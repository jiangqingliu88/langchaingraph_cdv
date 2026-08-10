"""
回归管理器Agent —— 使用回归框架 RegressionRunner + ShellGenerator + Scheduler
"""
from typing import Dict, List, Any
import json
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


@register_agent("regression_manager")
class RegressionManager(BaseAgent):
    """回归管理器Agent —— 编译 + 仿真 + 结果分析"""

    task_type = "regression_management"
    consumes = ["env", "tests"]
    produces = "regression"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="regression_manager",
            display_name="回归管理器",
            description="管理回归测试执行和结果分析",
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
        """
        ctx = task.get("ctx", {})
        input_text = task.get("input", "")
        output_dir = task.get("output_dir", "output")

        # ── 快速路径：如果是 retry/retry-failed 模式，直接走工具 ──
        fast_track = False
        try:
            input_data = json.loads(input_text) if isinstance(input_text, str) else input_text
            if input_data.get("retry") or input_data.get("fix"):
                fast_track = True
        except (json.JSONDecodeError, TypeError):
            pass

        if fast_track:
            return await self._execute_deterministic(ctx, output_dir)
        return await super().execute_task(task)

    async def _execute_deterministic(self, ctx, output_dir: str) -> AgentResult:
        """确定性执行：编译 → 仿真 → 报告（不走 LLM）。

        只有 compile、simulation 或 report 步骤中任意一步失败时，
        才会调用 LLM 分析失败原因。
        """
        import time

        # 1. 编译
        env = ctx.get("env", {}) if hasattr(ctx, 'get') else {}
        filelist = env.get("filelist", "") if isinstance(env, dict) else ""
        top = env.get("env_name", "dut") if isinstance(env, dict) else "dut"
        compile_result = _compile_env.func(filelist, output_dir, f"{top}_bench_tb_top")

        try:
            compile_data = json.loads(compile_result)
        except json.JSONDecodeError:
            compile_data = {"status": "FAIL", "error": compile_result}

        if compile_data.get("status") != "PASS":
            # 编译失败 → 用 LLM 分析（这需要推理）
            return await super().execute_task({
                "ctx": ctx,
                "input": json.dumps({"compile_failed": True, "compile_result": compile_data,
                                     "fix": True, "errors": compile_data.get("errors", [])[:5]}),
                "output_dir": output_dir,
            })

        # 2. 仿真
        tests = ctx.get("tests", {}) if hasattr(ctx, 'get') else {}
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
                }, ensure_ascii=False),
                "output_dir": output_dir,
            })
            return analysis_result

        # 全部成功 → 直接返回
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


# ── 真实覆盖率解析 ──

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
        r = subprocess.run([vcover, "report", "-details", str(ucdb)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=60)
        text = r.stdout
    except Exception:
        return {"source": "vcover_error", "overall_pct": 0.0}

    def _pct(pattern):
        m = re.search(pattern + r"[:\s]+(\d+\.?\d*)\s*%", text, re.IGNORECASE)
        return round(float(m.group(1)), 1) if m else 0.0

    coverage = {
        "source": "questa_vcover",
        "line_pct": _pct("Line"),
        "branch_pct": _pct("Branch"),
        "toggle_pct": _pct("Toggle"),
        "fsm_pct": _pct("FSM States"),
        "statement_pct": _pct("Statement"),
        "condition_pct": _pct("Condition"),
        "expression_pct": _pct("Expression"),
    }
    vals = [v for v in coverage.values() if isinstance(v, float) and v > 0]
    coverage["overall_pct"] = round(sum(vals) / len(vals), 1) if vals else 0.0

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
def _compile_env(filelist: str, output_dir: str, top_module: str) -> str:
    """编译 UVM 环境 + RTL 设计。输入: filelist路径, output目录, top模块名。返回编译结果JSON。"""
    od = Path(output_dir)

    # ── 自动修正 LLM 可能传错的参数 ──
    # 1. 修正 filelist 路径 — RTL-only 优先（不依赖 UVM）
    fl_path = None
    rtl_dir = od / "rtl"
    if rtl_dir.exists() and list(rtl_dir.glob("*.sv")):
        # 始终构建 RTL-only filelist
        fl_path = od / "inputs" / "filelists" / "filelist_rtl.f"
        lines = [str(sv.resolve()) for sv in sorted(rtl_dir.glob("*.sv"))]
        fl_path.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    if not fl_path:
        fl_path = Path(filelist) if filelist else None
    filelist = str(fl_path.resolve()) if fl_path else filelist

    # 2. 修正 top_module — 优先用 RTL-only 最小覆盖路径
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
    )
    result = runner.compile()
    return json.dumps(result, ensure_ascii=False)


@tool("run_simulation")
def _run_simulation(output_dir: str, tests_json: str) -> str:
    """执行仿真测试。tests_json: [{"name":"test_xxx","uvm_test":"..."}...]。返回仿真结果。"""
    try:
        tests = json.loads(tests_json) if isinstance(tests_json, str) else tests_json
    except json.JSONDecodeError:
        return json.dumps({"error": "invalid tests_json format"})

    # Save regression test list to YAML
    test_yaml_dir = Path(output_dir) / "inputs" / "yaml" / "dut_test"
    test_yaml_dir.mkdir(parents=True, exist_ok=True)
    import yaml as _yaml
    reg_path = test_yaml_dir / "regression.yaml"
    # Append tests to existing regression config
    reg_data = {}
    if reg_path.exists():
        reg_data = _yaml.safe_load(reg_path.read_text(encoding="utf-8", errors="replace")) or {}
    reg_data["tests"] = tests
    reg_path.write_text(
        _yaml.dump(reg_data, default_flow_style=False, allow_unicode=True, sort_keys=False),
        encoding="utf-8", errors="replace")

    results = []
    # Try to find bench top module
    bench_dir = Path(output_dir) / "bench"
    default_top = ""
    if bench_dir.exists():
        svs = list(bench_dir.glob("*_tb_top.sv"))
        if svs:
            default_top = svs[0].stem

    for t in tests:
        top = t.get("top", default_top) or "tb_top"
        runner = RegressionRunner(
            env_output_dir=output_dir,
            top_module=top,
            coverage=True,
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
