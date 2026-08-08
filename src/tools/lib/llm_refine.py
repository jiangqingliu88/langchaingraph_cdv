"""
LLM 驱动修复 —— 编译错误 + 仿真失败的诊断和 LLM 修复

用法:
    from src.tools.lib.llm_refine import call_llm, llm_refine_sim_timing
"""
import re
from pathlib import Path
import structlog

from src.tools.lib.filelist import build_loopback_filelist
from src.tools.lib.loopback import run_agent_loopback, _extract_method_body
from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner

logger = structlog.get_logger()


def call_llm(prompt: str, code: str, errors: str) -> str:
    """通过 LLMFactory 调用 LLM 修复代码。"""
    try:
        from src.core.llm_factory import LLMFactory
        llm = LLMFactory.create_for_task("code_generation")
        user_msg = f"CODE:\n{code[:3000]}\n\nERRORS:\n{errors[:1000]}\n\nOutput ONLY the fixed complete code, no explanation."
        resp = llm.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ])
        content = resp.content if hasattr(resp, 'content') else str(resp)
        if not content:
            return ""
        if "```" in content:
            block = content.split("```")[1]
            if block.startswith("systemverilog") or block.startswith("sv"):
                block = block.split("\n", 1)[1] if "\n" in block else block
            return block.strip()
        return content.strip()
    except Exception as e:
        logger.warning(f"LLM refine failed: {e}")
    return ""


def diagnose_compile_error(compile_log: str, agent_name: str) -> str:
    """从编译日志提取错误分类诊断。"""
    lines = compile_log.split("\n")
    errors = [l for l in lines if "** Error" in l]
    undeclared = [l for l in errors if "not declared" in l or "undeclared" in l.lower()]
    no_field = [l for l in errors if "could not find field" in l.lower() or "no field" in l.lower()]
    other = [l for l in errors if l not in undeclared and l not in no_field]
    parts = []
    if undeclared:
        parts.append(f"Undeclared identifiers:\n" + "\n".join(undeclared[:3]))
    if no_field:
        parts.append(f"Field access errors:\n" + "\n".join(no_field[:3]))
    if other:
        parts.append(f"Other errors:\n" + "\n".join(other[:3]))
    if not parts:
        parts.append("Unknown compile errors — check log for details.")
    return "\n".join(parts)


def build_compile_fix_prompt(name: str, compile_log: str, files: dict) -> str:
    """构建编译修复 LLM prompt。"""
    return f"""Fix ONLY the compile errors in the UVM agent "{name}" loopback testbench.
DO NOT rewrite working code. DO NOT change UVM framework structure.

COMPILE ERRORS:
{compile_log}

CURRENT FILES:
===FILE:driver===
{files.get('driver', '(missing)')[:2500]}

===FILE:monitor===
{files.get('monitor', '(missing)')[:1500]}

===FILE:test===
{files.get('test', '(missing)')[:1500]}

RULES:
1. Fix ONLY compile errors - do NOT change any other code.
2. Output ONLY fixed files in this format:
===FILE:driver===
<fixed driver.sv>
===FILE:monitor===
<fixed monitor.sv>
===FILE:test===
<fixed test.sv>
No explanations. Only code."""


def build_sim_fix_prompt(name: str, issue_type: str, diagnosis: str,
                          sim_log: str, files: dict) -> str:
    """构建仿真修复 LLM prompt。"""
    driver_excerpt = _extract_method_body(files.get("driver", ""), "drive_transaction")
    monitor_excerpt = _extract_method_body(files.get("monitor", ""), "sample_transaction")
    if not driver_excerpt:
        driver_excerpt = files.get("driver", "(missing)")[:2000]
    if not monitor_excerpt:
        monitor_excerpt = files.get("monitor", "(missing)")[:2000]

    fix_instructions = {
        "no_drive": """FIX TARGET: Driver not sending transactions.
1. Check test uses <name>_random_seq (NOT base_seq).
2. Check run_phase calls get_and_drive().
3. Check get_and_drive() declares <name>_seq_item req.
4. Check sequence body() creates and sends items.
5. Check test raises phase.raise_objection before seq.start().""",
        "no_match": """FIX TARGET: Monitor not matching (matched=0, driven>0).
1. QUALIFIER GATE: monitor's run_phase gate on qualifier signal BEFORE creating item.
2. EXP COPY: driver copies ALL transaction_vars fields to exp.
3. LOOPBACK TB: ALL ports connected, input wires tied to '0 or looped back.
4. MONITOR DELAY: add #1 after @(vif.cb).
5. DRIVER DE-ASSERT: de-assert strobe ports one cycle later.""",
        "mismatch": """FIX TARGET: Partial mismatch (0 < matched < driven).
1. TIMING: monitor samples at #1 after @(vif.cb).
2. QUALIFIER CONSTRAINTS: constrain qualifier to always be 1 during transactions.
3. FIELD COMPARE: non-driven input ports should NOT be in transaction_vars.
4. EXP COPY: ensure ALL compared fields copied from req to exp.
5. LOOPBACK WIRING: paired signals looped back correctly.""",
        "other": """FIX TARGET: Simulation errors or unexpected behavior.
1. Check sim log for UVM_ERROR/UVM_FATAL.
2. Common issues: null handle, randomization failure, config_db miss.
3. Clocking block: drive with vif.cb.<port> <= value; sample from vif.<port> after #1.""",
    }
    fix_text = fix_instructions.get(issue_type, fix_instructions["other"])

    return f"""You are debugging a UVM agent loopback test for agent "{name}".

ISSUE: {issue_type}
DIAGNOSIS: {diagnosis}

{fix_text}

SIM LOG (first 1500 chars):
{sim_log[:1500]}

KEY CODE EXCERPTS:
--- driver drive_transaction ---
{driver_excerpt[:2000]}

--- monitor sample_transaction ---
{monitor_excerpt[:2000]}

--- loopback test ---
{files.get('test', '(missing)')[:1500]}

--- loopback env ---
{files.get('env', '(missing)')[:1500]}

RULES:
1. Fix ONLY the specific issue described above.
2. Output ONLY changed files:
===FILE:driver===
<complete fixed driver.sv>
===FILE:monitor===
<complete fixed monitor.sv>
===FILE:test===
<complete fixed test.sv>
No markdown, no explanations — only code."""


def apply_llm_fixes(llm_output: str, files_to_fix: dict) -> int:
    """解析 LLM 输出中的 ===FILE:xxx=== 标记并写入文件。"""
    fixed = 0
    pattern = r'===FILE:(\w+)===\s*\n(.*?)(?=\n===FILE:|\Z)'
    matches = re.findall(pattern, llm_output, re.DOTALL)
    for tag, code in matches:
        tag = tag.strip()
        code = code.strip()
        if tag in files_to_fix and len(code) > 50:
            fpath = files_to_fix[tag]
            fpath.write_text(code, encoding="utf-8")
            logger.info(f"[LLM-fix] wrote {fpath.name} ({len(code)} bytes)")
            fixed += 1
        else:
            logger.warning(f"[LLM-fix] unknown/short tag: {tag} ({len(code)} bytes)")
    return fixed


def llm_refine_compile_errors(output_dir: Path, agents: list) -> int:
    """LLM 读取生成文件 + 编译错误，修复代码。"""
    fixed_count = 0
    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        agent_dir = output_dir / "agents" / name
        if not agent_dir.exists():
            continue

        fl = build_loopback_filelist(output_dir, name)
        runner = RegressionRunner(
            env_output_dir=str(output_dir), filelist=str(fl.resolve()),
            top_module=f"{name}_loopback_tb", coverage=False)
        compile_result = runner.compile()
        if compile_result["status"] == "PASS":
            continue

        errors = compile_result.get("stderr", "")
        error_files = set()
        for line in errors.split("\n"):
            if "** Error" in line:
                m = re.search(r'([\w_]+\.sv)\s*\)', line)
                if m:
                    error_files.add(m.group(1))

        for fname in error_files:
            fpath = agent_dir / fname
            if not fpath.exists():
                fpath = agent_dir / "loopback" / fname
            if not fpath.exists():
                continue
            code = fpath.read_text(encoding="utf-8", errors="replace")
            prompt = f"Fix compile errors in this UVM SystemVerilog file. Errors:\n{errors[:2000]}"
            refined = call_llm(prompt, code, errors)
            if refined and len(refined) > 50:
                fpath.write_text(refined, encoding="utf-8")
                fixed_count += 1
                fl = build_loopback_filelist(output_dir, name)
                runner = RegressionRunner(
                    env_output_dir=str(output_dir), filelist=str(fl.resolve()),
                    top_module=f"{name}_loopback_tb", coverage=False)
                r2 = runner.compile()
                if r2["status"] == "PASS":
                    break
    return fixed_count


def llm_refine_sim_timing(output_dir: Path, agents: list, env_name: str) -> dict:
    """LLM 驱动的迭代闭环修复 —— 诊断后修复，不重写整个文件。"""
    result = {"fixed": 0, "details": []}
    MAX_LLM_RETRIES = 2

    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        logger.info(f"[LLM-loopback] checking {name}...")
        prev_score = -1

        for llm_attempt in range(MAX_LLM_RETRIES):
            r = run_agent_loopback(output_dir, name)
            if r.get("compile") == "PASS" and r.get("passed", False):
                result["details"].append(f"{name}: PASS (attempt {llm_attempt})")
                break

            driven = r.get("driven", 0)
            matched = r.get("matched", 0)
            mismatched = r.get("mismatched", 0)
            sim_errors = r.get("errors", 0)
            compile_ok = r.get("compile") == "PASS"

            if not compile_ok:
                issue_type = "compile"
                diagnosis = diagnose_compile_error(r.get("compile_log", ""), name)
            elif driven == 0:
                issue_type = "no_drive"
                diagnosis = f"Driver sent 0 transactions. seq uses random_seq? seq.start() called? get_and_drive() correct?"
            elif matched == 0 and driven > 0:
                issue_type = "no_match"
                diagnosis = f"Driver sent {driven} tx but 0 matched. Monitor gating? exp copy? TLM connect?"
            elif mismatched > 0:
                issue_type = "mismatch"
                diagnosis = f"Drive={driven} matched={matched} mismatched={mismatched}. Timing? Fields? Wiring?"
            else:
                issue_type = "other"
                diagnosis = f"driven={driven} matched={matched} errors={sim_errors}"

            if r.get("score", 0) <= prev_score and llm_attempt > 0:
                result["details"].append(f"{name}: stuck at score={r.get('score', 0)}")
                break
            prev_score = r.get("score", 0)

            agent_dir = output_dir / "agents" / name
            files_to_fix = {
                "driver": agent_dir / f"{name}_driver.sv",
                "monitor": agent_dir / f"{name}_monitor.sv",
                "test": agent_dir / "loopback" / f"{name}_loopback_test.sv",
                "scoreboard": agent_dir / "loopback" / f"{name}_loopback_scb.sv",
                "env": agent_dir / "loopback" / f"{name}_loopback_env.sv",
            }
            file_contents = {}
            for tag, fpath in files_to_fix.items():
                file_contents[tag] = fpath.read_text(encoding="utf-8", errors="replace") if fpath.exists() else "(file not found)"

            if issue_type == "compile":
                prompt = build_compile_fix_prompt(name, r.get("compile_log", "")[:1500], file_contents)
            else:
                prompt = build_sim_fix_prompt(name, issue_type, diagnosis, str(r.get("sim_log", ""))[:1500], file_contents)

            refined = call_llm(prompt, "", str(r.get("sim_log", ""))[:500])
            if not refined or len(refined) < 50:
                result["details"].append(f"{name}: LLM fix failed (empty response)")
                break

            fixed_count = apply_llm_fixes(refined, files_to_fix)
            if fixed_count == 0:
                result["details"].append(f"{name}: LLM parse failed")
                break

            result["fixed"] += fixed_count
            logger.info(f"[LLM-loopback] {name}: LLM fixed {fixed_count} files, retrying...")
        else:
            result["details"].append(f"{name}: FAIL after {MAX_LLM_RETRIES} LLM attempts")

    return result
