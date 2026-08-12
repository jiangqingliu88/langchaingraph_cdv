"""
回归管理器Agent —— 使用回归框架 RegressionRunner + ShellGenerator + Scheduler
"""
from typing import Dict, List, Any
import json, re, yaml, os, sys, subprocess
from pathlib import Path
from datetime import datetime

from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.json import JsonReporter
from src.tools.regression_tools.regression_framwork.src.regression_framework.reporters.html import HtmlReporter
import structlog

logger = structlog.get_logger()


@register_agent("regress")
class RegressAgent(BaseAgent):
    """失败聚类器 —— 聚类回归失败 + 识别共同根因模式"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="regress",
            display_name="回归管理器",
            description="聚类回归失败模式，识别共同根因",
            config=config or {}
        )

    async def _setup(self):
        from src.core.agent_tools import register_all_tools
        self.tool_registry = register_all_tools()
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """Role: Regression Test Manager
Goal: Compile UVM env, run simulation tests, collect pass/fail rates, generate reports.

WORKFLOW (execute in order):
1. CALL compile_env(filelist, output_dir, top_module)
   → Returns a compile result containing status, error count, and elapsed seconds.
   IF status == "FAIL" → report failures, stop.
2. CALL run_simulation(output_dir, tests_json)
   → tests_json is a JSON array of test objects with name, uvm_test, top, and coverage fields.
   → Returns test results with passed, failed, and total counts.
3. CALL generate_regression_report(output_dir, tasks_json)
   → tasks_json uses results from step 2, including name, status, elapsed, sim_time, and work_dir.
   → Returns JSON and HTML report paths.

OUTPUT FORMAT:
Return an object with compile, passed, failed, total, pass_rate, and reports fields.

RULES:
- Derive top_module from env_name in the supplied input.
- If compile fails, DO NOT run simulation. Report the errors.
- Collect ALL test results before generating report.
            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            _compile_env,
            _run_simulation,
            _generate_regression_report,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    async def _post_process(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """提取回归结果 + 真实覆盖率"""
        output_text = result.get("output", "") if isinstance(result, dict) else str(result)
        from src.core.base import _extract_json_from_llm
        data = _extract_json_from_llm(output_text)

        # 尝试从 ucdb 读取真实覆盖率
        coverage = {}
        try:
            from pathlib import Path as _P
            for search in [_P("output"), _P(".")]:
                for ucdb in search.rglob("merged.ucdb"):
                    cov = _collect_real_coverage(ucdb.parent.parent.parent)
                    if cov and cov.get("overall_pct", 0) > 0:
                        coverage = cov
                        break
                if coverage:
                    break
        except Exception:
            pass

        if data:
            result["regression"] = data
            if coverage:
                data["coverage"] = coverage
            passed = data.get("passed", 0)
            total = data.get("total", 1)
            # 加权：编译+仿真通过 = 基分50，覆盖率贡献最高45分
            cov_pct = coverage.get("overall_pct", 0)
            result["score"] = min(50 + int(cov_pct * 0.45), 95) if coverage else 10
        elif coverage:
            result["regression"] = {"compile": "PASS", "sim": "PASS", "coverage": coverage}
            result["score"] = min(50 + int(coverage.get("overall_pct", 0) * 0.45), 95)
        else:
            result["score"] = 10
        return result

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """优化后的执行：确定性工具编排不使用 LLM，只有失败聚类分析用 LLM。

        对标 llm_vs_traditional_tools_analysis.md 的优化建议：
        - compile → simulate → report 是确定性流程 → 传统工具执行
        - 失败聚类 + 根因建议 → LLM 推理

        新增：如果 output 目录下存在 inputs/yaml/regression.yaml（由 find_spec_yaml 生成），
        始终走确定性路径，用 YAML 中的测试列表驱动回归执行。
        """
        ctx = task.get("ctx", {})
        input_text = task.get("input", "")
        raw_output_dir = task.get("output_dir", "output")

        # ── 解析 output_dir ──
        from src.core.output_config import make_output_root
        output_dir = make_output_root(raw_output_dir)
        task["output_dir"] = output_dir

        # ── 快速路径：检测 regression.yaml 存在 + 有 tests → 走确定性 CLI ──
        reg_yaml = _load_regression_yaml(output_dir)
        fast_track = bool(reg_yaml and reg_yaml.get("tests"))
        if not fast_track:
            logger.warning(f"Regress: no regression.yaml found at {output_dir}/inputs/yaml/regression.yaml, falling back to LLM")
        try:
            input_data = json.loads(input_text) if isinstance(input_text, str) else input_text
            if input_data.get("retry") or input_data.get("fix") or input_data.get("analyze_failures"):
                fast_track = True
        except (json.JSONDecodeError, TypeError):
            pass

        # ── 检测 regression.yaml 存在 → 走确定性路径 ──
        if not fast_track:
            reg_yaml = _load_regression_yaml(output_dir)
            if reg_yaml and reg_yaml.get("tests"):
                logger.info(f"Regression YAML found with {len(reg_yaml['tests'])} tests → deterministic path",
                            output_dir=output_dir)
                fast_track = True

        if fast_track:
            return await self._execute_deterministic(ctx, output_dir)
        return await super().execute_task(task)

    async def _execute_deterministic(self, ctx, output_dir: str) -> AgentResult:
        """确定性执行：直接调用回归框架 CLI。

        regression.py 是独立 CLI 工具，subprocess 调用比内部集成更稳定：
          python regression.py --config <yaml> --action all --mode local

        如果 regression.yaml 不存在，回退到 RegressionRunner 薄封装。
        """
        reg_yaml_path = Path(output_dir) / "inputs" / "yaml" / "regression.yaml"

        if not reg_yaml_path.exists():
            logger.info("No regression.yaml found, falling back to RegressionRunner",
                        output_dir=output_dir)
            return await self._execute_legacy(ctx, output_dir)

        # ── 调用回归框架 CLI ──
        framework_dir = Path(__file__).parent.parent.parent / "tools" / "regression_tools" / "regression_framwork"
        regression_py = framework_dir / "regression.py"

        if not regression_py.exists():
            logger.warning(f"regression.py not found at {regression_py}, falling back")
            return await self._execute_legacy(ctx, output_dir)

        str_yaml = str(reg_yaml_path.resolve())
        # regression.py 生成的回归根目录放在 output_dir/regression 下
        regression_output = str(Path(output_dir).resolve() / "regression")

        cmd = [
            sys.executable, str(regression_py),
            "--config", str_yaml,
            "--action", "all",
            "--mode", "local",
            "--output-dir", regression_output,
        ]

        logger.info(f"Running regression framework: {' '.join(cmd)}")

        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=600,
                             cwd=str(Path.cwd().resolve()))
        except subprocess.TimeoutExpired:
            logger.error("Regression framework timed out (600s)")
            return await self._execute_legacy(ctx, output_dir)

        if r.returncode != 0:
            logger.warning(f"regression.py exit={r.returncode}")
            logger.warning(f"regression.py stdout: {r.stdout[:500]}")
            logger.warning(f"regression.py stderr: {r.stderr[:500]}")
            # 尝试从输出中提取已有结果
        else:
            logger.info(f"regression.py completed successfully")

        # ── 解析回归结果 ──
        summary_path = Path(regression_output) / "report_summary.txt"
        report_json_path = Path(regression_output) / "report.json"
        report_html_path = Path(regression_output) / "report.html"

        passed, failed, total = 0, 0, 0
        if summary_path.exists():
            summary = summary_path.read_text(encoding="utf-8", errors="replace")
            for line in summary.split("\n"):
                line = line.strip()
                if line.startswith("Pass:") or line.startswith("pass"):
                    try: passed = int(line.split(":")[-1].strip())
                    except: pass
                elif line.startswith("Fail:") or line.startswith("fail"):
                    try: failed = int(line.split(":")[-1].strip())
                    except: pass
                elif line.startswith("Total"):
                    try: total = int(line.split(":")[-1].strip().split()[0])
                    except: pass

        if total == 0:
            # 从 regression.yaml 的 test count 估算
            import yaml as _y
            try:
                reg_data = _y.safe_load(reg_yaml_path.read_text(encoding="utf-8", errors="replace"))
                total = len(reg_data.get("tests", []))
            except: pass

        # ── 复制报告到 output_dir ──
        import shutil
        root = Path(output_dir)
        for src_name in ["report.json", "report.html", "report_summary.txt"]:
            src = Path(regression_output) / src_name
            dst = root / src_name
            if src.exists() and not dst.exists():
                shutil.copy2(str(src), str(dst))

        # ── 收集覆盖率 ──
        coverage = _collect_real_coverage(Path(output_dir))

        # ── 失败 → LLM 分析 ──
        if failed > 0:
            return await super().execute_task({
                "ctx": ctx,
                "input": json.dumps({
                    "analyze_failures": True,
                    "compile": "PASS" if r.returncode == 0 else "FAIL",
                    "sim": {"passed": passed, "failed": failed, "total": total},
                    "fix": True,
                }, ensure_ascii=False),
                "output_dir": output_dir,
            })

        return AgentResult(success=True, data={
            "compile": "PASS",
            "passed": passed,
            "failed": failed,
            "total": max(total, 1),
            "pass_rate": f"{passed * 100 // max(total, 1)}%",
            "coverage": coverage,
            "reports": {
                "json": str(report_json_path) if report_json_path.exists() else str(root / "report.json"),
                "html": str(report_html_path) if report_html_path.exists() else str(root / "report.html"),
            },
            "framework": "regression.py CLI",
        })

    async def _execute_legacy(self, ctx, output_dir: str) -> AgentResult:
        """回退路径：使用 RegressionRunner 薄封装直接调 vlog/vsim。"""
        import time

        reg_yaml = _load_regression_yaml(output_dir)

        # 1. 编译
        if reg_yaml:
            filelist = reg_yaml.get("filelist", "")
            bench_top = reg_yaml.get("bench_top", "")
            top = reg_yaml.get("top_module", "dut")
            compile_top = bench_top or f"{top}_bench_tb_top"
        else:
            env = ctx.get("env", {}) if hasattr(ctx, 'get') else {}
            filelist = env.get("filelist", "") if isinstance(env, dict) else ""
            top = env.get("env_name", "dut") if isinstance(env, dict) else "dut"
            compile_top = f"{top}_bench_tb_top"

        compile_result = _compile_env.func(filelist, output_dir, compile_top)

        try:
            compile_data = json.loads(compile_result)
        except json.JSONDecodeError:
            compile_data = {"status": "FAIL", "error": compile_result}

        if compile_data.get("status") != "PASS":
            return await super().execute_task({
                "ctx": ctx,
                "input": json.dumps({"compile_failed": True, "compile_result": compile_data,
                                     "fix": True, "errors": compile_data.get("errors", [])[:5]}),
                "output_dir": output_dir,
            })

        # 2. 仿真
        if reg_yaml and reg_yaml.get("tests"):
            tests_list = reg_yaml["tests"]
            bench_top = reg_yaml.get("bench_top", "")
            for t in tests_list:
                if not t.get("top"):
                    t["top"] = bench_top
            tests_json = json.dumps(tests_list, ensure_ascii=False)
            logger.info(f"Running {len(tests_list)} tests from regression.yaml", output_dir=output_dir)
        else:
            tests = ctx.get("tests", {}) if hasattr(ctx, 'get') else {}
            if isinstance(tests, dict) and tests.get("test_cases"):
                test_cases = tests.get("test_cases", [])
                env = ctx.get("env", {}) if hasattr(ctx, 'get') else {}
                env_name = env.get("env_name", "") if isinstance(env, dict) else ""
                bench_top = f"{env_name}_bench_tb_top" if env_name else ""
                tests_list = []
                for tc in test_cases:
                    if isinstance(tc, dict):
                        tests_list.append({
                            "name": tc.get("name", "test"),
                            "uvm_test": tc.get("uvm_test", tc.get("name", "test")),
                            "top": bench_top,
                        })
                tests_json = json.dumps(tests_list, ensure_ascii=False) if tests_list else "[]"
            else:
                tests_json = json.dumps(tests, ensure_ascii=False) if tests else "[]"
        sim_result = _run_simulation.func(output_dir, tests_json)

        try:
            sim_data = json.loads(sim_result)
        except json.JSONDecodeError:
            sim_data = {"passed": 0, "total": 0, "failed": 0}

        # 3. 生成报告
        tasks_json = json.dumps([
            {"name": t.get("name", f"test_{i}"),
             "status": "passed", "elapsed": t.get("elapsed", 0)}
            for i, t in enumerate(sim_data.get("tests", [sim_data]))],
            ensure_ascii=False)
        report_result = _generate_regression_report.func(output_dir, tasks_json)

        # 4. 如果有失败 → LLM 聚类分析
        failed = sim_data.get("failed", 0) if isinstance(sim_data, dict) else 0
        if failed > 0:
            analysis_result = await super().execute_task({
                "ctx": ctx,
                "input": json.dumps({
                    "analyze_failures": True,
                    "compile": compile_data,
                    "sim": sim_data,
                    "report": report_result,
                    "fix": True,
                }, ensure_ascii=False),
                "output_dir": output_dir,
            })
            return analysis_result

        passed = sim_data.get("passed", 0) if isinstance(sim_data, dict) else 0
        total = sim_data.get("total", 1) if isinstance(sim_data, dict) else 1
        return AgentResult(success=True, data={
            "compile": compile_data.get("status", "PASS"),
            "passed": passed,
            "failed": failed,
            "total": total,
            "pass_rate": f"{passed * 100 // max(total, 1)}%",
            "reports": report_result,
        })


# ── regression.yaml 解析 ──

def _load_regression_yaml(output_dir: str) -> dict | None:
    """从 inputs/yaml/regression.yaml 加载回归测试配置。

    返回 {top_module, filelist, bench_top, tests: [{name, uvm_test, top, tags, expect_errors}]}
    如果 YAML 不存在或解析失败返回 None。
    """
    reg_path = Path(output_dir) / "inputs" / "yaml" / "regression.yaml"
    if not reg_path.exists():
        return None

    try:
        data = yaml.safe_load(reg_path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    # ── 提取 top_module 和 bench_top ──
    # 从 settings.simulators.questa.run 命令中提取: "... -work <path> <top_module> {run_opts} ..."
    top_module = ""
    bench_top = ""
    simulators = data.get("settings", {}).get("simulators", {})
    questa = simulators.get("questa", {})
    run_cmd = questa.get("run", "")
    if run_cmd:
        # 匹配 vsim 命令中的顶层模块: vsim ... -work <path> <top_module> {run_opts}
        m = re.search(r'-work\s+\S+\s+(\S+)\s+\{run_opts\}', run_cmd)
        if m:
            bench_top = m.group(1)  # e.g. "apb_uart_bench_tb_top"
            # 去掉 _bench_tb_top 后缀得到基本模块名
            top_module = re.sub(r'_bench_tb_top$', '', bench_top)

    # ── 提取 filelist ──
    # 优先从 compile 命令中提取 -f <filelist_path>
    filelist = ""
    compile_cmd = questa.get("compile", "")
    fl_match = re.search(r'-f\s+(\S+)', compile_cmd)
    if fl_match:
        filelist = fl_match.group(1)
    # 回退：从 builds[0].files 取第一个 .f 文件
    if not filelist:
        builds = data.get("builds", [])
        if builds and isinstance(builds, list):
            build = builds[0]
            files = build.get("files", [])
            if files and isinstance(files, list):
                # 取第一个 .f 文件（filelist），而不是单个 RTL 文件
                for f in files:
                    if str(f).endswith('.f'):
                        filelist = str(f)
                        break
                if not filelist:
                    filelist = str(files[0])

    # ── 提取 tests ──
    tests = []
    raw_tests = data.get("tests", [])
    if not isinstance(raw_tests, list):
        raw_tests = []

    for i, t in enumerate(raw_tests):
        if not isinstance(t, dict):
            continue
        name = t.get("name", f"test_{i}")
        # 从 run_opts 中提取 +UVM_TESTNAME=xxx
        uvm_test = ""
        run_opts = t.get("run_opts", [])
        if isinstance(run_opts, list):
            for opt in run_opts:
                m = re.match(r'\+UVM_TESTNAME=(\S+)', str(opt))
                if m:
                    uvm_test = m.group(1)
                    break
        # 如果没找到 UVM_TESTNAME，从 name 构造
        if not uvm_test:
            uvm_test = f"{name}_test"

        expect = t.get("expect", {})
        tags = t.get("tags", [])
        tests.append({
            "name": name,
            "uvm_test": uvm_test,
            "top": bench_top,
            "tags": tags if isinstance(tags, list) else [],
            "expect_errors": expect.get("errors", 0) if isinstance(expect, dict) else 0,
            "count": t.get("count", 1),
            "desc": t.get("desc", ""),
        })

    if not bench_top:
        # 从 builds 推断
        build_name = builds[0].get("name", "") if builds else ""
        if build_name.startswith("build_"):
            module = build_name[6:]  # strip "build_"
            bench_top = f"{module}_bench_tb_top"
        if not top_module:
            top_module = module if module else ""

    return {
        "top_module": top_module,
        "bench_top": bench_top,
        "filelist": filelist,
        "tests": tests,
    }


# ── 真实覆盖率解析 ──

# ── 每测试 UCDB 注入与合并 ──

def _inject_per_test_ucdb(regression_dir: str, cov_ucdb_dir: str):
    """为每个 test 的 sim.sh 注入独立的 UCDB 保存路径。

    ShellGenerator 不支持 test_name 变量替换到 run 命令模板中，
    因此在生成脚本后、执行前，替换 sim.sh 中硬编码的 coverage save 路径。
    同时确保覆盖率目录在仿真前已创建。
    """
    import glob as _glob
    cov_dir_unix = cov_ucdb_dir.replace("\\", "/")
    for sim_sh in _glob.glob(os.path.join(regression_dir, "**/sim.sh"), recursive=True):
        test_dir = os.path.dirname(sim_sh)
        test_name = os.path.basename(test_dir)
        ucdb_path = f"{cov_dir_unix}/{test_name}.ucdb"

        content = Path(sim_sh).read_text(encoding="utf-8", errors="replace")
        # 在 mkdir waves 之后添加 coverage 目录创建
        if f"mkdir -p {cov_dir_unix}" not in content:
            content = content.replace(
                "#!/bin/bash\n",
                f"#!/bin/bash\nmkdir -p {cov_dir_unix}\n"
            )
        # 替换 coverage save 目标路径为 test-specific
        content = re.sub(
            r'coverage save -onexit\s+\S+?\.ucdb',
            f'coverage save -onexit {ucdb_path}',
            content
        )
        # 如果 sim.sh 没有 coverage save，在 vsim -do 中注入
        if 'coverage save' not in content:
            content = re.sub(
                r'(vsim\s+-c\s+)',
                r'\1-coverage ',
                content
            )
            content = re.sub(
                r'(-do\s+\')',
                rf'\1coverage save -onexit {ucdb_path}; ',
                content
            )
        Path(sim_sh).write_text(content, encoding="utf-8", errors="replace")
        logger.debug(f"Injected UCDB path: {test_name} → {ucdb_path}")


def _merge_ucdb_files(cov_ucdb_dir: str):
    """用 vcover merge 合并所有 per-test UCDB 文件。"""
    import glob as _glob
    ucdb_files = sorted(_glob.glob(os.path.join(cov_ucdb_dir, "test_*.ucdb")))
    if not ucdb_files:
        ucdb_files = sorted(_glob.glob(os.path.join(cov_ucdb_dir, "tp_*.ucdb")))
    if len(ucdb_files) < 2:
        return  # 不需要 merge

    merged = os.path.join(cov_ucdb_dir, "merged.ucdb")
    questa = os.environ.get("QUESTA_HOME", "f:/questasim64_2024.1/win64")
    vcover = os.path.join(questa, "vcover.exe")
    if not os.path.exists(vcover):
        vcover = os.path.join(questa, "win64", "vcover.exe")

    if not os.path.exists(vcover):
        logger.warning(f"vcover not found at {vcover}, skipping UCDB merge")
        return

    cmd = [vcover, "merge", "-out", merged] + ucdb_files
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=60)
        if r.returncode == 0:
            logger.info(f"Merged {len(ucdb_files)} UCDBs → {merged}")
        else:
            logger.warning(f"vcover merge failed: {r.stderr[:200]}")
    except Exception as e:
        logger.warning(f"vcover merge error: {e}")


def _collect_real_coverage(output_dir: Path) -> dict:
    """从 QuestaSim ucdb 提取覆盖率指标"""
    import subprocess, re, os
    ucdb = output_dir / "sim" / "coverage" / "merged.ucdb"
    if not ucdb.exists():
        # 尝试在单个 test 目录下找
        sim_dirs = list(output_dir.rglob("merged.ucdb"))
        if sim_dirs:
            ucdb = sim_dirs[0]
        else:
            return {"source": "no_ucdb_found", "overall_pct": 0.0}

    questa = os.environ.get("QUESTA_HOME", "f:/questasim64_2024.1/win64")
    vcover = os.path.join(questa, "vcover.exe")
    if not os.path.exists(vcover):
        return {"source": "vcover_not_found", "overall_pct": 0.0}

    try:
        r = subprocess.run([vcover, "report", "-recursive", "-code", "bcefs",
                          "-summary", str(ucdb)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
        text = r.stdout
    except Exception:
        return {"source": "vcover_error", "overall_pct": 0.0}

    def _pct(pattern):
        # Matches summary lines like: "    Branches    1685    66    1619    1    3.91%"
        m = re.search(r'^\s*' + pattern + r'\s+\d+\s+\d+\s+\d+\s+\d+\s+(\d+\.?\d*)\s*%',
                      text, re.MULTILINE | re.IGNORECASE)
        return round(float(m.group(1)), 1) if m else 0.0

    coverage = {
        "source": "questa_vcover",
        "line_pct": 0.0,
        "branch_pct": _pct("Branches"),
        "toggle_pct": _pct("Toggles"),
        "fsm_pct": _pct("FSM States"),
        "statement_pct": _pct("Statements"),
        "condition_pct": _pct("Conditions"),
        "expression_pct": _pct("Expressions"),
    }
    # Total coverage line: "Total coverage (filtered view): 3.48%"
    tm = re.search(r'Total coverage[^:]*:\s*(\d+\.?\d*)\s*%', text)
    coverage["overall_pct"] = round(float(tm.group(1)), 1) if tm else 0.0

    # 按实例分模块覆盖率
    inst_coverage = {}
    for m in re.finditer(r'=== Instance: /tb_minimal/(\S+) ===\n=== Design Unit: \S+ ===\n(.*?)(?=\n\Z|\n=== Instance)', text, re.DOTALL):
        inst_name = m.group(1).split("/")[-1]
        block = m.group(2)
        inst_coverage[inst_name] = {
            "branch_pct": _pct_in_block(block, "Branch"),
            "statement_pct": _pct_in_block(block, "Statement"),
            "fsm_pct": _pct_in_block(block, "FSM States"),
        }
    coverage["instances"] = inst_coverage

    return coverage


def _pct_in_block(block: str, pattern: str) -> float:
    import re
    m = re.search(pattern + r"[:\s]+.*?(\d+\.?\d*)\s*%.*?(\d+)\s*$", block, re.MULTILINE)
    if m:
        return round(float(m.group(1)), 1)
    return 0.0


def _ensure_minimal_tb(rtl_dir: Path, top_module: str):
    """生成最小 testbench 用于覆盖率收集"""
    tb_path = rtl_dir / "tb_minimal.sv"
    if tb_path.exists():
        return
    import re as _re

    # 读顶层模块的实际端口列表
    top_sv = rtl_dir / f"{top_module}.sv"
    ports = []
    clk_name, rst_name = "clk", "rst_n"
    if top_sv.exists():
        content = top_sv.read_text(encoding="utf-8", errors="replace")
        # 提取端口
        in_module = False
        for line in content.split('\n'):
            line = line.strip()
            if line.startswith('module '):
                in_module = True
                continue
            if in_module and line == ');':
                break
            if in_module and line:
                line = line.rstrip(',').strip()
                m = _re.match(r'(input|output)\s+(logic\s+)?(\[\d+:\d+\]\s+)?(\w+)', line)
                if m:
                    direction = m.group(1)
                    width = m.group(3) or ''
                    name = m.group(4)
                    ports.append({"name": name, "dir": direction, "width": width.strip()})
                    if "clk" in name.lower() and direction == "input":
                        clk_name = name
                    if "rst" in name.lower() and direction == "input":
                        rst_name = name

    # 生成 testbench
    tb_lines = [f"module tb_minimal;"]
    tb_lines.append(f"  reg {clk_name}=0, {rst_name}=0;")
    tb_lines.append(f"  always #5 {clk_name} = ~{clk_name};")

    # 为每个 input 端口声明 reg，每个 output 端口声明 wire
    for p in ports:
        if p["name"] in (clk_name, rst_name):
            continue
        w = p["width"]
        if p["dir"] == "input":
            tb_lines.append(f"  reg  {w+' ' if w else ''}{p['name']};")
        else:
            tb_lines.append(f"  wire {w+' ' if w else ''}{p['name']};")

    tb_lines.append("  integer i;")
    tb_lines.append("")

    # 例化
    conns = []
    for p in ports:
        conns.append(f"    .{p['name']}({p['name']})")
    tb_lines.append(f"  {top_module} u_dut (")
    tb_lines.append(",\n".join(conns))
    tb_lines.append("  );")
    tb_lines.append("")

    # 激励
    tb_lines.append("  initial begin")
    tb_lines.append("    $display(\"Coverage test starting...\");")
    tb_lines.append(f"    {rst_name}=0; #20; {rst_name}=1; #20;")
    tb_lines.append("    // Random stimulus (avoid randomizing clock/reset)")
    tb_lines.append("    for(i=0; i<500; i=i+1) begin")
    # 随机化所有 input 端口（除了 clock 和 reset）
    inputs = [p["name"] for p in ports if p["dir"] == "input" and p["name"] not in (clk_name, rst_name)]
    for inp in inputs:
        if "rst" not in inp.lower() and "preset" not in inp.lower():
            tb_lines.append(f"      {inp} <= $random;")
    tb_lines.append("      #10;")
    tb_lines.append("    end")
    tb_lines.append("    #200;")
    tb_lines.append("    $display(\"Coverage test complete.\");")
    tb_lines.append("    $finish;")
    tb_lines.append("  end")
    tb_lines.append("endmodule")

    tb_path.write_text("\n".join(tb_lines), encoding="utf-8", errors="replace")


# ── LangChain Tools ──

from langchain.tools import tool

@tool("compile_env")
def _get_compile_sim_dirs(output_dir):
    """返回 (compile_dir, sim_dir) 元组。"""
    from src.tools.lib.regress_dir import get_compile_dir, get_sim_dir
    return get_compile_dir(output_dir), get_sim_dir(output_dir)


def _compile_env(filelist: str, output_dir: str, top_module: str) -> str:
    """编译 UVM 环境 + RTL 设计。输入: filelist路径, output目录, top模块名。返回编译结果JSON。"""
    od = Path(output_dir)
    compile_dir, _ = _get_compile_sim_dirs(output_dir)

    # ── 自动修正 LLM 可能传错的参数 ──
    # 1. 修正 filelist 路径 — 优先用传入的 filelist（可能包含完整 UVM 环境）
    fl_path = None
    if filelist:
        candidate = Path(filelist)
        if candidate.exists():
            fl_path = candidate
    # 回退：从 regression.yaml 的 builds[0].files 获取
    if not fl_path:
        reg = _load_regression_yaml(output_dir)
        if reg and reg.get("filelist"):
            candidate = Path(reg["filelist"])
            if candidate.exists():
                fl_path = candidate
    # 回退：构建 RTL-only filelist（不包含 UVM bench，仅用于 RTL 语法检查）
    if not fl_path:
        rtl_dir = od / "rtl"
        if rtl_dir.exists() and list(rtl_dir.glob("*.sv")):
            fl_path = od / "inputs" / "filelists" / "filelist_rtl.f"
            lines = [str(sv.resolve()) for sv in sorted(rtl_dir.glob("*.sv"))]
            fl_path.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    filelist = str(fl_path.resolve()) if fl_path else filelist

    # 2. 修正 top_module — 如果已传入 _tb_top 或 _bench 结尾的模块名，直接使用
    if not (top_module.endswith("_tb_top") or "_bench_tb_top" in top_module):
        rtl_dir = od / "rtl"
        if rtl_dir.exists():
            rtl_files = sorted(rtl_dir.glob("*.sv"))
            # 找顶层模块（例化了子模块的那个：行如 "  MOD_NAME u_MOD_NAME ("）
            import re as _re2
            top_candidate = None
            for sv in rtl_files:
                content = sv.read_text(encoding="utf-8", errors="replace")
                inst_count = len(_re2.findall(r'^\s+\w+\s+u_\w+\s*\(', content, _re2.MULTILINE))
                if inst_count >= 2:
                    top_candidate = sv
                    break
            if top_candidate:
                top_module = top_candidate.stem
                _ensure_minimal_tb(rtl_dir, top_module)
            elif rtl_files:
                top_module = rtl_files[-1].stem

    if not top_module:
        top_module = "tb_top"

    # Save regression compile config
    test_yaml_dir = od / "inputs" / "yaml" / "dut_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    compile_cfg = {
        "regression": {
            "filelist": filelist,
            "top_module": top_module,
            "output_dir": output_dir,
            "coverage": True,
        }
    }
    (test_yaml_dir / "regression.yaml").write_text(
        _yaml.dump(compile_cfg, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8", errors="replace")

    runner = RegressionRunner(
        env_output_dir=output_dir,
        filelist=filelist,
        top_module=top_module,
        coverage=True,
        compile_dir=compile_dir,
    )
    result = runner.compile()
    return json.dumps(result, ensure_ascii=False)


@tool("run_simulation")
def _run_simulation(output_dir: str, tests_json: str) -> str:
    """执行仿真测试。tests_json: [{"name":"test_xxx","uvm_test":"..."}...]。返回仿真结果。

    如果 tests_json 为空或无效，自动从 inputs/yaml/regression.yaml 加载测试列表。
    """
    try:
        tests = json.loads(tests_json) if isinstance(tests_json, str) else tests_json
    except json.JSONDecodeError:
        tests = []

    # ── 回退：从 regression.yaml 加载测试 ──
    if not tests or not isinstance(tests, list) or len(tests) == 0:
        reg = _load_regression_yaml(output_dir)
        if reg and reg.get("tests"):
            tests = reg["tests"]
            logger.info(f"run_simulation: loaded {len(tests)} tests from regression.yaml (fallback)",
                        output_dir=output_dir)
    if not isinstance(tests, list):
        tests = []
    if len(tests) == 0:
        return json.dumps({"passed": 0, "total": 0, "failed": 0,
                          "error": "no tests specified and no regression.yaml found"})

    # Save regression test list to YAML
    test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "dut_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    reg_path = test_yaml_dir / "regression.yaml"
    # Append tests to existing regression config
    reg_data = {}
    if reg_path.exists():
        try:
            reg_data = yaml.safe_load(reg_path.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:
            reg_data = {}
    reg_data["tests"] = tests
    reg_path.write_text(
        yaml.dump(reg_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8", errors="replace")

    results = []
    # Try to find bench top module
    bench_dir = Path(output_dir) / "bench"
    default_top = ""
    if bench_dir.exists():
        svs = list(bench_dir.glob("*_tb_top.sv"))
        if svs:
            default_top = svs[0].stem

    compile_dir, sim_dir = _get_compile_sim_dirs(output_dir)

    for t in tests:
        top = t.get("top", default_top) or "tb_top"
        runner = RegressionRunner(
            env_output_dir=output_dir,
            top_module=top,
            coverage=True,
            compile_dir=compile_dir,
            sim_dir=sim_dir,
        )
        r = runner.collect_coverage(
            test_name=t.get("name", "test"),
            uvm_test=t.get("uvm_test", ""),
        )
        results.append(r)

    passed = sum(1 for r in results if r.get("status") == "PASS")

    # ── 从 ucdb 收集真实覆盖率 ──
    coverage_data = _collect_real_coverage(Path(output_dir))

    return json.dumps({
        "tests": results,
        "passed": passed,
        "failed": len(results) - passed,
        "total": len(results),
        "coverage": coverage_data,
    }, ensure_ascii=False, default=str)


@tool("generate_regression_report")
def _generate_regression_report(output_dir: str, tasks_json: str) -> str:
    """生成回归报告（JSON + HTML）。tasks_json: [{"name":"","status":"","elapsed":0,...}]。返回报告路径。"""
    from src.tools.regression_tools.regression_framwork.src.regression_framework.models.task import Task

    try:
        task_dicts = json.loads(tasks_json) if isinstance(tasks_json, str) else tasks_json
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid tasks_json format"})

    class SimpleTask:
        def __init__(self, d):
            self.name = d.get("name", "")
            self.status = d.get("status", "unknown")
            self.work_dir = d.get("work_dir", "")
            self.elapsed = d.get("elapsed", 0)
            self.job_id = d.get("job_id", "")
            self.fingerprint = d.get("fingerprint", "")
            self.sim_time = d.get("sim_time", 0)
            self.wave_path = d.get("wave_path", "")
            self.performance_degraded = d.get("performance_degraded", False)

    tasks = [SimpleTask(d) for d in task_dicts]

    root = Path(output_dir)
    json_reporter = JsonReporter()
    html_reporter = HtmlReporter()
    json_reporter.generate(tasks, str(root))
    html_reporter.generate(tasks, str(root))

    return json.dumps({
        "report_json": str(root / "report.json"),
        "report_html": str(root / "report.html"),
        "status": "generated",
    })


# ═══════════════════════════════════════════════════════════════
# RegressCovAgent: regress + cover 合并，带覆盖率闭环反馈
# ═══════════════════════════════════════════════════════════════

@register_agent("regress_cov")
class RegressCovAgent(RegressAgent):
    """回归与覆盖率管理器 —— 编译仿真→收集覆盖率→分析gap→建议增补case。

    继承 RegressAgent 的编译/仿真/报告能力，新增:
      - 覆盖率 gap 分析（对比 spec coverage_goals）
      - 结构化增补建议（可直接喂给 TestAgent）
      - 闭环重试逻辑（覆盖率不达标则回退 test 补 case）
    """

    COVERAGE_TARGET = 95.0

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config=config or {})
        self.role = "regress_cov"
        self.display_name = "回归与覆盖率管理器"
        self.description = "编译仿真→覆盖率→gap分析→增补建议，闭环迭代直到覆盖率收敛"
        self.task_type = "regression_management"
        self.consumes = ["env", "tests"]
        self.produces = "regression"

    async def _setup(self):
        """确定性工具注册，不走 LLM AgentExecutor。"""
        from src.core.agent_tools import register_all_tools
        self.tool_registry = register_all_tools()

    async def _get_tools(self):
        # 返回空列表：确定性执行不走 LangChain AgentExecutor
        # 工具通过 execute_task → _execute_deterministic 直接调用
        return []

    # ── 覆盖率 gap 分析 ──

    def analyze_coverage_gaps(self, coverage_data: dict, spec_data: dict = None) -> dict:
        """分析覆盖率 gap，返回结构化报告。

        coverage_data: 来自 _collect_real_coverage 的覆盖率数据
        spec_data: 可选的 spec JSON (含 coverage_goals)
        返回: {gaps, coverage_pct, target_pct, recommend_rerun, converged}
        """
        overall = coverage_data.get("overall_pct", coverage_data.get("coverage_pct", 0))
        line_pct = coverage_data.get("line_pct", 0)
        branch_pct = coverage_data.get("branch_pct", 0)
        toggle_pct = coverage_data.get("toggle_pct", 0)

        target = self.COVERAGE_TARGET
        if spec_data:
            cg = spec_data.get("coverage_goals", {})
            if isinstance(cg, dict):
                target = cg.get("code_coverage", cg.get("functional_coverage", target))
                if isinstance(target, str):
                    try:
                        target = float(target)
                    except ValueError:
                        target = self.COVERAGE_TARGET

        gaps = []
        if line_pct < target:
            gaps.append({"metric": "line_coverage", "current": line_pct, "target": target,
                         "gap": round(target - line_pct, 1)})
        if branch_pct < target:
            gaps.append({"metric": "branch_coverage", "current": branch_pct, "target": target,
                         "gap": round(target - branch_pct, 1)})
        if toggle_pct < target:
            gaps.append({"metric": "toggle_coverage", "current": toggle_pct, "target": target,
                         "gap": round(target - toggle_pct, 1)})

        # 功能覆盖率 gap (来自 spec coverage_goals 的 bool 字段)
        func_gaps = []
        if spec_data:
            cg = spec_data.get("coverage_goals", {})
            for key, val in cg.items():
                if isinstance(val, bool) and not val:
                    func_gaps.append({"feature": key, "status": "uncovered",
                                      "suggestion": f"Add directed test for {key}"})
                elif isinstance(val, dict):
                    uncovered = [k for k, v in val.items() if isinstance(v, bool) and not v]
                    if uncovered:
                        func_gaps.append({"feature": key, "uncovered_items": uncovered,
                                          "suggestion": f"Add test covering {key}: {uncovered}"})

        converged = overall >= target and len(gaps) == 0 and len(func_gaps) == 0

        return {
            "coverage_pct": overall,
            "line_pct": line_pct,
            "branch_pct": branch_pct,
            "toggle_pct": toggle_pct,
            "target_pct": target,
            "converged": converged,
            "recommend_rerun": not converged,
            "gaps": gaps,
            "functional_gaps": func_gaps,
        }

    # ── 增补 case 建议 ──

    def suggest_coverage_tests(self, gap_analysis: dict) -> list:
        """根据 gap 分析生成结构化增补建议，可直接消费。

        返回: [{feature, reason, suggested_scenario, policies, priority}]
        """
        suggestions = []
        for gap in gap_analysis.get("gaps", []):
            suggestions.append({
                "feature": gap["metric"],
                "reason": f"Current {gap['current']}% < target {gap['target']}% (gap: {gap['gap']}%)",
                "suggested_scenario": f"boost_{gap['metric']}",
                "policies": [],
                "priority": "P1",
            })

        for fg in gap_analysis.get("functional_gaps", []):
            suggestions.append({
                "feature": fg["feature"],
                "reason": f"Functional coverage not hit: {fg.get('uncovered_items', fg['feature'])}",
                "suggested_scenario": f"cover_{fg['feature']}",
                "policies": [],
                "priority": "P1",
                "uncovered_items": fg.get("uncovered_items", []),
            })

        return suggestions

    # ── 闭环执行 ──

    async def execute_with_retry(self, task: Dict[str, Any], max_retries: int = 2) -> Dict[str, Any]:
        """执行回归 + 覆盖率分析，不达标则返回增补建议触发 test 重跑。

        返回: {result, coverage_gap, suggestions, retry_count, converged}
        """
        retry_count = 0
        all_suggestions = []

        while retry_count <= max_retries:
            # 执行回归
            result = await self.execute_task(task)

            # 收集覆盖率
            output_dir = task.get("output_dir", "output")
            coverage = _collect_real_coverage(Path(output_dir))

            # 读取 spec 做对比
            spec_data = None
            spec_path = Path(output_dir) / "spec.json"
            if spec_path.exists():
                try:
                    spec_data = json.loads(spec_path.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    pass

            # 分析 gap
            gap_analysis = self.analyze_coverage_gaps(coverage, spec_data)

            if gap_analysis["converged"]:
                logger.info(f"Coverage converged at {gap_analysis['coverage_pct']}% after {retry_count} retries",
                            output_dir=output_dir)
                return {
                    "result": result,
                    "coverage": coverage,
                    "gap_analysis": gap_analysis,
                    "retry_count": retry_count,
                    "converged": True,
                }

            # 生成建议
            suggestions = self.suggest_coverage_tests(gap_analysis)
            all_suggestions.extend(suggestions)

            logger.warning(f"Coverage gap: {gap_analysis['coverage_pct']}% < {gap_analysis['target_pct']}%, "
                           f"suggestions: {len(suggestions)}, retry {retry_count+1}/{max_retries}",
                           output_dir=output_dir)

            if retry_count >= max_retries:
                break

            retry_count += 1
            # 通知 test agent 补 case（通过 task ctx 传递建议）
            task["input"] = json.dumps({
                "action": "supplement_cases",
                "suggestions": suggestions,
                "coverage_gap": gap_analysis,
            })

        return {
            "result": result,
            "coverage": coverage,
            "gap_analysis": gap_analysis,
            "suggestions": all_suggestions,
            "retry_count": retry_count,
            "converged": False,
        }
