"""
LLM 生成协议时序 —— 为 UVM driver/monitor 生成 protocol-specific 驱动和采样代码

用法:
    from src.tools.lib.llm_custom_logic import llm_generate_custom_logic
    snippets = llm_generate_custom_logic("apb_agent", ports, is_active=True)
    # snippets["custom_drive_logic"] → SV code
"""
from pathlib import Path
import structlog

logger = structlog.get_logger()


def llm_generate_custom_logic(agent_name: str, ports: list, is_active: bool = True) -> dict:
    """生成 driver/monitor 的协议时序代码片段。"""
    if not ports:
        return {"custom_drive_logic": "", "custom_sample_logic": ""}

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

    has_apb = any(n in output_names for n in ["psel", "penable", "pwrite", "pwdata"])
    has_valid = any("valid" in p.get("name", "").lower() for p in output_ports)
    has_ready = any("ready" in p.get("name", "").lower() for p in input_ports)
    has_strobe = any("strobe" in n.lower() or "wen" in n.lower() or "ren" in n.lower() for n in output_names)

    if has_apb:
        protocol_hint = """APB PROTOCOL — LOOPBACK MODE:
  Driver: 1) setup paddr/pwrite/pwdata/psel=1/penable=0; @(vif.cb)
          2) access penable=1; @(vif.cb)  3) de-assert psel=0/penable=0
  Monitor: @(vif.cb); if(vif.psel && vif.penable) sample ALL ports. NO pready gate."""
    elif has_valid and has_ready:
        protocol_hint = """VALID/READY HANDSHAKE:
  Driver: @(vif.cb); drive data+valid=1; wait while(!vif.ready); de-assert valid
  Monitor: @(vif.cb); if(vif.ready) sample fields."""
    elif has_strobe:
        protocol_hint = """STROBE-BASED:
  Driver: @(vif.cb); drive data+strobe=1; @(vif.cb); de-assert strobe
  Monitor: @(vif.cb); if(vif.strobe) sample ALL fields."""
    else:
        protocol_hint = """GENERAL BUS:
  Driver: @(vif.cb); drive ALL output ports. Monitor gate on first toggling signal."""

    prompt = f"""You are a UVM VIP timing expert. Write protocol timing snippets for LOOPBACK SELF-TEST.

AGENT: {agent_name}
TYPE: {"ACTIVE" if is_active else "PASSIVE"}
OUTPUT PORTS: {output_names}
INPUT PORTS: {input_names}

INTERFACE PORTS:
{port_desc}

{protocol_hint}

CRITICAL RULES:
0. DRIVER variable: req (e.g., vif.cb.<port> <= req.<port>)
   MONITOR variable: item (e.g., item.<port> = vif.<port>)
1. Output ONLY SystemVerilog code — NO markdown, NO fences, NO explanation.
2. DRIVE: use vif.cb.<port> <= req.<port>. No hardcoded constants.
3. SAMPLE: gate on a qualifier signal to skip idle cycles.
4. Keep each snippet under 10 lines.

OUTPUT EXACTLY:
===DRIVE===
<drive code>
===SAMPLE===
<sample code>"""

    code = _call_llm_raw(prompt, "", port_desc)
    result = {"custom_drive_logic": "", "custom_sample_logic": ""}

    if code:
        import re as _re2
        dm = _re2.search(r'===DRIVE===\s*\n(.*?)(?=\n===SAMPLE===|\Z)', code, _re2.DOTALL)
        sm = _re2.search(r'===SAMPLE===\s*\n(.*?)(?=\Z)', code, _re2.DOTALL)
        if dm:
            result["custom_drive_logic"] = dm.group(1).strip()
        if sm:
            result["custom_sample_logic"] = sm.group(1).strip()

    has_llm_response = code and len(code.strip()) > 20
    has_parsed_something = bool(result["custom_drive_logic"] or result["custom_sample_logic"])
    if not has_parsed_something and has_llm_response:
        result["custom_drive_logic"] = generate_fallback_drive(output_names)
        result["custom_sample_logic"] = generate_fallback_sample(output_names, input_names)

    return result


def _call_llm_raw(prompt: str, code: str, errors: str) -> str:
    """底层 LLM 调用。"""
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
        logger.warning(f"LLM call failed: {e}")
    return ""


def generate_fallback_drive(output_names: list) -> str:
    """默认的 drive 代码（无 LLM 时使用）。"""
    lines = ["@(vif.cb);"]
    for n in output_names:
        lines.append(f"vif.cb.{n} <= req.{n};")
    lines.append("@(vif.cb);")
    for n in output_names:
        if any(k in n.lower() for k in ("valid", "strobe", "wen", "ren", "sel", "enable")):
            lines.append(f"vif.cb.{n} <= 1'b0;")
    return "\n".join(lines)


def generate_fallback_sample(output_names: list, input_names: list) -> str:
    """默认的 sample 代码（无 LLM 时使用）。"""
    all_non_clk = [n for n in output_names + input_names
                   if n not in ("clk", "rst", "rst_n", "reset", "presetn")]
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
        for n in all_non_clk:
            lines.append(f"item.{n} = vif.{n};")
    return "\n".join(lines)


def inject_custom_logic_sv(sv_path: Path, drive_logic: str, sample_logic: str, file_type: str):
    """将 LLM 生成的代码注入到已生成的 SV 文件中（避免 Jinja2 二次渲染）。"""
    if not sv_path.exists():
        return
    content = sv_path.read_text(encoding="utf-8", errors="replace")

    if file_type == "driver" and drive_logic:
        default_marker = "// === Default: simple @(cb) drive all output ports ==="
        if default_marker in content:
            before, rest = content.split(default_marker, 1)
            end_markers = ["expected_port.write(exp);", "// Write expected NOW"]
            after = rest
            for em in end_markers:
                if em in rest:
                    _, after = rest.split(em, 1)
                    after = em + after
                    break
            injected = "// === LLM-generated protocol timing ===\n" + drive_logic
            content = before + injected + "\n    \n    " + after

    elif file_type == "monitor" and sample_logic:
        default_marker = "// === Default: sample all ports from interface ==="
        if default_marker in content:
            before, rest = content.split(default_marker, 1)
            if "endfunction" in rest:
                _, after = rest.split("endfunction", 1)
                after = "endfunction" + after
                injected = "// === LLM-generated protocol sampling ===\n" + sample_logic
                content = before + injected + "\n  " + after

    sv_path.write_text(content, encoding="utf-8")
