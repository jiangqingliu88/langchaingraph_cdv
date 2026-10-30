"""
LLM 驱动修复 —— 编译错误 + 仿真失败的诊断和 LLM 修复

本模块只做**修复的编排**（找文件、判有效性、走闸门写回）；
真正调 LLM 的那一下在 `llm_call.call_llm` —— 全项目唯一的出口。

用法:
    from src.tools.common.lib.llm_call import CODE_SCHEMA, call_llm
    from src.tools.common.lib.llm_refine import llm_refine_sim_timing
"""
import re
from pathlib import Path
import structlog

from src.tools.common.lib.filelist import build_loopback_filelist
from src.tools.common.lib.llm_call import call_llm
from src.tools.common.lib.loopback import run_agent_loopback, _extract_method_body
from src.tools.execution.regression_tools.regression_framework.adapters.regression_runner import RegressionRunner

logger = structlog.get_logger()


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


# 写盘边界 —— **判据只有一处**（`generated_files`，L1）。
#
# 这里原来是**本模块私有的第二份实现**（`_GENERATED_BANNER` / `_CUSTOM_MARKER` /
# `_skeleton` / `gated_write` 各写一遍）。而"同一件事有两份实现"正是这个会话里
# 反复踩的那个病 —— 上一版只闸了本模块的一条写盘路径、漏了另一条，就是因为
# 闸门被认为"是这里的东西"而不是"全项目的东西"。现在判据归 L1，这里只是别名，
# 保证老调用点与既有测试的名字仍然可用。
from src.layers.l1_infrastructure.generated_files import (  # noqa: E402
    gated_write as _l1_gated_write,
    is_generated as _is_generated_file,
    REGION_MARKER as _CUSTOM_MARKER,
    skeleton as _skeleton,
)


def gated_write(fpath, code: str) -> bool:
    """本模块的写盘出口 —— **转调 L1 的唯一实现**（别再在这里写第二份判据）。"""
    return _l1_gated_write(fpath, code, logger=logger)


def apply_llm_fixes(llm_output: str, files_to_fix: dict) -> int:
    """解析 LLM 输出中的 `===FILE:xxx===` 标记并写入文件。

    ## 为什么要拒绝"整份重写生成物"（实测踩过，代价很大）

    这个函数原来是无条件 `fpath.write_text(code)`。而 loopback 的
    `<ag>_loopback_scb.sv` **是 `gen_uvm` 从模板生成的**，LLM 每次拿到 500 字
    sim log 就把**整份**重写一遍 —— 于是同一个模板，三轮运行产出三份**各不
    相同**的文件（实测行数 131 / 182 / 156，且一份都不含模板自带的
    `SCB_LOOP_PASS` 标记）。后果按运气分三种：

      · 恰好能编能过        → loopback 7/7（假象：以为好了）
      · 写出非法覆盖        → `do_compare` 签名不符 → 编译塌 → `[INVTST]`
      · 能编但比较逻辑错     → 满屏 `loopback mismatch`

    loopback 是分级回归的**第一道门**，它挂了后面 p0–p3 / 覆盖率 / 签核**全不跑**。
    表现就是"每轮死在不同地方、怎么都跑不通" —— **跑通与否由那一轮 LLM 写了什么
    决定，而不是由代码决定**。

    ## 判据

    目标是生成物时，**骨架（`pragma custom` 之外）必须逐字节不变**：

      · 只动 `pragma custom` 区域 → 放行（那是它被允许改的地方）
      · 骨架对不上（= 整份重写）→ **拒绝，保留原文**，并把这次拒绝记进日志与计数

    拒绝不是"静默跳过"：调用方拿 `refused` 单独报，别和"LLM 没输出"混为一谈。
    """
    fixed = 0
    refused = 0
    pattern = r'===FILE:(\w+)===\s*\n(.*?)(?=\n===FILE:|\Z)'
    matches = re.findall(pattern, llm_output, re.DOTALL)
    for tag, code in matches:
        tag = tag.strip()
        code = code.strip()
        if tag not in files_to_fix or len(code) <= 50:
            logger.warning(f"[LLM-fix] unknown/short tag: {tag} ({len(code)} bytes)")
            continue
        fpath = files_to_fix[tag]
        if gated_write(fpath, code):
            fixed += 1
        else:
            refused += 1
    apply_llm_fixes.refused = refused          # noqa: SLF001 调用方取用
    return fixed


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

            refined = call_llm(prompt, "", str(r.get("sim_log", ""))[:500],
                               output_schema=CODE_SCHEMA,
                               prompt_version="debug-sim-fix-v1")
            if not refined or len(refined) < 50:
                result["details"].append(f"{name}: LLM fix failed (empty response)")
                break

            fixed_count = apply_llm_fixes(refined, files_to_fix)
            refused = getattr(apply_llm_fixes, "refused", 0)
            if refused:
                # **拒绝不是"没解析出来"** —— 是 LLM 想去改生成物的骨架，被挡了。
                # 混成一句 "parse failed" 会让人往 prompt 上找原因（实测会白查一轮）。
                result["details"].append(
                    f"{name}: 拒绝 LLM 整份重写生成物 {refused} 个文件"
                    f"（只允许改 pragma custom 区域）")
                logger.warning(f"[LLM-loopback] {name}: refused {refused} wholesale "
                               f"rewrite(s) of generated files")
            if fixed_count == 0:
                result["details"].append(
                    f"{name}: LLM parse failed" if not refused else
                    f"{name}: 没有可应用的修改（全部被生成物闸门拦下）")
                break

            result["fixed"] += fixed_count
            logger.info(f"[LLM-loopback] {name}: LLM fixed {fixed_count} files, retrying...")
        else:
            result["details"].append(f"{name}: FAIL after {MAX_LLM_RETRIES} LLM attempts")

    return result
