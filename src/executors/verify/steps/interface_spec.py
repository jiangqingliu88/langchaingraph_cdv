"""VPlan 顶层契约 → UVM 接口声明（从 `verify/main.py` 拆出，保持行数预算）。

这些函数只做**纯投影**：端口按协议分组、用全局接口补位宽/方向。
它们不访问 run 产物，也不改状态；`verify` 只在 VPlan 项目上调用
`_vplan_uvm_spec()` 把 dplan 的端口表交给 `find_spec_yaml`。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

_PROTOCOL_ALIASES = {
    "clk": "clock", "clock": "clock",
    "rst": "reset", "rst_n": "reset", "reset": "reset", "reset_n": "reset",
}
#: `config` 按 master 再拆：5 个模块的 cmd_*_start/base_addr 混在一个 agent 里
#: 无法分模块驱动/断言（与 docs/specs 的接口契约分组保持同一套名字）。
_CONFIG_MODULES = ("niu", "glsu", "llsu", "vpu", "mpu")


def _interface_protocol(itf: Dict[str, Any]) -> str:
    """接口项 → 合法 SV 标识符形式的协议名（分组键）。

    dplan 的 protocol 是语义边界（config / pulse / interrupt / valid-ready …）。
    **不要把所有端口压成一个 `cmd_if`**：那会把 74-bit 指令、512-bit wdata
    这类互不相干的信号塞进同一个 interface，agent 也无法按边界驱动。
    """
    from src.tools.common.lib.ports import is_clock_port, is_reset_port

    name = str(itf.get("name") or "").strip().lower()
    proto = str(itf.get("protocol") or "").strip().lower()
    if proto in _PROTOCOL_ALIASES:
        return _PROTOCOL_ALIASES[proto]
    if is_clock_port(name):
        return "clock"
    if is_reset_port(name):
        return "reset"
    clean = re.sub(r"[^a-z0-9_]+", "_", proto).strip("_") or "cmd_if"
    # 一个 master 的接口 = config + start + done + 释放；按模块归组，
    # 与 docs/specs 的接口契约分组同一套名字。
    if clean in ("config", "pulse"):
        tokens = set(name.split("_"))
        module = next((m for m in _CONFIG_MODULES if m in tokens), "")
        if module:
            return module
    return clean


def _top_module_interfaces(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """dplan 的 level=top 模块端口（DUT 对外接口）；没有就返回空。"""
    top_name = str((spec.get("architecture") or {}).get("top")
                   or spec.get("design_name") or "")
    for m in spec.get("modules") or []:
        if not isinstance(m, dict):
            continue
        is_top = str(m.get("level") or "").lower() == "top"
        if (is_top or str(m.get("name") or "") == top_name) and m.get("interfaces"):
            return [i for i in m["interfaces"] if isinstance(i, dict)]
    return []


def _merge_interface_attrs(itf: Dict[str, Any],
                           source: Dict[str, Any] | None) -> Dict[str, Any]:
    """按全局接口补齐位宽/方向/协议；顶层显式给出的非默认值优先。

    `modules[].interfaces` 常常只有端口名（1-bit/INOUT/无协议是占位），
    不补的话 74-bit 指令、512-bit wdata 会被写成 1 bit。
    """
    if not source:
        return dict(itf)
    merged = dict(source)
    try:
        width = int(itf.get("data_width", 1) or 1)
    except (TypeError, ValueError):
        width = 1
    if width > 1:
        merged["data_width"] = width
    direction = str(itf.get("direction") or "").upper()
    if direction not in ("", "INOUT"):
        merged["direction"] = direction
    if str(itf.get("protocol") or "").strip():
        merged["protocol"] = itf["protocol"]
    merged["name"] = str(itf.get("name") or "").split("[")[0].strip()
    return merged


def _vplan_uvm_spec(spec: Dict[str, Any], output_dir: Path) -> Dict[str, Any]:
    """VPlan 顶层契约 → UVM 接口声明（协议边界来自 VPlan，不是 LLM 猜）。

    取 dplan 的顶层端口列表，按 `protocol` 分组交给 `find_spec_yaml`
    （`config` / `pulse` / `interrupt` / `valid_ready` … 各成一个 interface），
    不再把所有端口压成一个 `cmd_if`。端口位宽/方向以全局 `interfaces` 为准。
    """
    try:
        from src.layers.l1_infrastructure.layout import find_vplan_root

        if find_vplan_root(None, output_dir) is None:
            return spec
        full = [dict(i) for i in (spec.get("interfaces") or [])
                if isinstance(i, dict) and i.get("name")]
        full_by_name = {str(i["name"]).split("[")[0].strip(): i for i in full}
        ifaces: List[Dict[str, Any]] = []
        for itf in (_top_module_interfaces(spec) or full):
            base = str(itf.get("name") or "").split("[")[0].strip()
            merged = _merge_interface_attrs(itf, full_by_name.get(base))
            merged["protocol"] = _interface_protocol(merged)
            ifaces.append(merged)
        out = dict(spec)
        if ifaces:
            out["interfaces"] = ifaces
        return out
    except Exception:                              # noqa: BLE001 旁路
        return spec


__all__ = [
    "_PROTOCOL_ALIASES", "_CONFIG_MODULES", "_interface_protocol",
    "_top_module_interfaces", "_merge_interface_attrs", "_vplan_uvm_spec",
]
