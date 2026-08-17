"""
UVM 验证工具集 —— 供 UvmAgent Agent 调用

   generate_uvm_from_spec  — spec 文本 → UVM 环境代码 + 质量检查
   check_static            — 静态文件存在性检查
   check_compile           — QuestaSim 编译检查
   check_loopback          — 闭环编译+仿真检查
   check_health            — 环境顶层健康检查
   read_file               — 读取生成的 SV 文件
   write_file              — 写入/覆盖 SV 文件

手动测试:
   >>> from src.tools.uvm_tools.tools import generate_uvm_from_spec
   >>> result = generate_uvm_from_spec.func("module alu ...")
   >>> # 或设置 context 后调用
   >>> from src.tools.uvm_tools.tools import _uvm_ctx
   >>> _uvm_ctx.set(output_dir=Path("output"), agents=[], env_name="dut_env")
"""
import json, re, os, subprocess, time, shutil as _shutil, threading
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from langchain.tools import tool
import structlog

from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
# UvmToolContext — 线程安全运行时上下文
# ═══════════════════════════════════════════════════════════

class UvmToolContext:
    """UVM 工具共享上下文 —— 替代原 _LLM_CTX 全局 dict。

    UvmAgent.execute_task() 在每次 LLM 调用前设置上下文。
    工具函数通过 _uvm_ctx 单例读写上下文。
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._output_dir: Optional[str] = None
        self._agents: List = []
        self._env_name: str = "dut"

    def set(self, *, output_dir, agents, env_name):
        """每轮 LLM 调用前由 agent 设置。"""
        with self._lock:
            self._output_dir = str(output_dir)
            self._agents = list(agents) if agents else []
            self._env_name = env_name or "dut"

    def update_agents(self, agents: List):
        """generate_uvm_from_spec 完成后更新 agent 列表。"""
        with self._lock:
            self._agents = list(agents)

    def update_env_name(self, env_name: str):
        """generate_uvm_from_spec 完成后更新 env 名称。"""
        with self._lock:
            self._env_name = env_name

    @property
    def output_dir(self) -> str:
        return self._output_dir or str(Path("output").resolve())

    @property
    def agents(self) -> List:
        return self._agents

    @property
    def env_name(self) -> str:
        return self._env_name or "dut"

    def reset(self):
        """重置上下文（用于测试隔离）。"""
        with self._lock:
            self._output_dir = None
            self._agents = []
            self._env_name = "dut"


_uvm_ctx = UvmToolContext()

_registry_initialized = False
_registry_instance = None


def ensure_uvm_tool_registry():
    """返回 testbench_orchestrator 所有 Tool 的 ToolRegistry（含 JSON Schema）。

    这是 testbench_orchestrator 工具 schema 的单一事实来源。
    供 agent_tools.py 和 UvmAgent._setup() 使用。
    """
    global _registry_initialized, _registry_instance
    if _registry_initialized:
        return _registry_instance

    from src.layers.l2_orchestration.communication.tool_system import Tool, ToolRegistry

    registry = ToolRegistry()
    registry.register_many([
        Tool("generate_uvm_from_spec",
             description="从规格文本生成 UVM 验证环境代码。输入 spec_text (Markdown) 返回文件列表 JSON。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "spec_text": {"type": "string", "description": "Markdown 规格文本"},
                 }, "required": ["spec_text"],
             },
             risk_level="write"),

        Tool("check_static",
             description="静态检查: 验证所有预期的 UVM 文件是否存在。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "env_dir": {"type": "string", "default": "", "description": "输出目录路径"},
                 },
             },
             risk_level="safe"),

        Tool("check_compile",
             description="编译检查: 使用 QuestaSim vlog 编译 UVM 环境。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "env_dir": {"type": "string", "default": "", "description": "输出目录路径"},
                 },
             },
             risk_level="safe"),

        Tool("check_loopback",
             description="闭环检查: 编译 + 仿真每个 Agent 的 loopback TB。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "env_dir": {"type": "string", "default": "", "description": "输出目录路径"},
                 },
             },
             risk_level="safe"),

        Tool("check_health",
             description="健康检查: 编译 + 仿真环境顶层 100us。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "env_dir": {"type": "string", "default": "", "description": "输出目录路径"},
                 },
             },
             risk_level="safe"),

        Tool("read_file",
             description="读取生成的 SystemVerilog 文件内容用于检查和修复。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "path": {"type": "string", "description": "文件路径 (相对或绝对)"},
                 }, "required": ["path"],
             },
             risk_level="safe"),

        Tool("write_file",
             description="写入/覆盖 SystemVerilog 文件。输入格式: 'filepath::content'。",
             input_schema={
                 "type": "object",
                 "properties": {
                     "path_content": {"type": "string",
                                      "description": "格式: 'filepath::content', 用 :: 分隔路径和内容"},
                 }, "required": ["path_content"],
             },
             risk_level="write"),
    ])

    _registry_instance = registry
    _registry_initialized = True
    return registry


# ═══════════════════════════════════════════════════════════
# LLM Refinement — template foundation + LLM polish
# ═══════════════════════════════════════════════════════════

def _llm_generate_custom_logic(agent_name: str, ports: list, is_active: bool = True) -> dict:
    """Generate protocol-specific drive/sample logic from interface port spec.

    Returns dict with keys: custom_drive_logic, custom_sample_logic
    Each value is a SystemVerilog code snippet inserted into the driver/monitor template.
    """
    if not ports:
        return {"custom_drive_logic": "", "custom_sample_logic": ""}

    # Build port description
    port_desc_lines = []
    for p in ports:
        d = p.get("dir", "?")
        n = p.get("name", "?")
        w = p.get("width", 1)
        desc = p.get("desc", "")
        w_str = f"[{w-1}:0] " if isinstance(w, int) and w > 1 else ""
        port_desc_lines.append(f"  {d:6s} {w_str}{n}" + (f"  // {desc}" if desc else ""))

    port_desc = "\n".join(port_desc_lines)
    output_ports = [p for p in ports if p.get("dir") == "output"]
    input_ports = [p for p in ports if p.get("dir") == "input"]
    output_names = [p["name"] for p in output_ports]
    input_names = [p["name"] for p in input_ports]
    has_valid = any("valid" in p.get("name", "").lower() for p in output_ports)
    has_ready = any("ready" in p.get("name", "").lower() for p in input_ports)

    # ── Determine protocol type for targeted guidance ──
    has_apb = any(n in output_names for n in ["psel", "penable", "pwrite", "pwdata"])
    has_strobe = any("strobe" in n.lower() or "wen" in n.lower() or "ren" in n.lower()
                     for n in output_names)

    # ── Build protocol-specific guidance ──
    if has_apb:
        protocol_hint = """
APB PROTOCOL (setup+access phases) — LOOPBACK MODE (no DUT, no slave response):
  Driver: 1) setup: drive paddr, pwrite, pwdata, psel=1, penable=0; @(vif.cb)
          2) access: penable=1; @(vif.cb)
          3) DO NOT wait for pready (floating in loopback). De-assert immediately.
          4) de-assert: psel=0, penable=0; @(vif.cb)
  Monitor: @(vif.cb); if (vif.psel && vif.penable) sample ALL APB signals
  CRITICAL for loopback: DO NOT include pready in the monitor gate (pready is floating).
  Gate on (psel && penable) only. Sample ALL ports including prdata and pslverr."""
    elif has_valid and has_ready:
        protocol_hint = """
VALID/READY HANDSHAKE:
  Driver: @(vif.cb); drive data+valid=1; @(vif.cb); wait while(!vif.ready); de-assert valid
  Monitor: @(vif.cb); if (vif.ready) sample fields (valid may still be high from previous)
  The template already handles expected_port.write(exp). Just write the signal-wiggling.
  Monitor MUST gate on ((vif.valid && vif.ready) or at minimum vif.ready) to avoid
  sampling the same transaction multiple times."""
    elif has_strobe:
        protocol_hint = """
STROBE-BASED PROTOCOL:
  Driver: @(vif.cb); drive data+strobe=1; @(vif.cb); de-assert strobe
  Monitor: @(vif.cb); if (vif.strobe) sample ALL fields
  Monitor MUST gate on strobe to avoid sampling idle cycles."""
    else:
        protocol_hint = """
GENERAL BUS PROTOCOL (no explicit valid/strobe — use a 1-cycle qualification):
  Driver: @(vif.cb); drive ALL output ports with req values
  Monitor: Create a "valid" qualifier from the output port that toggles (e.g. data change
           or a dedicated control signal). If no qualifier exists, sample every cycle
           but the expected_port.write timing will handle matching.
  IMPORTANT: The driver template copies all output ports into `exp` BEFORE your code runs.
  Your code just needs to wiggle the signals via vif.cb.<port> <= req.<port>."""

    prompt = f"""You are a UVM verification IP (VIP) timing expert. Write the protocol timing
snippets for a UVM agent used in LOOPBACK SELF-TEST (no DUT, driver→monitor closed loop).

AGENT: {agent_name}
TYPE: {"ACTIVE — drives signals, writes expected" if is_active else "PASSIVE — only monitors"}
OUTPUT PORTS (TB drives these): {output_names}
INPUT PORTS  (TB reads these):  {input_names}

INTERFACE PORTS:
{port_desc}

{protocol_hint}

━━━ CONTEXT: WHAT THE TEMPLATE ALREADY DOES ━━━
The Jinja2 template generates a complete UVM driver and monitor class. Your snippet
goes INSIDE these methods. DO NOT repeat what the template does.

DRIVER template (drive_transaction task):
  // 1. Template copies ALL output ports into exp item:
  //    exp.<port> = req.<port>;  (for every output port — DONE already)
  // 2. YOUR drive logic goes here (===DRIVE===)
  // 3. Template then writes expected: expected_port.write(exp);
  // 4. Template then does @(vif.cb) and de-asserts valid/ready if named exactly 'valid'/'ready'

MONITOR template (sample_transaction function):
  // YOUR sample logic goes here (===SAMPLE===)
  // Template then writes collected item to item_collected_port

━━━ CRITICAL RULES ━━━
0. VARIABLE NAMES (exact — must match the generated code):
   DRIVER: The task signature is `drive_transaction(APB_agent_seq_item req)`.
           Drive output ports with: `vif.cb.<port> <= req.<port>`
   MONITOR: The function signature is `sample_transaction(APB_agent_seq_item item)`.
            Sample all signals into: `item.<port> = vif.<port>`
   NEVER use `trans`, `tx`, `t`, `it`, or any other variable name. Only `req` (driver) and `item` (monitor).

1. Output ONLY SystemVerilog code — NO markdown, NO ```sv fences, NO explanation.
2. DRIVE snippet: use `vif.cb.<port> <= req.<port>` to drive output ports synchronously.
   DO NOT drive hardcoded constants (like `<= 1;`). Always use `req.<port>` from the transaction.
3. DRIVE snippet: for input ports that the agent reads (e.g. pready), use `vif.<port>` (no .cb).
4. SAMPLE snippet: sample ALL signals (input AND output direction) using `item.<port> = vif.<port>`.
   The monitor already does `@(vif.cb)` before calling sample_transaction.
5. SAMPLE snippet: MUST gate on a qualifier signal to skip idle cycles.
   Without gating, the monitor samples every clock cycle = mismatches with expected.
6. Keep each snippet under 10 lines. Just the timing, nothing else.

━━━ LOOPBACK TIMING (Driver→Monitor closed loop) ━━━
  Clock cycle N:   Driver drives signals via vif.cb (output skew → signals appear at N+1)
  Clock cycle N+1: Monitor @(vif.cb) captures, samples vif.<signal> (sees driven values)

  The template writes expected_port.write(exp) INSIDE drive_transaction at cycle N,
  BEFORE monitor samples at N+1. This ordering ensures expected arrives first.

OUTPUT EXACTLY IN THIS FORMAT (3 equals signs, no spaces around ===):
===DRIVE===
<your drive code here>
===SAMPLE===
<your sample code here>"""

    code = _call_llm(prompt, "", port_desc)
    result = {"custom_drive_logic": "", "custom_sample_logic": ""}

    if code:
        import re as _re2
        dm = _re2.search(r'===DRIVE===\s*\n(.*?)(?=\n===SAMPLE===|\Z)', code, _re2.DOTALL)
        sm = _re2.search(r'===SAMPLE===\s*\n(.*?)(?=\Z)', code, _re2.DOTALL)
        if dm:
            result["custom_drive_logic"] = dm.group(1).strip()
        if sm:
            result["custom_sample_logic"] = sm.group(1).strip()

    # ── Only use fallback if LLM responded but we couldn't parse sections ──
    # If LLM returned something useful (parsed at least one section), trust it.
    # If both empty AND LLM returned garbage, leave empty → template defaults used.
    has_llm_response = code and len(code.strip()) > 20
    has_parsed_something = bool(result["custom_drive_logic"] or result["custom_sample_logic"])
    if not has_parsed_something and not has_llm_response:
        return result  # no LLM response at all → template defaults
    if not has_parsed_something and has_llm_response:
        # LLM responded but format was wrong → use safe fallback
        result["custom_drive_logic"] = _generate_fallback_drive(output_names)
        result["custom_sample_logic"] = _generate_fallback_sample(output_names, input_names)

    return result


def _generate_fallback_drive(output_names: list) -> str:
    """Generate safe default drive snippet — protocol-aware, one-cycle drive + de-assert."""
    lines = ["@(vif.cb);"]
    # Drive all output ports
    for n in output_names:
        lines.append(f"vif.cb.{n} <= req.{n};")
    # One cycle hold
    lines.append("@(vif.cb);")
    # De-assert strobe-like signals
    for n in output_names:
        if any(k in n.lower() for k in ("valid", "strobe", "wen", "ren", "sel", "enable")):
            lines.append(f"vif.cb.{n} <= 1'b0;")
    return "\n".join(lines)


def _generate_fallback_sample(output_names: list, input_names: list) -> str:
    """Generate safe default sample snippet — gate on strobe/valid, sample all non-clk ports."""
    all_non_clk = [n for n in output_names + input_names
                   if n not in ("clk", "rst", "rst_n", "reset", "presetn")]
    # Find a qualifier signal for gating
    strobe_candidates = [n for n in output_names
                         if any(k in n.lower() for k in ["valid", "strobe", "wen", "ren", "sel", "enable"])]
    lines = []
    if strobe_candidates:
        gate = strobe_candidates[0]
        lines.append(f"if (vif.{gate}) begin")
        for n in all_non_clk:
            lines.append(f"  item.{n} = vif.{n};")
        lines.append("end")
    else:
        # No explicit qualifier — sample all, but rely on one-cycle strobe de-assert
        for n in all_non_clk:
            lines.append(f"item.{n} = vif.{n};")
    return "\n".join(lines)


def _inject_custom_logic_sv(sv_path: Path, drive_logic: str, sample_logic: str, file_type: str):
    """Inject LLM-generated custom logic into already-generated SV file via string replacement.

    Avoids Jinja2 re-rendering which corrupts when LLM code contains {{ }} or {% %} syntax.
    """
    if not sv_path.exists():
        return
    content = sv_path.read_text(encoding="utf-8", errors="replace")

    if file_type == "driver" and drive_logic:
        # Replace default drive section: from "// === Default: simple @(cb)" marker
        # through the @(vif.cb) drive block, stopping before "expected_port.write(exp)"
        default_marker = "// === Default: simple @(cb) drive all output ports ==="
        if default_marker in content:
            # Find the block between default_marker and expected_port.write
            before, rest = content.split(default_marker, 1)
            # The default block ends at "expected_port.write(exp);" or "// Write expected NOW"
            end_markers = ["expected_port.write(exp);", "// Write expected NOW"]
            after = rest
            for em in end_markers:
                if em in rest:
                    _, after = rest.split(em, 1)
                    after = em + after
                    break
            injected = "// === LLM-generated protocol timing ===\n" + drive_logic
            content = before + injected + "\n    \n    " + after
        else:
            # Maybe already injected? Replace existing LLM block
            llm_marker = "// === LLM-generated protocol timing ==="
            if llm_marker in content:
                before, rest = content.split(llm_marker, 1)
                # Find next blank line or expected_port.write
                end_markers = ["expected_port.write(exp);", "// Write expected NOW"]
                after = rest
                for em in end_markers:
                    if em in rest:
                        _, after = rest.split(em, 1)
                        after = em + after
                        break
                content = before + llm_marker + "\n" + drive_logic + "\n    \n    " + after

    elif file_type == "monitor" and sample_logic:
        # Replace default sample section
        default_marker = "// === Default: sample all ports from interface ==="
        if default_marker in content:
            before, rest = content.split(default_marker, 1)
            # Find the end of sample_transaction function
            end_marker = "endfunction"
            if end_marker in rest:
                # Find the endfunction that closes sample_transaction
                # (there might be multiple endfunctions)
                _, after = rest.split("endfunction", 1)
                after = "endfunction" + after
                injected = "// === LLM-generated protocol sampling ===\n" + sample_logic
                content = before + injected + "\n  " + after

    sv_path.write_text(content, encoding="utf-8")


def _call_llm(prompt: str, code: str, errors: str) -> str:
    """通过 LLMFactory 调用 LLM 修复代码。支持 DeepSeek / OpenAI / Anthropic / Custom。"""
    try:
        from src.layers.l2_orchestration.context.llm_factory import LLMFactory
        llm = LLMFactory.create_for_task("code_generation")
        user_msg = f"CODE:\n{code[:3000]}\n\nERRORS:\n{errors[:1000]}\n\nOutput ONLY the fixed complete code, no explanation."
        resp = llm.invoke([
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ])
        content = resp.content if hasattr(resp, 'content') else str(resp)
        if not content:
            return ""
        # Extract code block if wrapped
        if "```" in content:
            block = content.split("```")[1]
            if block.startswith("systemverilog") or block.startswith("sv"):
                block = block.split("\n", 1)[1] if "\n" in block else block
            return block.strip()
        return content.strip()
    except Exception as e:
        logger.warning(f"LLM refine failed: {e}")
    return ""


def _llm_refine_compile_errors(output_dir: Path, agents: list) -> int:
    """LLM reads generated files + compile errors, fixes code, rewrites files.

    编译通过 RegressionRunner，不再硬编码 vlog 路径。
    """
    fixed_count = 0

    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        agent_dir = output_dir / "agents" / name
        if not agent_dir.exists():
            continue

        logger.info(f"[LLM-refine] checking {name} agent...")
        fl = _build_loopback_filelist(output_dir, name)
        runner = RegressionRunner(
            env_output_dir=str(output_dir),
            filelist=str(fl.resolve()),
            top_module=f"{name}_loopback_tb",
            coverage=False,
        )
        compile_result = runner.compile()
        if compile_result["status"] == "PASS":
            continue  # already clean

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
            refined = _call_llm(prompt, code, errors)
            if refined and len(refined) > 50:
                fpath.write_text(refined, encoding="utf-8")
                logger.info(f"  LLM refined: {fname}")
                fixed_count += 1
                # Retry compile
                fl = _build_loopback_filelist(output_dir, name)
                runner = RegressionRunner(
                    env_output_dir=str(output_dir),
                    filelist=str(fl.resolve()),
                    top_module=f"{name}_loopback_tb",
                    coverage=False,
                )
                r2 = runner.compile()
                if r2["status"] == "PASS":
                    logger.info(f"  LLM refined + compile PASS for {name}")
                    break

    return fixed_count


def _llm_refine_sim_timing(output_dir: Path, agents: list, env_name: str) -> dict:
    """LLM-driven iterative loopback fix —— 先诊断后修复，不重写整个文件"""
    result = {"fixed": 0, "details": []}
    MAX_LLM_RETRIES = 2  # 减少迭代次数，每轮更精准

    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        logger.info(f"[LLM-loopback] checking {name}...")

        prev_score = -1
        for llm_attempt in range(MAX_LLM_RETRIES):
            r = _run_agent_loopback(output_dir, name)

            if r.get("compile") == "PASS" and r.get("passed", False):
                result["details"].append(f"{name}: PASS (attempt {llm_attempt})")
                logger.info(f"[LLM-loopback] {name} PASS")
                break

            # ── 诊断失败类型 ──
            driven = r.get("driven", 0)
            matched = r.get("matched", 0)
            mismatched = r.get("mismatched", 0)
            sim_errors = r.get("errors", 0)
            compile_ok = r.get("compile") == "PASS"

            if not compile_ok:
                issue_type = "compile"
                diagnosis = _diagnose_compile_error(
                    r.get("compile_log", ""), name)
            elif driven == 0:
                issue_type = "no_drive"
                diagnosis = (
                    f"Driver sent 0 transactions. Either the sequence didn't start, "
                    f"or get_and_drive() isn't receiving items from the sequencer.\n"
                    f"→ Check: seq uses random_seq (not base_seq), "
                    f"seq.start() is called, run_phase calls get_and_drive(), "
                    f"get_and_drive() declares '{name}_seq_item req;'")
            elif matched == 0 and driven > 0:
                issue_type = "no_match"
                diagnosis = (
                    f"Driver sent {driven} transactions but 0 matched. "
                    f"Either the monitor isn't sampling, or expected/actual values don't match.\n"
                    f"→ Check: monitor gates on a qualifier signal (no idle sampling), "
                    f"sample_transaction reads vif.<signal> for all ports, "
                    f"expected_port.connect(scb_h.expected_export) in env connect_phase")
            elif mismatched > 0:
                issue_type = "mismatch"
                diagnosis = (
                    f"Drive={driven} matched={matched} mismatched={mismatched}. "
                    f"Data mismatch between expected and actual.\n"
                    f"→ Check: exp copy copies ALL output fields BEFORE driving, "
                    f"monitor samples the same cycle driver drives, "
                    f"monitor uses vif.<port> (not vif.cb.<port>) for output-direction ports")
            else:
                issue_type = "other"
                diagnosis = (
                    f"driven={driven} matched={matched} errors={sim_errors}. "
                    f"Check sim log for UVM_ERROR/UVM_FATAL details.")

            logger.info(f"[LLM-loopback] {name} {issue_type} (attempt {llm_attempt+1}/{MAX_LLM_RETRIES})")

            # Skip LLM if stuck (same score twice)
            if r.get("score", 0) <= prev_score and llm_attempt > 0:
                logger.warning(f"[LLM-loopback] {name}: score not improving ({prev_score}→{r.get('score',0)}), skipping LLM")
                result["details"].append(f"{name}: stuck at score={r.get('score',0)}")
                break
            prev_score = r.get("score", 0)

            # ── 收集相关文件（只取关键部分，不送整个文件） ──
            agent_dir = output_dir / "agents" / name
            files_to_fix = {
                "driver":      agent_dir / f"{name}_driver.sv",
                "monitor":     agent_dir / f"{name}_monitor.sv",
                "test":        agent_dir / "loopback" / f"{name}_loopback_test.sv",
                "scoreboard":  agent_dir / "loopback" / f"{name}_loopback_scb.sv",
                "env":         agent_dir / "loopback" / f"{name}_loopback_env.sv",
            }
            file_contents = {}
            for tag, fpath in files_to_fix.items():
                if fpath.exists():
                    file_contents[tag] = fpath.read_text(encoding="utf-8", errors="replace")
                else:
                    file_contents[tag] = "(file not found)"

            # ── 针对性 prompt：根据 issue_type 给不同的修复指令 ──
            if issue_type == "compile":
                compile_log = r.get("compile_log", "")[:1500]
                prompt = _build_compile_fix_prompt(name, compile_log, file_contents)
            else:
                sim_log = r.get("sim_log", "")[:1500]
                prompt = _build_sim_fix_prompt(name, issue_type, diagnosis, sim_log, file_contents)

            refined = _call_llm(prompt, "", str(r.get("sim_log", ""))[:500])

            if not refined or len(refined) < 50:
                logger.warning(f"[LLM-loopback] {name}: LLM returned empty/invalid response")
                result["details"].append(f"{name}: LLM fix failed (empty response)")
                break

            fixed_count = _apply_llm_fixes(refined, files_to_fix)
            if fixed_count == 0:
                logger.warning(f"[LLM-loopback] {name}: could not parse any fixes")
                result["details"].append(f"{name}: LLM parse failed")
                break

            result["fixed"] += fixed_count
            logger.info(f"[LLM-loopback] {name}: LLM fixed {fixed_count} files, retrying...")

        else:
            result["details"].append(f"{name}: FAIL after {MAX_LLM_RETRIES} LLM attempts")

    return result


def _diagnose_compile_error(compile_log: str, agent_name: str) -> str:
    """从编译日志中提取具体错误，给出针对性诊断"""
    import re
    lines = compile_log.split("\n")
    errors = [l for l in lines if "** Error" in l]
    # 归类
    undeclared = [l for l in errors if "not declared" in l or "undeclared" in l.lower()]
    no_field = [l for l in errors if "could not find field" in l.lower() or "no field" in l.lower()]
    other = [l for l in errors if l not in undeclared and l not in no_field]
    parts = []
    if undeclared:
        parts.append(f"Undeclared identifiers (missing import/include?):\n" + "\n".join(undeclared[:3]))
    if no_field:
        parts.append(f"Field access errors (field missing in transaction?):\n" + "\n".join(no_field[:3]))
    if other:
        parts.append(f"Other errors:\n" + "\n".join(other[:3]))
    if not parts:
        parts.append("Unknown compile errors — check log for details.")
    return "\n".join(parts)


def _build_compile_fix_prompt(name: str, compile_log: str, files: dict) -> str:
    """编译错误的修复 prompt —— 只修语法，不改逻辑"""
    return f"""Fix ONLY the compile errors in the UVM agent "{name}" loopback testbench.
DO NOT rewrite working code. DO NOT change UVM framework structure.
Only fix the exact lines causing the errors below.

COMPILE ERRORS:
{compile_log}

CURRENT FILES (fix ONLY the files with errors):
===FILE:driver===
{files.get('driver', '(missing)')[:2500]}

===FILE:monitor===
{files.get('monitor', '(missing)')[:1500]}

===FILE:test===
{files.get('test', '(missing)')[:1500]}

COMMON FIXES:
- "could not find field X": field doesn't exist in transaction class, remove or comment out reference.
- "Undefined variable 'X'": constraint references non-existent field, remove or fix the constraint.
- "syntax error, unexpected IDENTIFIER": likely truncated file, check class/endclass pairing.
- "Failed to find name 'type_id'": package not compiled, check import and compile order.
- For clocking block output ports: drive with vif.cb.<port> <= value; read from vif.<port> (wire).

RULES:
1. Fix ONLY the compile errors - do NOT change any other code.
2. Output ONLY the fixed files, in this exact format:
===FILE:driver===
<fixed driver.sv>
===FILE:monitor===
<fixed monitor.sv>
===FILE:test===
<fixed test.sv>

No explanations. Only code."""


def _build_sim_fix_prompt(name: str, issue_type: str, diagnosis: str,
                           sim_log: str, files: dict) -> str:
    """仿真失败的修复 prompt —— 根据诊断给针对性指令"""
    # 只送关键代码段，不送整个文件
    driver_excerpt = _extract_method(files.get("driver", ""), "drive_transaction")
    monitor_excerpt = _extract_method(files.get("monitor", ""), "sample_transaction")
    if not driver_excerpt:
        driver_excerpt = files.get("driver", "(missing)")[:2000]
    if not monitor_excerpt:
        monitor_excerpt = files.get("monitor", "(missing)")[:2000]

    fix_instructions = {
        "no_drive": """FIX TARGET: Driver not sending transactions.
1. Check the loopback test uses <name>_random_seq (NOT base_seq which has empty body).
2. Check run_phase calls get_and_drive() (NOT just reset_signals).
3. Check get_and_drive() declares: <name>_seq_item req;
4. Check the sequence's body() actually creates and sends items.
5. Check the test raises an objection (phase.raise_objection) before starting the sequence.""",
        "no_match": """FIX TARGET: Monitor not matching driver's expected values (matched=0, driven>0).
1. QUALIFIER GATE (most common fix): monitor's run_phase must gate on a qualifier signal
   BEFORE creating the item: if (!vif.<qualifier>) continue;
   The gate must be in run_phase (NOT inside sample_transaction), otherwise empty items still get written.
   Qualifier signals: valid, strobe, psel, penable, enable, ready — use the first one found.
2. EXP COPY: driver copies ALL transaction_vars fields to exp (not just output ports):
   exp.<field> = req.<field>; for every field in the transaction.
3. LOOPBACK TB WIRING: check agent_loopback_tb.sv — ALL ports must be connected to wires.
   Input wires must be tied to '0 or looped back from output wires. Floating inputs → Z → compare fails.
4. MONITOR DELAY: add #1 after @(vif.cb) to ensure NBA-driven values propagate before sampling.
5. DRIVER DE-ASSERT: after each transaction, de-assert strobe ports (valid/ready/psel/penable)
   one cycle later so the monitor gate closes between items. If your protocol has no strobe port,
   add a 'valid' output port constrained to 1.""",
        "mismatch": """FIX TARGET: Some items match but others mismatch (0 < matched < driven).
1. TIMING: check monitor samples at #1 after @(vif.cb) — without this delay, NBA-driven
   values may not have propagated to the wire, causing stale reads.
2. QUALIFIER CONSTRAINTS: if the qualifier signal is randomized, constrain it to always be 1
   during transactions. A randomized qualifier (e.g. psel=0) causes the monitor to skip valid cycles.
3. FIELD COMPARE: check which fields are compared — non-driven input ports (which float to Z)
   should NOT be in transaction_vars, or should be set to iscompare=False.
4. EXP COPY: ensure ALL compared fields are copied from req to exp. Fields not copied
   default to 0 and mismatch against actual wire values.
5. LOOPBACK WIRING: check that paired signals are looped back correctly
   (e.g. prdata ← pwdata, pready ← penable, uart_rx ← uart_tx).""",
        "other": """FIX TARGET: Simulation errors or unexpected behavior.
1. Check sim log for UVM_ERROR/UVM_FATAL messages and fix the root cause.
2. Common issues: null handle access, randomization failure, config_db miss.
3. Check that clocking block ports are accessed correctly: drive with vif.cb.<port> <= value,
   sample from vif.<port> (wire) after #1 delay."""
    }
    fix_text = fix_instructions.get(issue_type, fix_instructions["other"])

    return f"""You are debugging a UVM agent loopback test for agent "{name}".

ISSUE: {issue_type}
DIAGNOSIS: {diagnosis}

{fix_text}

SIM LOG (first 1500 chars):
{sim_log[:1500]}

KEY CODE EXCERPTS (ONLY the relevant methods — DO NOT rewrite entire files):

--- driver drive_transaction ---
{driver_excerpt[:2000]}

--- monitor sample_transaction ---
{monitor_excerpt[:2000]}

--- loopback test ---
{files.get('test', '(missing)')[:1500]}

--- loopback env connect_phase ---
{files.get('env', '(missing)')[:1500]}

RULES:
1. Fix ONLY the specific issue described above. Do NOT rewrite working code.
2. The UVM framework (build_phase, agent, sequencer, TLM ports) is already correct — don't touch it.
3. Most common fix: add a qualifier gate in the monitor's sample_transaction.
4. Second most common: fix the expected_port.write timing in drive_transaction.
5. Output ONLY the files that need changes, in this format:
===FILE:driver===
<complete fixed driver.sv>
===FILE:monitor===
<complete fixed monitor.sv>
===FILE:test===
<complete fixed test.sv>

No markdown, no explanations — only code."""


def _extract_method(file_content: str, method_name: str) -> str:
    """Extract a specific task/function body from a SystemVerilog file."""
    import re
    # Match "task method_name" or "function ... method_name" through "endtask"/"endfunction"
    patterns = [
        rf'(?:virtual\s+)?task\s+(?:automatic\s+)?{method_name}\b.*?endtask',
        rf'(?:virtual\s+)?function\s+\S+\s+{method_name}\b.*?endfunction',
    ]
    for pat in patterns:
        m = re.search(pat, file_content, re.DOTALL | re.IGNORECASE)
        if m:
            return m.group(0)
    return ""


def _apply_llm_fixes(llm_output: str, files_to_fix: dict) -> int:
    """Parse LLM output with ===FILE:xxx=== markers and write fixed code."""
    import re
    fixed = 0
    # Split on ===FILE:xxx=== markers
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
            logger.warning(f"[LLM-fix] unknown or too-short tag: {tag} ({len(code)} bytes)")
    return fixed


def _build_filelist_for_tb(output_dir: Path, agents: list, env_name: str,
                           filelist_name: str = "filelist.f") -> Path:
    """Build a filelist referencing the generated UVM files.

    RegressionRunner 自动添加 UVM incdir/pkg，无需在此重复。
    """
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl_path = fl_dir / filelist_name
    lines = []
    for a in agents:
        name = a["name"]
        lines.append(str(output_dir.resolve() / f"agents/{name}/{name}_interface.sv"))
    for a in agents:
        name = a["name"]
        lines.append(f"+incdir+{output_dir.resolve()}/agents/{name}")
        lines.append(str(output_dir.resolve() / f"agents/{name}/{name}_pkg.sv"))
    # RTL 文件（在 rtl/ 目录下所有 .sv）
    rtl_dir = output_dir / "rtl"
    if rtl_dir.exists():
        for sv in sorted(rtl_dir.glob("*.sv")):
            lines.append(str(sv.resolve()))
        lines.append(f"+incdir+{rtl_dir.resolve()}")

    # Bench 顶层（按 glob 匹配，兼容 {module}_bench_tb_top 和 {env}_bench_tb_top 两种命名）
    bench_dir = output_dir / "bench"
    if bench_dir.exists():
        bench_tops = sorted(bench_dir.glob("*_bench_tb_top.sv"))
        for bt in bench_tops:
            lines.append(str(bt.resolve()))
    bench_top_found = len(list(bench_dir.glob("*_bench_tb_top.sv"))) > 0 if bench_dir.exists() else False
    # 兼容旧逻辑（如果 glob 没找到）
    bench_top = output_dir / "bench" / f"{env_name}_bench_tb_top.sv"
    if not bench_top_found and bench_top.exists():
        lines.append(str(bench_top.resolve()))

    lines += [
        f"+incdir+{output_dir.resolve()}/env",
        str(output_dir.resolve() / f"env/{env_name}_pkg.sv"),
        f"+incdir+{output_dir.resolve()}/env/seqs",
        str(output_dir.resolve() / f"env/seqs/{env_name}_seq_pkg.sv"),
        f"+incdir+{output_dir.resolve()}/env/tests",
        str(output_dir.resolve() / f"env/tests/{env_name}_test_pkg.sv"),
    ]
    fl_path.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl_path


# ═══════════════════════════════════════════════════════════
# Log Analysis — 纯日志分析评分工具（不跑编译/仿真）
# ═══════════════════════════════════════════════════════════

def _analyze_compile_log(log_text: str) -> dict:
    """分析编译日志 → PASS/FAIL。0 错误 = PASS。"""
    import re
    errors = len(re.findall(r"\*\* Error", log_text))
    warnings = len(re.findall(r"\*\* Warning", log_text))
    passed = errors == 0
    score = 25 if passed else max(0, 25 - errors * 5)
    return {
        "passed": passed, "status": "PASS" if passed else "FAIL",
        "errors": errors, "warnings": warnings,
        "score": score, "score_str": f"{score}/25",
    }


def _analyze_sim_log(log_text: str) -> dict:
    """分析仿真日志 → PASS/FAIL。

    PASS 条件：0 UVM_ERROR/UVM_FATAL + 无超时 + matched > 0（闭环自发自收成功）。
    """
    import re
    errors = len([l for l in log_text.split("\n")
                  if ("UVM_ERROR" in l or "UVM_FATAL" in l)
                  and "UVM_ERROR :" not in l and "UVM_FATAL :" not in l])
    timeout = "LOOPBACK_TIMEOUT" in log_text
    # 从 scoreboard 报告中提取 matched/mismatched
    matched = 0; mismatched = 0
    all_matched = list(re.finditer(r"\[SCB_LOOP\].*?matched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    all_mismatched = list(re.finditer(r"\[SCB_LOOP\].*?mismatched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    if all_matched:
        matched = int(all_matched[-1].group(1))
    if all_mismatched:
        mismatched = int(all_mismatched[-1].group(1))
    driven_m = re.search(r"driven\s*[:=]\s*(\d+)", log_text)
    driven = int(driven_m.group(1)) if driven_m else 0
    passed = errors == 0 and not timeout and matched > 0
    score = 25 if passed else (15 if errors == 0 and driven > 0 else (10 if driven > 0 else 0))
    return {
        "passed": passed, "status": "PASS" if passed else "FAIL",
        "errors": errors, "timeout": timeout,
        "matched": matched, "mismatched": mismatched, "driven": driven,
        "score": score, "score_str": f"{score}/25",
    }


def _analyze_static(output_dir: Path, agents: list) -> dict:
    """静态检查：所有预期文件是否存在（无日志，直接检查文件系统）。"""
    missing = []; present = []
    for a in agents:
        name = a["name"]
        agent_dir = output_dir / "agents" / name
        expected = [f"{name}_pkg.sv", f"{name}_interface.sv", f"{name}_agent.sv",
                    f"{name}_driver.sv", f"{name}_monitor.sv", f"{name}_sequencer.sv",
                    f"{name}_config.sv", f"{name}_transaction.sv"]
        for f in expected:
            if (agent_dir / f).exists(): present.append(f"{name}/{f}")
            else: missing.append(f"{name}/{f}")
    passed = len(missing) == 0
    score = 25 if passed else max(0, 25 - len(missing) * 5)
    return {"present": len(present), "missing": len(missing), "missing_files": missing,
            "passed": passed, "status": "PASS" if passed else "FAIL",
            "score": score, "score_str": f"{score}/25"}


def _score_from_logs(output_dir: Path, agents: list, env_name: str) -> dict:
    """从日志文件评分：读取编译日志 + 仿真日志 → 三项 PASS/FAIL。

    日志文件位置：
      - 编译日志: {output_dir}/sim/agent/compile_{env_name}.log
      - 仿真日志: {output_dir}/sim/agent/sim_{agent_name}_lb.log
    如果日志文件不存在，回退到自检模式（运行编译/仿真）。
    """
    import os
    # ── 静态检查 ──
    static_r = _analyze_static(output_dir, agents)

    # ── 编译日志分析 ──
    compile_log_path = output_dir / "sim" / "agent" / f"compile_{env_name}.log"
    if compile_log_path.exists():
        compile_r = _analyze_compile_log(compile_log_path.read_text(encoding="utf-8", errors="replace"))
        compile_r["_source"] = "log_file"
    else:
        # fallback: 自检编译
        compile_r = _run_compile_check(output_dir, agents, env_name)
        compile_r["_source"] = "self_check"

    # ── 仿真日志分析（每 agent） ──
    loopback_results = []
    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        sim_log_path = output_dir / "sim" / "agent" / f"sim_{name}_lb.log"
        if sim_log_path.exists():
            sim_r = _analyze_sim_log(sim_log_path.read_text(encoding="utf-8", errors="replace"))
            sim_r["agent"] = name
            sim_r["compile"] = "PASS"  # 日志存在说明编译已过
            sim_r["_source"] = "log_file"
        else:
            # fallback: 自检仿真
            sim_r = _run_agent_loopback(output_dir, name)
            sim_r["_source"] = "self_check"
        loopback_results.append(sim_r)

    all_compile_passed = all(r["compile"] == "PASS" for r in loopback_results)
    all_sim_passed = all(r.get("passed", False) for r in loopback_results)
    loopback_passed = all_compile_passed and all_sim_passed

    total_matched = sum(r.get("matched", 0) for r in loopback_results)
    loopback_score = 25 if loopback_passed else max(0, 25 - sum(1 for r in loopback_results if not r.get("passed", False)) * 8)

    loopback_r = {
        "agents": loopback_results,
        "all_compile_pass": all_compile_passed,
        "all_passed": loopback_passed,
        "passed": loopback_passed,
        "matched": total_matched,
        "score": loopback_score,
        "total_score": f"{loopback_score}/25",
        "_source": "log_file" if all(r.get("_source") == "log_file" for r in loopback_results) else "mixed",
    }

    # ── 汇总 ──
    all_three_passed = static_r["passed"] and compile_r["passed"] and loopback_passed
    total = static_r["score"] + compile_r["score"] + loopback_score
    max_total = 75

    return {
        "passed": all_three_passed,
        "static_passed": static_r["passed"],
        "compile_passed": compile_r["passed"],
        "loopback_passed": loopback_passed,
        "scores": {
            "static": f"{static_r['score']}/25",
            "compile": f"{compile_r['score']}/25",
            "loopback": f"{loopback_score}/25",
            "total": f"{total}/{max_total}",
        },
        "total": total,
        "max_total": max_total,
        "details": {
            "static": static_r,
            "compile": compile_r,
            "loopback": loopback_r,
        },
        "verdict": "READY" if all_three_passed else "NEEDS_FIX",
    }


# ── 原始自检函数（保留用于回退） ──

def _run_static_check(output_dir: Path, agents: list) -> dict:
    """Real static check: verify expected files exist."""
    missing = []
    present = []
    for a in agents:
        name = a["name"]
        agent_dir = output_dir / "agents" / name
        expected = [f"{name}_pkg.sv", f"{name}_interface.sv", f"{name}_agent.sv",
                    f"{name}_driver.sv", f"{name}_monitor.sv", f"{name}_sequencer.sv",
                    f"{name}_config.sv", f"{name}_transaction.sv"]
        for f in expected:
            if (agent_dir / f).exists(): present.append(f"{name}/{f}")
            else: missing.append(f"{name}/{f}")
    passed = len(missing) == 0
    score = 25 if passed else max(0, 25 - len(missing) * 5)  # 0-25 scale
    return {"present": len(present), "missing": len(missing), "missing_files": missing,
            "score": score, "status": "PASS" if passed else "FAIL",
            "passed": passed}


def _run_compile_check(output_dir: Path, agents: list, env_name: str) -> dict:
    """编译检查 —— 使用 RegressionRunner，保存日志到 sim/agent/compile_{env_name}.log。"""
    import time
    from src.tools.lib.regress_dir import get_compile_dir
    fl = _build_filelist_for_tb(output_dir, agents, env_name)
    top = f"{env_name}_bench_tb_top"

    t0 = time.time()
    runner = RegressionRunner(
        env_output_dir=str(output_dir),
        filelist=str(fl.resolve()),
        top_module=top,
        coverage=False,
        compile_dir=get_compile_dir(output_dir),
    )
    result = runner.compile()
    elapsed = round(time.time() - t0, 1)

    # 保存编译日志（RegressionRunner 不直接返回 log text，从 work_dir 读取）
    log_text = ""
    sim_agent_dir = output_dir / "sim" / "agent"
    sim_agent_dir.mkdir(parents=True, exist_ok=True)
    log_path = sim_agent_dir / f"compile_{env_name}.log"
    # RegressionRunner 编译日志通过 stdout 捕获，这里用 errors count 作为最小信息
    compile_errs = result.get("errors", 0)
    passed = result["status"] == "PASS" and compile_errs == 0
    # 写入简要日志
    log_path.write_text(
        f"status: {result['status']}\nerrors: {compile_errs}\ntime: {elapsed}s\n",
        encoding="utf-8", errors="replace")

    return {
        "status": "PASS" if passed else "FAIL",
        "errors": compile_errs, "time_s": elapsed,
        "score": 25 if passed else max(0, 25 - compile_errs * 5),
        "passed": passed,
        "log_file": str(log_path),
    }


def _build_loopback_filelist(output_dir: Path, agent_name: str) -> Path:
    """Build filelist for single-agent loopback testbench.

    RegressionRunner 自动添加 UVM incdir/pkg，无需在此重复。
    定义 agent_loop_back_test 确保 package 包含 loopback 文件。
    """
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl = fl_dir / f"filelist_{agent_name}_lb.f"
    agent_dir = output_dir / "agents" / agent_name
    lines = [
        f"+define+{agent_name}_loop_back_test",
        f"+incdir+{agent_dir.resolve()}",
        f"+incdir+{agent_dir.resolve()}/loopback",
        str(agent_dir.resolve() / f"{agent_name}_interface.sv"),
        str(agent_dir.resolve() / f"{agent_name}_pkg.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_scb.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_env.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_test.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_tb.sv"),
    ]
    fl.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl


def _parse_sim_log(log_text: str) -> dict:
    """Parse vsim log for UVM errors and loopback results."""
    import re
    errors = len([l for l in log_text.split("\n") if ("UVM_ERROR" in l or "UVM_FATAL" in l) and "UVM_ERROR :" not in l and "UVM_FATAL :" not in l])
    warnings = len([l for l in log_text.split("\n") if "UVM_WARNING" in l])
    timeout = "LOOPBACK_TIMEOUT" in log_text

    # Extract SCB matched/mismatched from LAST scoreboard report in log (final result)
    matched = 0; mismatched = 0
    all_matched = list(re.finditer(r"\[SCB_LOOP\].*?matched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    all_mismatched = list(re.finditer(r"\[SCB_LOOP\].*?mismatched\s*[:=]\s*(\d+)", log_text, re.IGNORECASE))
    if all_matched:
        matched = int(all_matched[-1].group(1))  # last report = final result
    if all_mismatched:
        mismatched = int(all_mismatched[-1].group(1))
    # Also check driver/monitor counts
    for m in re.finditer(r"Driver.*?driven\s*[:=]\s*(\d+)", log_text, re.IGNORECASE):
        driven = int(m.group(1))
    for m in re.finditer(r"Monitor.*?collected\s*[:=]\s*(\d+)", log_text, re.IGNORECASE):
        collected = int(m.group(1))

    # Pass = 0 fatal errors, no timeout, and driver actually sent items
    driven = int(re.search(r"driven\s*[:=]\s*(\d+)", log_text).group(1)) if re.search(r"driven\s*[:=]\s*(\d+)", log_text) else 0
    passed = errors == 0 and not timeout and driven > 0

    return {"passed": passed, "errors": errors, "warnings": warnings,
            "timeout": timeout, "matched": matched, "mismatched": mismatched,
            "driven": driven}


def _try_autofix_loopback(output_dir: Path, agent_name: str, compile_log: str) -> bool:
    """Auto-fix common template-generated loopback issues BEFORE LLM iteration.
    Handles: missing qualifier gating, empty sequence, field refs, exp copy, env connections."""
    fixed_any = False
    agent_dir = output_dir / "agents" / agent_name
    test_file = agent_dir / "loopback" / f"{agent_name}_loopback_test.sv"
    driver_file = agent_dir / f"{agent_name}_driver.sv"
    monitor_file = agent_dir / f"{agent_name}_monitor.sv"
    env_file = agent_dir / "loopback" / f"{agent_name}_loopback_env.sv"

    # ── Fix 1: base_seq → random_seq (base_seq has empty body → driven=0) ──
    if test_file.exists():
        content = test_file.read_text(encoding="utf-8", errors="replace")
        if f"{agent_name}_base_seq" in content and f"{agent_name}_random_seq" not in content:
            content = content.replace(f"{agent_name}_base_seq", f"{agent_name}_random_seq")
            if "num_transactions" not in content and "seq.start" in content:
                content = content.replace(
                    "seq.start(env_h.agent_h.sqr);",
                    "seq.num_transactions = num_items;\n    seq.delay_min = 0;\n    seq.delay_max = 3;\n    seq.start(env_h.agent_h.sqr);")
            test_file.write_text(content, encoding="utf-8", errors="replace")
            logger.info(f"Auto-fixed {agent_name}: base_seq → random_seq")
            fixed_any = True
        elif "#200ns" not in content and "raise_objection" in content:
            content = content.replace(
                "phase.raise_objection(this);",
                "phase.raise_objection(this);\n    #200ns; // wait for reset release")
            test_file.write_text(content, encoding="utf-8", errors="replace")
            logger.info(f"Auto-fixed {agent_name}: added reset wait in test")
            fixed_any = True

    # ── Fix 2: compile errors — field not found ──
    if "could not find field" in compile_log or "Failed to find" in compile_log:
        for sv_file in [test_file, driver_file, monitor_file]:
            if not sv_file or not sv_file.exists():
                continue
            fc = sv_file.read_text(encoding="utf-8", errors="replace")
            modified = False
            for line in compile_log.split("\n"):
                m = re.search(r"field\s+'(\w+)'\s+in", line, re.IGNORECASE)
                if m:
                    bad = m.group(1)
                    if f".{bad}" in fc:
                        fc = fc.replace(f".{bad}", f"//.{bad} // auto-removed")
                        modified = True
            if modified:
                sv_file.write_text(fc, encoding="utf-8", errors="replace")
                logger.info(f"Auto-fixed {agent_name}: removed bad fields in {sv_file.name}")
                fixed_any = True

    # ── Fix 3: monitor lacks qualifier gating (samples every cycle → 0 matches) ──
    if monitor_file.exists():
        mc = monitor_file.read_text(encoding="utf-8", errors="replace")
        sample_fn = _extract_method(mc, "sample_transaction")
        if sample_fn:
            # Check if there's ANY qualifier (if, case, etc.)
            has_qualifier = bool(re.search(
                r'\bif\s*\(|case\s*\(|&\s*vif\.|vif\.\w+\s*==|vif\.\w+\s*!=', sample_fn))
            if not has_qualifier:
                # Find the port names used in sample_transaction
                ports_in_sample = re.findall(r'vif\.(\w+)', sample_fn)
                # Find a likely qualifier signal from the interface
                interface_file = agent_dir / f"{agent_name}_interface.sv"
                qualifier_signal = None
                if interface_file.exists():
                    ifc = interface_file.read_text(encoding="utf-8", errors="replace")
                    # Look for valid, strobe, enable, sel, penable signals in the interface
                    for candidate in ["valid", "strobe", "psel", "penable", "enable", "ready"]:
                        if re.search(rf'\b{candidate}\b', ifc):
                            qualifier_signal = candidate
                            break
                if qualifier_signal and "item." in sample_fn:
                    # Wrap ALL sampling lines in if gate
                    sample_lines = sample_fn.strip().split("\n")
                    # Find all "item.xxx = vif.xxx;" lines
                    item_lines = [l for l in sample_lines if "item." in l and "vif." in l]
                    if item_lines:
                        # Build gated version: wrap all item lines inside if block
                        indented = "\n".join("    " + l.strip() for l in item_lines)
                        new_block = f"if (vif.{qualifier_signal}) begin\n{indented};\n  end"
                        # Replace the raw item lines with the gated version
                        # Join original lines to find the full block
                        old_block = "\n".join(item_lines)
                        mc = mc.replace(old_block, new_block)
                        monitor_file.write_text(mc, encoding="utf-8", errors="replace")
                        logger.info(f"Auto-fixed {agent_name}: added monitor qualifier gate on vif.{qualifier_signal} for {len(item_lines)} ports")
                    fixed_any = True

    # ── Fix 4: driver exp copy — ensure output ports (that exist in transaction) are copied from req ──
    if driver_file.exists():
        dc = driver_file.read_text(encoding="utf-8", errors="replace")
        drive_fn = _extract_method(dc, "drive_transaction")
        if drive_fn:
            # Check if exp copy exists in drive_transaction
            if "exp." not in drive_fn and "expected_port.write" in drive_fn:
                # Read transaction file to find which fields actually exist
                txn_file = agent_dir / f"{agent_name}_transaction.sv"
                txn_fields = set()
                if txn_file.exists():
                    tc = txn_file.read_text(encoding="utf-8", errors="replace")
                    txn_fields = set(re.findall(r'rand\s+\S+\s+(\w+)\s*;', tc))
                    # Also add built-in fields
                    txn_fields.update(["req_id", "tag", "error", "begin_time"])
                # Only add exp copies for ports that exist as transaction fields
                valid_ports = [p for p in re.findall(r'vif\.cb\.(\w+)\s*<=', drive_fn) if p in txn_fields]
                if valid_ports:
                    exp_lines = "\n".join(
                        f"    exp.{p} = req.{p};" for p in valid_ports)
                    # Insert exp copy before expected_port.write
                    dc = dc.replace(
                        "expected_port.write(exp);",
                        f"{exp_lines}\n    expected_port.write(exp);")
                    driver_file.write_text(dc, encoding="utf-8", errors="replace")
                    logger.info(f"Auto-fixed {agent_name}: added exp copy for {len(valid_ports)} ports")
                    fixed_any = True

    # ── Fix 5: env connect_phase — ensure TLM connections exist ──
    if env_file.exists():
        ec = env_file.read_text(encoding="utf-8", errors="replace")
        if "drv.expected_port.connect" not in ec:
            # Template should already have this — but re-add if missing
            ec = ec.replace(
                "super.connect_phase(phase);",
                "super.connect_phase(phase);\n    agent_h.drv.expected_port.connect(scb_h.expected_export);\n    agent_h.mon.item_collected_port.connect(scb_h.actual_export);")
            env_file.write_text(ec, encoding="utf-8", errors="replace")
            logger.info(f"Auto-fixed {agent_name}: added TLM connections in env")
            fixed_any = True

    return fixed_any


def _run_agent_loopback(output_dir: Path, agent_name: str) -> dict:
    """Run single-agent loopback simulation + parse log.

    编译使用 RegressionRunner，仿真使用 vsim（RegressionRunner 无独立 sim 接口）。
    """
    import subprocess, time, os
    fl = _build_loopback_filelist(output_dir, agent_name)
    top = f"{agent_name}_loopback_tb"

    # ── 从 RegressionRunner 取 QuestaSim 路径（避免硬编码） ──
    from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner as _RR
    QUESTA = _RR.QUESTA if hasattr(_RR, 'QUESTA') else "f:/questasim64_2024.1/win64"
    vsim = os.path.join(QUESTA, "vsim.exe")

    t0 = time.time()
    print(f"    [{agent_name}] compiling loopback TB... ", end="", flush=True)

    from src.tools.lib.regress_dir import get_compile_dir as _gcd, get_sim_dir as _gsd
    _cd = _gcd(output_dir)
    _sd = _gsd(output_dir)

    # ── 编译：使用 RegressionRunner ──
    runner = RegressionRunner(
        env_output_dir=str(output_dir),
        filelist=str(fl.resolve()),
        top_module=top,
        coverage=False,
        compile_dir=_cd,
        sim_dir=_sd,
    )
    compile_result = runner.compile()
    compile_ok = compile_result["status"] == "PASS"
    compile_errs = compile_result.get("errors", 0)
    compile_time = round(time.time() - t0, 1)
    print(f"compile {'PASS' if compile_ok else 'FAIL'}({compile_errs} errs, {compile_time}s)", flush=True)

    if not compile_ok:
        fixed = _try_autofix_loopback(output_dir, agent_name, compile_result.get("stderr", ""))
        if fixed:
            fl = _build_loopback_filelist(output_dir, agent_name)
            runner = RegressionRunner(
                env_output_dir=str(output_dir),
                filelist=str(fl.resolve()),
                top_module=top, coverage=False,
                compile_dir=_cd,
                sim_dir=_sd,
            )
            compile_result = runner.compile()
            compile_ok = compile_result["status"] == "PASS"
            compile_errs = compile_result.get("errors", 0)
            compile_time = round(time.time() - t0, 1)
        if not compile_ok:
            return {"compile": "FAIL", "errors": compile_errs, "time_s": compile_time,
                    "sim": "SKIPPED", "score": 0, "passed": False,
                    "autofix_attempted": bool(fixed)}

    compile_base = output_dir / _cd if _cd else output_dir
    wd = (compile_base / "build" / "work").resolve()  # 与 RegressionRunner 默认 work_dir 一致
    wd_str = str(wd).replace("\\", "/")
    sim_agent_dir = (output_dir / "sim" / "agent").resolve()
    sim_agent_dir.mkdir(parents=True, exist_ok=True)
    sim_dir = str(output_dir.resolve()).replace("\\", "/")
    sim_agent_str = str(sim_agent_dir).replace("\\", "/")
    log_path = sim_agent_dir / f"sim_{agent_name}_lb.log"

    # ── 仿真：vsim（RegressionRunner 无单 test sim 接口） ──
    print(f"    [{agent_name}] simulating 2us... ", end="", flush=True)
    if log_path.exists():
        log_path.unlink()

    r2 = subprocess.run([
        vsim, "-c", "-sv_lib", f"{QUESTA.replace('win64','')}{os.environ.get('UVM_VERSION','uvm-1.2')}/win64/uvm_dpi",
        "-onfinish", "stop",
        "-do", "log -r /*; run -all; quit -f",
        "-wlf", f"{sim_agent_str}/wave_{agent_name}_lb.wlf",
        "-work", wd_str,
        "-l", f"{sim_agent_str}/sim_{agent_name}_lb.log",
        top, f"+UVM_TESTNAME={agent_name}_loopback_test",
        "+UVM_TIMEOUT=100000",
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, cwd=str(output_dir.resolve()))

    sim_time = round(time.time() - t0 - compile_time, 1)
    parsed = _parse_sim_log(r2.stdout)

    # ── Sim retry loop（仅重试仿真，编译已过） ──
    MAX_SIM_RETRIES = 3
    for retry in range(MAX_SIM_RETRIES):
        if parsed["passed"] or parsed["errors"] == 0:
            break
        fixed = _try_autofix_loopback(output_dir, agent_name, r2.stdout)
        if not fixed:
            break
        # 重新仿真（编译已过，跳过重编译）
        r2 = subprocess.run([
            vsim, "-c", "-sv_lib", f"{QUESTA.replace('win64','')}{os.environ.get('UVM_VERSION','uvm-1.2')}/win64/uvm_dpi",
            "-onfinish", "stop",
            "-do", "log -r /*; run -all; quit -f",
            "-wlf", f"{sim_agent_str}/wave_{agent_name}_lb.wlf",
            "-work", wd_str, top,
            f"+UVM_TESTNAME={agent_name}_loopback_test",
            "+UVM_TIMEOUT=100000",
        ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30, cwd=str(output_dir.resolve()))
        parsed = _parse_sim_log(r2.stdout)
        sim_time = round(time.time() - t0 - compile_time, 1)
        print(f"    [{agent_name}] retry {retry+1}: errs={parsed['errors']}, matched={parsed.get('matched',0)}", flush=True)
        if parsed["passed"] and parsed["errors"] == 0:
            break

    sim_ok = parsed["passed"] and parsed["errors"] == 0
    passed = sim_ok and parsed.get("matched", 0) > 0
    if passed:
        score = 25
    elif sim_ok:
        score = 15
    elif parsed.get("driven", 0) > 0 and parsed.get("matched", 0) > 0:
        score = 10
    else:
        score = 0
    status = "PASS" if passed else ("OK" if score >= 15 else ("WARN" if score >= 10 else "FAIL"))
    print(f"    [{agent_name}] sim {status}(errs={parsed['errors']}, driven={parsed.get('driven',0)}, matched={parsed.get('matched',0)}, score={score}, {sim_time}s)", flush=True)

    return {
        "agent": agent_name,
        "compile": "PASS" if compile_ok else "FAIL",
        "compile_errors": compile_errs,
        "compile_time_s": compile_time,
        "sim_time_s": sim_time,
        "sim_passed": parsed["passed"],
        "sim_errors": parsed["errors"],
        "matched": parsed.get("matched", 0),
        "mismatched": parsed.get("mismatched", 0),
        "driven": parsed.get("driven", 0),
        "errors": parsed["errors"],
        "timeout": parsed.get("timeout", False),
        "score": score,
        "passed": passed,
        "compile_log": "",
        "sim_log": r2.stdout if 'r2' in dir() else "",
    }


def _run_loopback_check(output_dir: Path, agents: list, env_name: str) -> dict:
    """Real loopback: compile + simulate agent_tb, parse logs for Driver->Monitor pass/fail."""
    results = []
    for a in agents:
        name = a.get("name", a) if isinstance(a, dict) else a
        r = _run_agent_loopback(output_dir, name)
        results.append(r)

    total_score = sum(r["score"] for r in results)
    all_passed = all(r["compile"] == "PASS" and r.get("matched", 0) > 0 for r in results)
    # 0-25 scale
    score = 25 if all_passed else max(0, 25 - sum(1 for r in results if r.get("matched", 0) == 0) * 8)

    return {
        "agents": results,
        "all_compile_pass": all(r["compile"] == "PASS" for r in results),
        "all_passed": all_passed,
        "passed": all_passed,
        "total_score": f"{score}/25",
        "score": score,
    }


def _generate_real_quality_report(output_dir: Path, agents: list,
                                  env_name: str) -> dict:
    """从日志文件生成质量报告 —— 纯日志分析，不跑编译/仿真。

    日志文件位置：
      - 编译日志: {output_dir}/sim/agent/compile_{env_name}.log
      - 仿真日志: {output_dir}/sim/agent/sim_{agent_name}_lb.log
    如果日志文件不存在，回退到自检模式。
    """
    # ── 优先使用日志分析 ──
    result = _score_from_logs(output_dir, agents, env_name)

    static_r = result["details"]["static"]
    compile_r = result["details"]["compile"]
    loopback_r = result["details"]["loopback"]

    # If loopback fails and we have LLM available, try fix
    if not result["loopback_passed"] and compile_r["passed"]:
        logger.info("Loopback FAIL by log analysis, attempting LLM-driven fix...")
        refine_result = _llm_refine_sim_timing(output_dir, agents, env_name)
        if refine_result.get("fixed", 0) > 0:
            # Re-analyze logs after LLM fixes (re-run log analysis on potentially updated log files)
            result = _score_from_logs(output_dir, agents, env_name)
            result["_llm_refined"] = True
            result["_llm_fixed_count"] = refine_result["fixed"]
            static_r = result["details"]["static"]
            compile_r = result["details"]["compile"]
            loopback_r = result["details"]["loopback"]

    all_three_passed = result["passed"]
    total = result["total"]
    max_total = result["max_total"]
    grade = "A" if total >= 70 else "B" if total >= 50 else "C" if total >= 30 else "D"

    report = {
        "timestamp": datetime.now().isoformat(),
        "agent": "uvm",
        "output_dir": str(output_dir.resolve()),
        "env_name": env_name,
        "scores": result["scores"],
        "grade": grade,
        "passed": all_three_passed,
        "details": {
            "static": static_r,
            "compile": compile_r,
            "loopback": loopback_r,
        },
        "issues": {"errors": compile_r.get("errors", 0),
                   "missing_files": static_r.get("missing_files", [])},
        "verdict": "READY" if all_three_passed else "NEEDS_FIX",
        "recommendations": (
            ["Static check passed"] if result["static_passed"]
            else [f"Missing {len(static_r.get('missing_files',[]))} files"]
        ) + ([f"Compile: {compile_r.get('errors',0)} errors"] if not result["compile_passed"] else ["Compile passed"])
          + (["Loopback passed — log analysis"] if result["loopback_passed"]
             else [f"Loopback failed — matched={loopback_r.get('matched',0)}"]),
    }

    # Write quality report
    report_path = output_dir / "quality_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8", errors="replace")
    return report


# ── Runtime context: use _uvm_ctx singleton (imported from this module) ──


# ── LangChain Tools (for LLM mode) ──

@tool("generate_uvm_from_spec")
def generate_uvm_from_spec(spec_text: str) -> str:
    """从规格文本生成 UVM 验证环境代码。自动选择已有 YAML 或从 spec 构造。

    输入: 规格文本（Markdown）。输出: 生成文件列表 JSON。
    """
    from src.tools.uvm_tools.tool_uvm.gen_uvm import UVMGenerator, JinjaRenderer, TEMPLATES_DIR

    yaml_dir = (Path(__file__).resolve().parent / "tool_uvm")
    output_dir = Path(_uvm_ctx.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    renderer = JinjaRenderer(TEMPLATES_DIR)
    generator = UVMGenerator(renderer, output_dir)
    all_files = []

    # 从 spec 提取模块名
    import re
    module_match = re.search(r'(?:#|module\s+)\s*(\w+)', spec_text, re.IGNORECASE)
    module_name = module_match.group(1) if module_match else "dut"

    # 按模块名查找已有 YAML：尝试全名、前缀、首段
    name_variants = [module_name, module_name.upper(), module_name.lower()]
    for seg in re.split(r'[_\-\s]+', module_name):
        if len(seg) >= 2:
            name_variants.extend([seg, seg.upper()])
    existing_yamls = []
    if yaml_dir.exists():
        for variant in name_variants:
            for pattern in [f"{variant}_*.yaml"]:
                found = sorted(yaml_dir.glob(pattern))
                if found:
                    existing_yamls = found
                    break
            if existing_yamls:
                break
    if existing_yamls:
        print(f"  [UVM] Found {len(existing_yamls)} YAML files for module '{module_name}'", flush=True)
        # 复制 YAML 到 inputs/yaml/uvm/ 归档
        import shutil as _shutil
        uvm_yaml_archive = output_dir / "inputs" / "yaml" / "uvm"
        uvm_yaml_archive.mkdir(parents=True, exist_ok=True)
        for yp in existing_yamls:
            _shutil.copy2(yp, uvm_yaml_archive / yp.name)
            generated = generator.run([yp])
            all_files.extend(generated)
            print(f"    {yp.name} → {len(generated)} files", flush=True)
    else:
        # 从 spec 构造 agent YAML
        print(f"  [UVM] No YAML for '{module_name}', constructing from spec...", flush=True)
        # 构造基础 agent YAML
        for direction in ["in", "out"]:
            agent_name = f"{module_name}_{direction}"
            yaml_str = f"""interfaces:
  name: {agent_name}
  clock: clk
  reset: rst
  parameters:
    - {{ name: DATA_WIDTH, type: int, value: '32' }}
  ports:
    - {{ name: clk, dir: input, width: 1 }}
    - {{ name: rst, dir: input, width: 1 }}
    - {{ name: data, dir: {'output' if direction == 'in' else 'input'}, width: DATA_WIDTH }}
    - {{ name: valid, dir: {'output' if direction == 'in' else 'input'}, width: 1 }}
    - {{ name: ready, dir: {'input' if direction == 'in' else 'output'}, width: 1 }}
  transaction_vars:
    - {{ name: data, type: "bit [DATA_WIDTH-1:0]", iscompare: 'True', isrand: 'True' }}
  transaction_constraints:
    - name: valid_c
      value: '{{ data inside {{[0:255]}}; }}'
  config:
    is_active: UVM_ACTIVE
"""
            uvm_yaml_dir = output_dir / "inputs" / "yaml" / "uvm"
            uvm_yaml_dir.mkdir(parents=True, exist_ok=True)
            yaml_path = uvm_yaml_dir / f"{agent_name}.yaml"
            yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
            generated = generator.run([yaml_path])
            all_files.extend(generated)
            print(f"    {yaml_path.name} → {len(generated)} files", flush=True)

        # 构造 env + bench YAML
        env_yaml_str = f"""environment:
  name: {module_name}_env
  agents:
    {module_name}_in:
      interface: {module_name}_in
      clock: clk
      reset: rst
    {module_name}_out:
      interface: {module_name}_out
      clock: clk
      reset: rst
"""
        uvm_yaml_dir = output_dir / "inputs" / "yaml" / "uvm"
        uvm_yaml_dir.mkdir(parents=True, exist_ok=True)
        env_path = uvm_yaml_dir / "env.yaml"
        env_path.write_text(env_yaml_str, encoding="utf-8", errors="replace")
        generated = generator.run([env_path])
        all_files.extend(generated)

        bench_yaml_str = f"""bench:
  name: {module_name}_bench
  env_name: {module_name}_env
  timeout: 10ms
  clk_rst:
    clocks:
      - {{ name: clk, period: 10ns, init: 0 }}
    resets:
      - {{ name: rst_n, init: 0, release_delay: 0 }}
  wire_decls:
    - {{ name: data_in,  width: 32 }}
    - {{ name: data_out, width: 32 }}
    - {{ name: valid_in, width: 1 }}
    - {{ name: ready_in, width: 1 }}
    - {{ name: valid_out, width: 1 }}
    - {{ name: ready_out, width: 1 }}
  assignments:
    - {{ lhs: ready_out, rhs: "1'b0" }}
  agents:
    {module_name}_in:
      interface: {module_name}_in
      clock: clk
      reset: rst_n
      instance: {module_name}_in_if
      connections:
        - {{ port: clk, wire: clk }}
        - {{ port: rst, wire: rst_n }}
        - {{ port: data, wire: data_in }}
        - {{ port: valid, wire: valid_in }}
        - {{ port: ready, wire: ready_in }}
    {module_name}_out:
      interface: {module_name}_out
      clock: clk
      reset: rst_n
      instance: {module_name}_out_if
      connections:
        - {{ port: clk, wire: clk }}
        - {{ port: rst, wire: rst_n }}
        - {{ port: data, wire: data_out }}
        - {{ port: valid, wire: valid_out }}
        - {{ port: ready, wire: ready_out }}
  dut:
    module: {module_name}
    instance: u_{module_name}
    parameters:
      - {{ name: DATA_WIDTH, value: 32 }}
    ports:
      - {{ name: clk, connection: clk }}
      - {{ name: rst_n, connection: rst_n }}
      - {{ name: data_in, connection: data_in }}
      - {{ name: valid_in, connection: valid_in }}
      - {{ name: ready_in, connection: ready_in }}
      - {{ name: data_out, connection: data_out }}
      - {{ name: valid_out, connection: valid_out }}
      - {{ name: ready_out, connection: ready_out }}
"""
        bench_path = uvm_yaml_dir / "bench.yaml"
        bench_path.write_text(bench_yaml_str, encoding="utf-8", errors="replace")
        generated = generator.run([bench_path])
        all_files.extend(generated)

    # 更新运行时上下文
    agent_names = set()
    for f in all_files:
        parts = Path(str(f)).parts
        if "agents" in parts:
            idx = parts.index("agents")
            if idx + 1 < len(parts):
                agent_names.add(parts[idx + 1])
    if agent_names:
        _uvm_ctx.update_agents([{"name": n} for n in sorted(agent_names)])
        if not _uvm_ctx.env_name or _uvm_ctx.env_name == "dut":
            _uvm_ctx.update_env_name(f"{module_name}_env")

    # ── 链式质量检查：生成 → 静态 → 编译 ──
    agent_list = [{"name": n} for n in sorted(agent_names)]
    env_name = _uvm_ctx.env_name or f"{module_name}_env"
    quality = _generate_real_quality_report(output_dir, agent_list, env_name)
    all_passed = quality.get("passed", False)

    return json.dumps({
        "status": "generated",
        "file_count": len(all_files),
        "agents": sorted(agent_names),
        "files": [str(f) for f in all_files],
        "quality": {
            "passed": all_passed,
            "verdict": quality.get("verdict", "?"),
            "scores": quality.get("scores", {}),
            "static_pass": quality["details"]["static"].get("passed", False),
            "compile_pass": quality["details"]["compile"].get("passed", False),
            "loopback_pass": quality["details"]["loopback"].get("passed", False),
        },
        "next_step": "ALL PASS" if all_passed else "Call read_file to inspect errors, write_file to fix, then re-run check_compile"
    }, ensure_ascii=False)


@tool("check_static")
def check_static(env_dir: str = "") -> str:
    """Static check: verify all expected files exist."""
    od = Path(env_dir) if env_dir else Path(_uvm_ctx.output_dir)
    agents = _uvm_ctx.agents
    r = _run_static_check(od, agents)
    return json.dumps(r, ensure_ascii=False)

@tool("check_compile")
def check_compile(env_dir: str = "") -> str:
    """Compile check: run QuestaSim vlog, return errors/warnings."""
    od = Path(env_dir) if env_dir else Path(_uvm_ctx.output_dir)
    agents = _uvm_ctx.agents
    env_name = _uvm_ctx.env_name
    r = _run_compile_check(od, agents, env_name)
    return json.dumps(r, ensure_ascii=False)

@tool("check_loopback")
def check_loopback(env_dir: str = "") -> str:
    """Loopback: compile + simulate each agent, parse log for pass/fail."""
    od = Path(env_dir) if env_dir else Path(_uvm_ctx.output_dir)
    agents = _uvm_ctx.agents
    r = _run_loopback_check(od, agents, _uvm_ctx.env_name)
    return json.dumps(r, ensure_ascii=False)

@tool("check_health")
def check_health(env_dir: str = "") -> str:
    """Health check: compile + simulate env test 100us."""
    od = Path(env_dir) if env_dir else Path(_uvm_ctx.output_dir)
    r = _run_compile_check(od, _uvm_ctx.agents, _uvm_ctx.env_name)
    return json.dumps({"status": r.get("status","?"), "errors": r.get("errors",0), "score": f"{r.get('score',0)}/25"})

@tool("read_file")
def read_file(path: str) -> str:
    """Read a generated SystemVerilog file for analysis/fixing."""
    p = Path(path)
    if not p.is_absolute():
        p = Path(_uvm_ctx.output_dir) / path
    if p.exists():
        return p.read_text(encoding="utf-8", errors="replace")
    return f"ERROR: file not found: {p}"

@tool("write_file")
def write_file(path_content: str) -> str:
    """Write/overwrite a SystemVerilog file. Input format: 'filepath::content'."""
    parts = path_content.split("::", 1)
    if len(parts) != 2:
        return "ERROR: use format 'path::content'"
    path, content = parts
    p = Path(path.strip())
    if not p.is_absolute():
        p = Path(_uvm_ctx.output_dir) / path.strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip(), encoding="utf-8")
    return f"OK: wrote {len(content)} bytes to {p}"

