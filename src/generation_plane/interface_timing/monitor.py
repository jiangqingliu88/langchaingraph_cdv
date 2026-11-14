"""由已验证契约生成可执行 SystemVerilog monitor（候选工件）。

这里编译的是监控器，不是让 LLM 直接写 SVA。每条约束从结构化字段生成，
不会接受任意自然语言作为 HDL 表达式注入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.ir_plane.interface_timing import InterfaceTimingIR
from src.knowledge_plane.interface_protocols.axi_stream import HANDSHAKE

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


@dataclass(frozen=True)
class MonitorArtifact:
    rule_id: str
    path: Path
    module: str
    valid: str
    ready: str
    stable_signals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "path": str(self.path),
            "module": self.module,
            "valid": self.valid,
            "ready": self.ready,
            "stable_signals": list(self.stable_signals),
            "monitor_kind": "procedural_systemverilog",
        }


def _safe(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"非法 SystemVerilog 标识符：{name!r}")
    return name


def _width(ir: InterfaceTimingIR, name: str) -> int:
    signal = next(s for s in ir.signals if s.name == name)
    return max(1, int(signal.width))


def render_monitor(ir: InterfaceTimingIR) -> str:
    if not ir.rules:
        raise ValueError("缺少握手规则，不能生成 monitor")
    rule = ir.rules[0]
    if len(ir.rules) != 1 or rule.kind != HANDSHAKE:
        raise ValueError("当前 monitor 后端只支持单条 valid_ready_stable 规则")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.:-]*", rule.rule_id):
        raise ValueError(f"非法规则 ID：{rule.rule_id!r}")
    valid, ready, clock = map(_safe, (rule.valid, rule.ready, ir.clock.name))
    reset = _safe(ir.clock.reset)
    payload = [name for name in rule.stable_signals if name != rule.valid]
    for name in payload:
        _safe(name)
        _width(ir, name)
    reset_condition = f"{reset} === 1'b1" if ir.clock.reset_active_high else f"{reset} === 1'b0"
    declarations = "\n".join(f"    reg [{_width(ir, name) - 1}:0] prev_{i};" for i, name in enumerate(payload))
    capture = "\n".join(f"            prev_{i} <= {name};" for i, name in enumerate(payload))
    reset_payload = "\n".join(f"            prev_{i} <= '0;" for i in range(len(payload)))
    changed = " || ".join(f"({name} !== prev_{i})" for i, name in enumerate(payload))
    change_guard = f" || ({changed})" if changed else ""
    unknown_ready = f"({ready} !== 1'b0 && {ready} !== 1'b1)"
    unknown_payload = " || ".join(f"(^{name} === 1'bx)" for name in payload)
    payload_check = ""
    if unknown_payload:
        payload_check = (
            f"            if ({valid} === 1'b1 && ({unknown_payload}))\n"
            "                unknown_samples <= unknown_samples + 1;"
        )
    payload_ports = "".join(f"    input wire [{_width(ir, name) - 1}:0] {name},\n" for name in payload)
    return f"""// Generated from {ir.content_hash()}. Only declared identifiers are injected.
module axi_hold_monitor (
    input wire {clock}, input wire {reset},
    input wire {valid}, input wire {ready},
{payload_ports}
    output reg [31:0] violations,
    output reg [31:0] handshakes,
    output reg [31:0] blocked_samples,
    output reg [31:0] unknown_samples
);
    reg prev_valid, prev_ready;
{declarations}

    initial begin
        violations = 0; handshakes = 0; blocked_samples = 0;
        unknown_samples = 0; prev_valid = 0; prev_ready = 0;
    end

    always @(posedge {clock}) begin
        if ({reset_condition}) begin
            violations <= 0; handshakes <= 0; blocked_samples <= 0;
            unknown_samples <= 0; prev_valid <= 0; prev_ready <= 0;
{reset_payload}
        end else begin
            // 上一周期 VALID=1/READY=0 时，本周期仍要保持声明信号稳定。
            if (prev_valid && !prev_ready && (({valid} !== prev_valid){change_guard})) begin
                $display("TIMING_VIOLATION rule={rule.rule_id} cycle=%0t payload_changed_or_valid_dropped", $time);
                violations <= violations + 1;
            end
            if (({valid} !== 1'b0 && {valid} !== 1'b1) || ({valid} === 1'b1 && {unknown_ready})) begin
                unknown_samples <= unknown_samples + 1;
            end
{payload_check}
            if ({valid} === 1'b1 && {ready} === 1'b1)
                handshakes <= handshakes + 1;
            if ({valid} === 1'b1 && {ready} === 1'b0)
                blocked_samples <= blocked_samples + 1;
            prev_valid <= {valid}; prev_ready <= {ready};
{capture}
        end
    end
endmodule
"""


def write_monitor(ir: InterfaceTimingIR, out_dir: str | Path) -> MonitorArtifact:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rule = ir.rules[0]
    module = f"monitor_{re.sub('[^A-Za-z0-9_]', '_', rule.rule_id.lower())}"
    path = out / f"{module}.sv"
    text = render_monitor(ir).replace("module axi_hold_monitor", f"module {module}", 1)
    path.write_text(text, encoding="utf-8", newline="\n")
    return MonitorArtifact(rule.rule_id, path, module, rule.valid, rule.ready, tuple(rule.stable_signals))


__all__ = ["MonitorArtifact", "render_monitor", "write_monitor"]
