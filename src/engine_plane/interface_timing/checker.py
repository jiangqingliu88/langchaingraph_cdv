"""时序 IR 与真实 RTL/来源的确定性绑定检查。未证明的绑定不得通过。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.mental_ir_plane.interface_timing import InterfaceTimingIR, source_hash
from src.knowledge_plane.interface_protocols.axi_stream import (
    HANDSHAKE,
    handshake_requirements,
)


@dataclass
class TimingBindingReport:
    status: str
    issues: list[dict[str, Any]]
    ir_hash: str
    binding_count: int
    scope: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "interface_binding_v1",
            "status": self.status,
            "issues": self.issues,
            "ir_hash": self.ir_hash,
            "binding_count": self.binding_count,
            "scope": self.scope,
        }


def _issue(code: str, message: str, severity: str = "INCOMPLETE") -> dict[str, str]:
    return {"code": code, "message": message, "severity": severity}


def check_anchor(anchor: Any, source_root: Path) -> list[dict[str, str]]:
    if anchor is None:
        return [_issue("missing_source_anchor", "规则缺少原文锚点")]
    errors: list[dict[str, str]] = []
    path = Path(anchor.locator)
    if not path.is_absolute():
        path = source_root / path
    try:
        path = path.resolve()
        path.relative_to(source_root.resolve())
    except (OSError, ValueError):
        return [_issue("anchor_outside_project", f"来源越过项目目录：{path}")]
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeError) as exc:
        return [_issue("source_unreadable", f"无法读取来源：{exc}")]
    if source_hash(path) != anchor.document_sha256:
        errors.append(_issue("stale_source_anchor", "来源文件已变化，原锚点不能继续生效"))
    if anchor.line_start < 1 or anchor.line_end < anchor.line_start:
        errors.append(_issue("invalid_anchor_lines", "来源行号不合法"))
        return errors
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    excerpt = "\n".join(lines[anchor.line_start - 1 : anchor.line_end]).strip()
    if excerpt != anchor.quote.strip():
        errors.append(_issue("anchor_mismatch", "原文字段与声明的 quote/行号不一致，不能用模型自述代替证据"))
    return errors


def _protocol_issues(ir: InterfaceTimingIR) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if not ir.interface_id or not ir.interface_group:
        issues.append(_issue("missing_interface_identity", "缺少接口名或 interface_group"))
    if ir.protocol != "axi4_stream":
        issues.append(_issue("unsupported_protocol", f"当前只能实证 axi4_stream 的最小握手子集：{ir.protocol}"))
    if ir.status != "CONFIRMED":
        issues.append(_issue("unconfirmed_interface", "候选接口声明尚未获得确认"))
    issues.extend(_issue("protocol_requirement_missing", reason) for reason in handshake_requirements(ir))
    issues.extend(_issue("unknown_semantics", reason) for reason in ir.unknowns)
    return issues


def _signal_issues(ir: InterfaceTimingIR, ports: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen: set[str] = set()
    for signal in ir.signals:
        if not signal.name or signal.name in seen:
            issues.append(_issue("invalid_signal_identity", f"信号名缺失或重复：{signal.name!r}"))
        seen.add(signal.name)
        if signal.name not in ports:
            issues.append(_issue("missing_rtl_binding", f"RTL 中找不到信号 {signal.name}，不能靠端口名猜测"))
        if signal.width <= 0:
            issues.append(_issue("invalid_signal_width", f"{signal.name} 位宽无效"))
        if signal.role in ("VALID", "READY") and signal.width != 1:
            issues.append(_issue("invalid_control_width", f"{signal.name} 必须是单比特握手信号"))
        actual_range = str((ports.get(signal.name) or {}).get("range") or "")
        allowed = (f"[{signal.width - 1}:0]", f"[0:{signal.width - 1}]")
        if signal.width == 1:
            allowed = ("", *allowed)
        if actual_range not in allowed:
            issues.append(_issue("rtl_width_unknown", f"{signal.name} 的 RTL 位宽与契约不一致"))
        if signal.binding_status != "CONFIRMED":
            issues.append(_issue("unconfirmed_signal_binding", f"{signal.role}={signal.name} 尚未确认"))
        if signal.protocol != "valid_ready":
            issues.append(_issue("protocol_mismatch", f"{signal.name} 的 port.protocol={signal.protocol}"))
    return issues


def _direction_issues(ir: InterfaceTimingIR, ports: dict[str, Any]) -> list[dict[str, str]]:
    """本最小闭环特指单个 master 输出接口，不能由名字脑补方向。"""
    issues: list[dict[str, str]] = []
    expected = {"VALID": "output", "READY": "input", "DATA": "output"}
    for role in {signal.role for signal in ir.signals}:
        if sum(signal.role == role for signal in ir.signals) != 1:
            issues.append(_issue("unsupported_signal_roles", f"本最小闭环要求每个角色恰好一个绑定：{role}"))
        if role not in expected:
            issues.append(_issue("unsupported_signal_role", f"角色 {role} 尚未有后端证据，不能当作已支持"))
    for signal in ir.signals:
        direction = str((ports.get(signal.name) or {}).get("direction") or "").lower()
        if direction and direction != expected.get(signal.role):
            issues.append(
                _issue(
                    "signal_direction_conflict",
                    f"{signal.name} 方向为 {direction}，本闭环期望 {expected.get(signal.role)}",
                    severity="CONFLICT",
                )
            )
    reset_direction = str((ports.get(ir.clock.reset) or {}).get("direction") or "").lower()
    if reset_direction and reset_direction != "input":
        issues.append(_issue("reset_direction_conflict", "复位必须绑定实际输入", severity="CONFLICT"))
    return issues


def _clock_issues(ir: InterfaceTimingIR, ports: dict[str, Any]) -> list[dict[str, str]]:
    clock = ir.clock
    issues: list[dict[str, str]] = []
    if len({rule.rule_id for rule in ir.rules}) != len(ir.rules):
        issues.append(_issue("duplicate_rule_id", "rule_id 必须唯一"))
    if isinstance(clock.period_ps, bool) or clock.period_ps <= 0:
        issues.append(_issue("invalid_clock_period", "时钟周期必须为正整数皮秒"))
    if clock.edge != "posedge":
        issues.append(_issue("unsupported_clock_edge", "当前最小 monitor 只支持 posedge"))
    if clock.reset not in ports:
        issues.append(_issue("missing_reset_binding", f"RTL 中找不到复位 {clock.reset}"))
    if not isinstance(clock.reset_active_high, bool):
        issues.append(_issue("invalid_reset_polarity", "复位极性不能使用默认值代替确认"))
    return issues


def _endpoint_issues(ir: InterfaceTimingIR, rule: Any, ports: dict[str, Any]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    valid = next((s for s in ir.signals if s.role == "VALID"), None)
    if valid and valid.name not in rule.stable_signals:
        issues.append(_issue("incomplete_stability_set", "稳定信号集合必须包含 VALID"))
    for signal in (s for s in ir.signals if s.role == "DATA"):
        if signal.name not in rule.stable_signals:
            issues.append(_issue("incomplete_stability_set", f"稳定信号集合未包含 {signal.name}"))
    if rule.valid == rule.ready:
        issues.append(_issue("invalid_endpoints", "VALID 和 READY 不能绑定同一端口", severity="CONFLICT"))
    endpoints = (rule.valid, rule.ready, *rule.stable_signals)
    missing = [name for name in endpoints if name not in ports]
    if missing:
        issues.append(_issue("missing_rule_port", f"{rule.rule_id} 缺少实际端口：{missing}"))
    unknown = [name for name in endpoints if name not in {s.name for s in ir.signals}]
    if unknown:
        issues.append(_issue("unregistered_rule_port", f"{rule.rule_id} 引用了未注册信号：{unknown}"))
    return issues


def _anchor_semantics(ir: InterfaceTimingIR, rule: Any) -> list[dict[str, str]]:
    if not rule.anchor:
        return []
    issues: list[dict[str, str]] = []
    endpoints = (rule.valid, rule.ready, *rule.stable_signals)
    missing = [name for name in endpoints if name not in rule.anchor.quote]
    if missing:
        issues.append(_issue("anchor_does_not_bind_endpoints", f"原文锚点没有覆盖：{missing}"))
    mismatched = [
        signal.source_id for signal in ir.signals if signal.source_id and signal.source_id != rule.anchor.source_id
    ]
    if mismatched:
        issues.append(_issue("inconsistent_source_identity", "信号与规则引用的来源不是同一份"))
    return issues


def _rule_issues(ir: InterfaceTimingIR, ports: dict[str, Any], source_root: Path) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    for rule in ir.rules:
        if rule.kind != HANDSHAKE:
            issues.append(_issue("unsupported_rule", f"{rule.rule_id}: {rule.kind}"))
        if not rule.rule_id:
            issues.append(_issue("missing_rule_id", "规则必须有稳定且可用于追溯的 ID"))
        if rule.status != "CONFIRMED":
            issues.append(_issue("unconfirmed_rule", f"{rule.rule_id} 尚未确认"))
        issues.extend(_endpoint_issues(ir, rule, ports))
        issues.extend(_anchor_semantics(ir, rule))
        issues.extend(check_anchor(rule.anchor, source_root))
    return issues


def check_temporal_ir(
    ir: InterfaceTimingIR, rtl_ports: list[dict[str, Any]], source_root: str | Path
) -> TimingBindingReport:
    ports = {str(row.get("name")): row for row in rtl_ports}
    issues = _protocol_issues(ir)
    if len(ports) != len(rtl_ports):
        issues.append(_issue("duplicate_rtl_port", "RTL 端口存在重复名称，无法唯一绑定"))
    issues.extend(_signal_issues(ir, ports))
    issues.extend(_direction_issues(ir, ports))
    issues.extend(_clock_issues(ir, ports))
    issues.extend(_rule_issues(ir, ports, Path(source_root)))
    status = (
        "INCOMPLETE"
        if any(row["severity"] == "INCOMPLETE" for row in issues)
        else "CONFLICT"
        if issues
        else "VALIDATED"
    )
    return TimingBindingReport(
        status,
        issues,
        ir.content_hash(),
        len(ir.signals),
        {
            "interface_id": ir.interface_id,
            "protocol": ir.protocol,
            "checks": len(ir.rules),
            "scope": "AXI4-Stream VALID/READY/DATA 稳定性子集",
        },
    )


__all__ = ["TimingBindingReport", "check_anchor", "check_temporal_ir"]
