"""dplan 的 **CSV 人读视图**（JSON 只作机器 sidecar）。

`npu_sched_dplan.json` 是 front/design/model 吃的机器契约，但 300KB JSON 没法
人工审阅。这里把同一份契约落成几张 CSV：

    <prefix>_dplan_interfaces.csv    全局端口 + 各模块端口（方向/位宽/协议/描述/分组）
    <prefix>_dplan_modules.csv       模块划分（function/method/组合/时序/接口名）
    <prefix>_dplan_model_ports.csv   参考模型端口
    <prefix>_dplan_summary.csv       design_name / top / overview 等摘要

**CSV 是审阅与人工修正的入口**：`load_dplan_csvs()` 会覆盖 JSON 里的
`interfaces` / `modules` / `model_contract.ports`。人工改 CSV → review 哈希变化
→ 必须重新审阅，然后执行时用改后的值。
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List

from .extract import _group_name, _merge_iface_attrs, _port_width

IF_FIELDS = ("scope", "module", "level", "name", "direction", "data_width",
             "protocol", "description", "interface_group")
MODULE_FIELDS = ("name", "level", "parent", "method", "function",
                 "interfaces", "combinational", "sequential")
MODEL_PORT_FIELDS = ("name", "direction", "data_width", "protocol",
                     "description")
SUMMARY_FIELDS = ("key", "value")


def _write(path: Path, fields, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields),
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read(path: Path) -> List[Dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    except OSError:
        return []


def _port_of(row: Dict[str, str]) -> Dict[str, Any]:
    return {
        "name": row.get("name") or "",
        "direction": row.get("direction") or "INPUT",
        "data_width": int(row.get("data_width") or 1),
        "protocol": row.get("protocol") or "",
        "description": row.get("description") or "",
    }


def _iface_row(scope: str, module: str, level: str,
               itf: Dict[str, Any]) -> Dict[str, str]:
    return {
        "scope": scope, "module": module, "level": level,
        "name": str(itf.get("name") or "").split("[")[0],
        "direction": str(itf.get("direction") or "INPUT").upper(),
        "data_width": str(_port_width(itf)),
        "protocol": str(itf.get("protocol") or ""),
        "description": str(itf.get("description") or ""),
        "interface_group": _group_name(itf.get("protocol"),
                                       itf.get("name")),
    }


def _interface_rows(contract: Dict[str, Any], top: str) -> List[Dict[str, str]]:
    interfaces = [i for i in (contract.get("interfaces") or [])
                  if isinstance(i, dict)]
    modules = [m for m in (contract.get("modules") or [])
               if isinstance(m, dict)]
    full = {str(i.get("name") or "").split("[")[0].strip(): i
            for i in interfaces}
    rows = [_iface_row("global", top, "global", i) for i in interfaces]
    for module in modules:
        level = str(module.get("level") or "sub")
        name = str(module.get("name") or "")
        for itf in module.get("interfaces") or []:
            if not isinstance(itf, dict) or not itf.get("name"):
                continue
            merged = _merge_iface_attrs(
                itf, full.get(str(itf["name"]).split("[")[0].strip()))
            rows.append(_iface_row("module", name, level, merged))
    return rows


def _module_rows(modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{
        "name": m.get("name"), "level": m.get("level") or "sub",
        "parent": m.get("parent") or "",
        "method": m.get("method") or "",
        "function": m.get("function") or m.get("description") or "",
        "interfaces": "|".join(
            str(i.get("name") or "") for i in m.get("interfaces") or []
            if isinstance(i, dict)),
        "combinational": "|".join(map(str, m.get("combinational") or [])),
        "sequential": "|".join(map(str, m.get("sequential") or [])),
    } for m in modules]


def _model_port_rows(mc: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [{"name": p.get("name"), "direction": p.get("direction") or "",
             "data_width": str(_port_width(p)),
             "protocol": p.get("protocol") or "",
             "description": p.get("description") or ""}
            for p in mc.get("ports") or [] if isinstance(p, dict)]


def _summary_rows(contract: Dict[str, Any], top: str,
                  mc: Dict[str, Any]) -> List[Dict[str, str]]:
    return [{"key": "design_name", "value": contract.get("design_name") or ""},
            {"key": "top", "value": top},
            {"key": "overview", "value": contract.get("overview") or ""},
            {"key": "model_module", "value": mc.get("module") or ""},
            {"key": "model_scoreboard", "value": mc.get("scoreboard") or ""}]


def write_dplan_csvs(spec_dir: Path, prefix: str,
                     contract: Dict[str, Any]) -> Dict[str, str]:
    """把 dplan 落成人读 CSV（JSON 仍然保留，作为 sidecar）。"""
    modules = [m for m in (contract.get("modules") or [])
               if isinstance(m, dict)]
    mc = contract.get("model_contract") or {}
    top = str((contract.get("architecture") or {}).get("top")
              or contract.get("design_name") or prefix)
    _write(spec_dir / f"{prefix}_dplan_interfaces.csv", IF_FIELDS,
           _interface_rows(contract, top))
    _write(spec_dir / f"{prefix}_dplan_modules.csv", MODULE_FIELDS,
           _module_rows(modules))
    _write(spec_dir / f"{prefix}_dplan_model_ports.csv", MODEL_PORT_FIELDS,
           _model_port_rows(mc))
    _write(spec_dir / f"{prefix}_dplan_summary.csv", SUMMARY_FIELDS,
           _summary_rows(contract, top, mc))
    return {"interfaces": str(spec_dir / f"{prefix}_dplan_interfaces.csv"),
            "modules": str(spec_dir / f"{prefix}_dplan_modules.csv"),
            "model_ports": str(spec_dir / f"{prefix}_dplan_model_ports.csv")}


def _load_interface_tables(spec_dir: Path, prefix: str,
                           rows: List[Dict[str, str]]) -> Dict[str, Any]:
    global_rows = [r for r in rows if r.get("scope") == "global"]
    module_rows = [r for r in rows if r.get("scope") == "module"]
    out: Dict[str, Any] = {}
    if global_rows:
        out["interfaces"] = [_port_of(r) for r in global_rows]
    modules = []
    for row in _read(spec_dir / f"{prefix}_dplan_modules.csv"):
        name = str(row.get("name") or "")
        modules.append({
            "name": name, "level": row.get("level") or "sub",
            "parent": row.get("parent") or "",
            "method": row.get("method") or "",
            "function": row.get("function") or "",
            "interfaces": [_port_of(r) for r in module_rows
                           if r.get("module") == name],
            "combinational": [x for x in
                              (row.get("combinational") or "").split("|") if x],
            "sequential": [x for x in
                           (row.get("sequential") or "").split("|") if x],
        })
    if modules:
        out["modules"] = modules
    return out


def load_dplan_summary(spec_dir: Path, prefix: str) -> Dict[str, Any]:
    """`<prefix>_dplan_summary.csv` → `{design_name, top, overview, ...}`。"""
    return {str(row.get("key") or ""): str(row.get("value") or "")
            for row in _read(spec_dir / f"{prefix}_dplan_summary.csv")
            if row.get("key")}


def load_dplan_csvs(spec_dir: Path, prefix: str) -> Dict[str, Any]:
    """CSV → dplan 的 `interfaces / modules / model_contract.ports`（有才返回）。"""
    out: Dict[str, Any] = {}
    ifaces = _read(spec_dir / f"{prefix}_dplan_interfaces.csv")
    if ifaces:
        out.update(_load_interface_tables(spec_dir, prefix, ifaces))
    ports = _read(spec_dir / f"{prefix}_dplan_model_ports.csv")
    if ports:
        out["model_contract"] = {"ports": [_port_of(r) for r in ports]}
    return out


__all__ = ["write_dplan_csvs", "load_dplan_csvs", "load_dplan_summary"]
