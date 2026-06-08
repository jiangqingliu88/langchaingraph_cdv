"""
测试工程师 Agent —— 合并 sequence_engineer + testcase_engineer

   spec + env → constraint policies → scenarios → SV 测试代码 + simargs/run.sh + 覆盖率检查

   工具集: src/tools/testcase/tools.py (6 个 @tool)
   生成器: src/tools/testcase/generator.py
"""
from typing import Dict, List, Any
from datetime import datetime as dt
import json, os, tempfile, yaml
from pathlib import Path

from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.testcase.tools import (
    parse_test_points,
    map_policies_to_tests,
    build_scenario_yaml,
    build_priority_rules,
    generate_test_cases,
    check_test_coverage,
)
import structlog

logger = structlog.get_logger()


def _extract_test_points(raw_input: str, ctx: dict = None) -> dict:
    """兼容 pipeline 结构化输入 / 原始 spec JSON / 已处理的 categories"""
    ctx = ctx or {}
    try:
        data = json.loads(raw_input) if isinstance(raw_input, str) else raw_input
    except (json.JSONDecodeError, TypeError):
        data = {}

    if isinstance(data, dict):
        if "test_points" in data and isinstance(data["test_points"], list):
            raw_tp = data["test_points"]
        elif "categories" in data:
            return data
        elif ctx.get("spec", {}).get("test_points"):
            raw_tp = ctx["spec"]["test_points"]
        else:
            raw_tp = data.get("test_points", [])
    else:
        raw_tp = []

    raw_func = parse_test_points.func if hasattr(parse_test_points, 'func') else parse_test_points
    result = json.loads(raw_func(json.dumps({"test_points": raw_tp}, ensure_ascii=False)))
    return result


@register_agent("test_engineer")
class TestEngineer(BaseAgent):
    """测试工程师 —— 策略→场景→测试代码→simargs 一站式生成"""

    task_type = "code_generation"
    consumes = ["spec", "env"]
    produces = "tests"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="test_engineer",
            display_name="测试工程师",
            description="约束策略→场景映射→SV测试代码→仿真参数一站式生成",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证测试工程师。

【职责】
1. 解析 spec_planner 输出的 test_points
2. 生成 constraint policies 约束策略
3. 映射 policies → 测试场景
4. 生成 SV 测试代码 + run.sh + simargs
5. 检查测试覆盖率

【工具】
- parse_test_points: spec JSON → 结构化测试列表
- map_policies_to_tests: 分类 → policies 场景映射
- build_scenario_yaml: 场景 JSON → YAML
- build_priority_rules: 策略 → 权重规则
- generate_test_cases: YAML → SV 代码 + run.sh
- check_test_coverage: 覆盖率对比

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [
            parse_test_points, map_policies_to_tests,
            build_scenario_yaml, build_priority_rules,
            generate_test_cases, check_test_coverage,
        ]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: spec + env → policies → scenarios → SV 代码 + simargs ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            # Hybrid: use bypass when ctx has required data
            ctx = task.get("ctx", {}) if isinstance(task, dict) else {}
            if ctx.get("spec"):
                task["bypass"] = True
            return await super().execute_task(task)

        start_time = dt.now()
        try:
            raw_input = task.get("input", str(task))
            output_dir = task.get("output_dir", "output/testcases")
            ctx = task.get("ctx", {})
            env_name = ctx.get("env", {}).get("env_name", "uart_env")
            env_output_dir = ctx.get("env", {}).get("output_dir", "generated/uart")
            self._last_prompt = "bypass: spec → policies → scenarios → SV tests + simargs"

            # ── Step 1: test_points → categories ──
            tp = _extract_test_points(raw_input, ctx)
            if "error" in tp:
                return AgentResult(success=False, error=tp["error"])

            # ── Step 2: 生成 constraint policies（原 sequence_engineer 职责）──
            policies = _build_policies(ctx, env_name)

            # ── Step 3: categories + policies → scenarios ──
            _mpt = map_policies_to_tests.func if hasattr(map_policies_to_tests, 'func') else map_policies_to_tests
            pnames = [p.get("name", p) if isinstance(p, dict) else p for p in policies]
            map_input = json.dumps(
                {"categories": tp["categories"], "available_policies": pnames},
                ensure_ascii=False
            )
            mapped = _mpt(map_input)
            scenarios_data = json.loads(mapped)

            # ── Step 4: scenarios → YAML ──
            _bsy = build_scenario_yaml.func if hasattr(build_scenario_yaml, 'func') else build_scenario_yaml
            yaml_str = _bsy(json.dumps(scenarios_data, ensure_ascii=False))

            # ── Step 5: YAML → SV files + run.sh + simargs ──
            from src.tools.testcase.generator import TestCaseGenerator as _TCG
            _tf = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
            try:
                _tf.write(yaml_str); _tf.close()
                _gen = _TCG(_tf.name)
                gen_summary = _gen.generate_all(output_dir)
            finally:
                try: os.unlink(_tf.name)
                except Exception: pass

            # ── Step 6: 生成 simargs（per-test plusargs）──
            simargs = _build_simargs(gen_summary, env_output_dir, env_name)

            # ── Step 7: coverage check ──
            _ctc = check_test_coverage.func if hasattr(check_test_coverage, 'func') else check_test_coverage
            cov_result = _ctc(json.dumps(tp, ensure_ascii=False), json.dumps(scenarios_data, ensure_ascii=False))
            cov = json.loads(cov_result)

            # ── Step 8: 逐 Case 调试（编译+仿真+分类）──
            case_results = _debug_each_case(
                output_dir, gen_summary, env_name, env_output_dir, ctx)

            # ── 汇总 ──
            summary = (
                f"Policies → {gen_summary['total_tests']} test scenarios\n"
                f"Output: {output_dir}\n"
                f"Env: {env_name}\n"
                f"Coverage: {cov.get('coverage_pct','?')} "
                f"({cov.get('covered',0)}/{cov.get('total_test_points',0)})\n"
            )
            for t in gen_summary.get("tests", []):
                cr = case_results.get(t.get("test_name", t.get("id", "")), {})
                status = cr.get("status", "?")
                issue = cr.get("issue", "")
                summary += f"  [{t['id']}] {t['test_name']}: {status} {issue}\n"

            # Case debug summary
            n_pass = sum(1 for c in case_results.values() if c.get("status") == "PASS")
            n_env  = sum(1 for c in case_results.values() if c.get("issue") == "ENV")
            n_rtl  = sum(1 for c in case_results.values() if c.get("issue") == "RTL")
            n_model = sum(1 for c in case_results.values() if c.get("issue") == "MODEL")
            n_skip = sum(1 for c in case_results.values() if c.get("status") == "SKIP")
            summary += (f"\n  Case Debug: {n_pass}PASS {n_env}ENV {n_rtl}RTL {n_model}MODEL {n_skip}SKIP")

            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += (dt.now() - start_time).total_seconds()

            return AgentResult(success=True, data={
                "output": summary,
                "tests": {
                    "output_dir": str(Path(output_dir).resolve()),
                    "scenario_count": gen_summary.get("total_tests", 0),
                    "coverage_pct": cov.get("coverage_pct", "0%"),
                    "scenarios": gen_summary.get("tests", []),
                    "simargs": simargs,
                    "case_results": case_results,
                },
                "policies": {"policies": policies},
                "yaml": yaml_str,
                "scenarios": scenarios_data,
                "coverage": cov,
                "files": [f["files"] for f in gen_summary.get("tests", [])],
                "score": min(5 * gen_summary.get("total_tests", 0)
                             + 5 * len(policies) + 5 * len(tp.get("categories", [])), 85),
            }, execution_time=(dt.now() - start_time).total_seconds())

        except Exception as e:
            import traceback
            return AgentResult(success=False, error=f"{e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════
# Bypass 辅助函数
# ═══════════════════════════════════════════════════════════

def _build_policies(ctx: dict, env_name: str) -> list:
    """生成 constraint policies — 优先读 YAML 约束文件"""
    # 如果 ctx 中已有 policies，直接复用
    existing = ctx.get("policies", {}).get("policies", [])
    if existing:
        return existing

    # 尝试从 YAML 约束文件读取
    constraint_yamls = [
        Path(f"src/tools/uvm/tool_uvm/{env_name.upper()}_constraint.yaml"),
        Path(f"src/tools/uvm/tool_uvm/ALU_constraint.yaml"),
        Path(f"src/tools/uvm/tool_uvm/{env_name}_constraint.yaml"),
    ]
    for yf in constraint_yamls:
        if yf.exists():
            try:
                data = yaml.safe_load(yf.read_text(encoding="utf-8"))
                # Policies may be at top level or nested under 'constraint'
                policies = data.get("policies", []) or data.get("constraint", {}).get("policies", [])
                if policies:
                    return [{"name": p["name"], "description": p.get("description", ""),
                            "priority": p.get("priority", 1),
                            "applies_to": p.get("applies_to", [])} for p in policies]
            except Exception:
                pass

    # 兜底：根据 env_name 语义生成
    is_alu = "alu" in env_name.lower()
    if is_alu:
        return [
            {"name": "precision_consistency", "description": "精度一致性", "priority": 1, "applies_to": ["cfg","input"]},
            {"name": "data_dependency", "description": "数据依赖策略", "priority": 2, "applies_to": ["input","output"]},
            {"name": "boundary_overflow", "description": "边界溢出", "priority": 3, "applies_to": ["input"]},
            {"name": "compute_mode", "description": "计算模式策略", "priority": 4, "applies_to": ["cfg","input","output"]},
            {"name": "concurrent_access", "description": "并发访问", "priority": 5, "applies_to": ["input","output"]},
        ]
    return [
        {"name": "basic_stimulus", "description": "基础激励", "priority": 1, "applies_to": ["cfg","input"]},
        {"name": "error_injection", "description": "错误注入", "priority": 2, "applies_to": ["input","output"]},
        {"name": "boundary_test", "description": "边界测试", "priority": 3, "applies_to": ["input"]},
        {"name": "random_stress", "description": "随机压力", "priority": 4, "applies_to": ["input","output"]},
    ]


def _debug_each_case(output_dir, gen_summary, env_name, env_output_dir, ctx) -> dict:
    """逐 Case 编译+仿真+分类，返回每个 case 的调试结果"""
    import subprocess, time as _time, os as _os
    results = {}
    tests = gen_summary.get("tests", [])
    if not tests:
        return results

    QUESTA = "f:/questasim64_2024.1/win64"
    vlog = _os.path.join(QUESTA, "vlog.exe")
    vsim = _os.path.join(QUESTA, "vsim.exe")
    env_dir = Path(env_output_dir) if env_output_dir else Path(output_dir)

    # Build filelist for env TB — try multiple locations
    candidates = [
        env_dir / "filelist.f",
        Path(output_dir) / "filelist.f",
        Path("generated/alu/filelist.f"),
        Path("output/filelist.f"),
    ]
    fl_path = None
    for c in candidates:
        if c.exists(): fl_path = c; break
    if not fl_path:
        for name in gen_summary.get("tests", []):
            results[name.get("test_name", name.get("id","?"))] = {"status":"SKIP","issue":"NO_FILELIST"}
        return results

    wd = (env_dir / "build" / "case_debug").resolve()
    wd.parent.mkdir(parents=True, exist_ok=True)
    wd_str = str(wd).replace("\\", "/")
    fl_str = str(fl_path.resolve()).replace("\\", "/")
    sim_dir = str(env_dir.resolve()).replace("\\", "/")

    # Compile once
    _os.makedirs(str(wd), exist_ok=True)
    subprocess.run([_os.path.join(QUESTA, "vlib.exe"), wd_str], capture_output=True, text=True, timeout=30)
    r = subprocess.run([vlog, "-mfcu", "-work", wd_str, "-sv", "+acc",
        "+incdir+f:/questasim64_2024.1/verilog_src/uvm-1.2/src",
        "-timescale=1ns/1ps",
        "f:/questasim64_2024.1/verilog_src/uvm-1.2/src/uvm_pkg.sv",
        "-f", fl_str],
        capture_output=True, text=True, timeout=120)
    compile_ok = r.returncode == 0
    if not compile_ok:
        for t in tests:
            name = t.get("test_name", t.get("id", "test"))
            results[name] = {"status": "COMPILE_FAIL", "issue": "ENV", "log": r.stdout[-500:]}
            import sys; sys.stdout.write(f"  [ENV ] {name} — compile FAIL → verify_architect\n"); sys.stdout.flush()
        return results

    # Run each test case
    for i, t in enumerate(tests):
        name = t.get("test_name", t.get("id", f"test_{i}"))
        top = f"{env_name}_bench_tb_top"
        log_file = env_dir / "sim" / f"case_{name}.log"

        _t0 = _time.time()
        r2 = subprocess.run([
            vsim, "-c", "-sv_lib", "f:/questasim64_2024.1/uvm-1.2/win64/uvm_dpi",
            "-onfinish", "stop",
            "-do", f"run 100us; quit -f",
            "-work", wd_str,
            "-l", str(log_file).replace("\\", "/"),
            top, "+UVM_TESTNAME=" + name,
        ], capture_output=True, text=True, timeout=120, cwd=str(env_dir.resolve()))
        _t1 = _time.time() - _t0

        log_text = r2.stdout
        if log_file.exists():
            try: log_text = log_file.read_text(encoding="utf-8", errors="replace")
            except: pass

        # Classify
        classification = _classify_case_result(log_text, r2.returncode)
        results[name] = classification
        icon = {"PASS":"[PASS]","ENV":"[ENV ]","RTL":"[RTL ]","MODEL":"[MODL]","UNKNOWN":"[????]"}.get(
            classification.get("issue","UNKNOWN"), "[????]")
        import sys; sys.stdout.write(
            f"  {icon} {name} ({_t1:.1f}s) env={classification.get('env_score',0)} "
            f"rtl={classification.get('rtl_score',0)} model={classification.get('model_score',0)}"
            f" → {classification.get('suggestion','')}\n"); sys.stdout.flush()

    return results


def _classify_case_result(log_text: str, returncode: int) -> dict:
    """Classify simulation result: PASS / ENV / RTL / MODEL"""
    if returncode == 0 and "UVM_ERROR" not in log_text and "UVM_FATAL" not in log_text:
        return {"status": "PASS", "issue": "", "env_score": 0, "rtl_score": 0, "model_score": 0}

    # Score each category
    import re as _re
    env_pats = [r"virtual interface", r"config_db", r"UVM_FATAL.*CFG", r"UVM_FATAL.*VIF",
                r"Module.*not defined", r"could not find package"]
    rtl_pats = [r"X/Z detected", r"scoreboard.*mismatch", r"mismatch.*expected",
                r"flags.*mismatch", r"result.*mismatch"]
    model_pats = [r"predictor.*mismatch", r"expected.*!=.*actual", r"golden.*mismatch"]

    env_score = sum(1 for p in env_pats for l in [log_text] if _re.search(p, l, _re.IGNORECASE))
    rtl_score = sum(1 for p in rtl_pats for l in [log_text] if _re.search(p, l, _re.IGNORECASE))
    model_score = sum(1 for p in model_pats for l in [log_text] if _re.search(p, l, _re.IGNORECASE))

    total_errors = len([l for l in log_text.split("\n") if "UVM_ERROR" in l or "UVM_FATAL" in l])

    # Determine primary issue
    scores = {"ENV": env_score, "RTL": rtl_score, "MODEL": model_score}
    primary = max(scores, key=scores.get) if any(scores.values()) else "UNKNOWN"

    return {"status": "FAIL", "issue": primary, "total_errors": total_errors,
            "env_score": env_score, "rtl_score": rtl_score, "model_score": model_score,
            "suggestion": {"ENV": "Re-run verify_architect", "RTL": "Re-run design_architect",
                           "MODEL": "Re-run model_agent", "UNKNOWN": "Manual check"}[primary]}


def _build_simargs(gen_summary: dict, env_output_dir: str, env_name: str) -> dict:
    """为每个测试生成 simargs（plusargs + run.sh 参数）"""
    simargs = {
        "env_output_dir": env_output_dir,
        "env_name": env_name,
        "top_module": f"{env_name}_bench_tb_top",
        "defaults": {
            "+UVM_VERBOSITY": "UVM_MEDIUM",
            "+UVM_TIMEOUT": "1000000000",
        },
        "per_test": {},
    }
    for t in gen_summary.get("tests", []):
        test_name = t.get("test_name", t.get("id", "test"))
        simargs["per_test"][test_name] = {
            "plusargs": [
                f"+UVM_TESTNAME={test_name}",
                "+UVM_VERBOSITY=UVM_MEDIUM",
            ],
            "seed": t.get("seed", "random"),
            "timeout": f"{t.get('timeout', 600)}s",
        }
    return simargs
