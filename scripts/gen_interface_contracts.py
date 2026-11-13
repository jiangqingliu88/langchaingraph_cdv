"""从顶层接口端口表生成可执行接口契约（断言 / TP / 事实）。

规则（确定性，不调 LLM）：
  · 每个接口组一个 TP_IF_<GROUP>_TIMING，绑定 C-IF-GRP-<GROUP>；
  · 已知值：组内 `*_start` / `*_vld` / `*_done_vld` / `*_rls_vld` /
    `*_rls_idx` / `*_start_inst_id` 复位后不得为 X；
  · 脉冲：`*_start`、`*_done_vld`、`*_rls_vld` 单拍；
  · 配对：`<sig>_start_inst_id` 必须与 `<sig>_start` 同拍合法（0/1）。

生成物：
  · specs/<module>/data/assertions.csv（保留手工 GLSU 行）
  · specs/<module>/docs/specs/<module>_testpoints.csv
  · specs/<module>/data/interface_timing.csv

用法：
  python scripts/gen_interface_contracts.py specs/npu_sched
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

PULSE_SUFFIX = ("_start", "_done_vld", "_rls_vld")
KNOWN_SUFFIX = PULSE_SUFFIX + ("_vld", "_rls_idx", "_start_inst_id",
                               "_wstart", "_rstart")


def _read(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)
        return rows, list(reader.fieldnames or [])


def _write(path: Path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _top_ports(project: Path):
    path = project / "docs" / "specs" / f"{project.name}_interface_ports.csv"
    rows, _ = _read(path)
    return [row for row in rows
            if row.get("scope") == "top" and row.get("module") == project.name]


def _group_contract(ports):
    out = {}
    for row in ports:
        group = str(row.get("interface_group") or "")
        for cid in str(row.get("contract_ids") or "").split("|"):
            cid = cid.strip()
            if group and cid.startswith("C-IF-GRP-"):
                out.setdefault(group, cid)
    return out


def _is_pulse(name: str, direction: str) -> bool:
    """只把**驱动侧的启动脉冲**和 TB 驱动的 done/rls 当脉冲。

    `creg_cmd_perf_start` 是 CSR 配置位（DUT 输入，可保持多拍），不是脉冲；
    按 `*_start` 一刀切会把它误报成"脉冲不满一拍"。
    """
    if direction == "OUTPUT" and name.startswith("cmd_") and name.endswith(
            ("_start", "_wstart", "_rstart")):
        return True
    return name.endswith(("_done_vld", "_rls_vld"))


def _assertions_for(group: str, ports) -> list:
    names = {row["port_name"]: row for row in ports}
    known = sorted(name for name in names
                   if any(name.endswith(sfx) for sfx in KNOWN_SUFFIX))
    pulses = sorted(name for name in names
                    if _is_pulse(name, str(names[name].get("direction") or "")))
    tp = json.dumps([{"tp_id": f"TP_IF_{group.upper()}_TIMING",
                      "role": "primary"}])
    rows = []
    # 逐信号 known：报错时直接点名是哪根线，而不是一个巨大的 concat。
    for name in known:
        rows.append({
            "name": f"if_{group}_{name}_known",
            "expr": f"!$isunknown({name})",
            "message": f"{name} 复位后不得为 X（接口组 {group}）",
            "signals": json.dumps([{
                "name": name, "width": int(names[name].get("width") or 1)}]),
            "tp_bindings": tp,
        })
    for name in pulses:
        rows.append({
            "name": f"if_{group}_{name}_pulse",
            "expr": f"{name} |=> !{name}",
            "message": f"{name} 必须是单拍脉冲（接口组 {group}）",
            "signals": json.dumps([{
                "name": name, "width": int(names[name].get("width") or 1)}]),
            "tp_bindings": tp,
        })
    for name in known:
        if not name.endswith("_start_inst_id"):
            continue
        base = name[: -len("_inst_id")]
        if base not in names:
            continue
        rows.append({
            "name": f"if_{group}_{base}_inst",
            "expr": f"{base} |-> {name} inside {{0, 1}}",
            "message": f"{name} 在 {base} 有效时必须合法（0/1）",
            "signals": json.dumps([
                {"name": base, "width": int(names[base].get("width") or 1)},
                {"name": name, "width": int(names[name].get("width") or 1)}]),
            "tp_bindings": json.dumps([{
                "tp_id": f"TP_IF_{group.upper()}_TIMING", "role": "primary"}]),
        })
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    args = parser.parse_args()
    project = args.project.resolve()
    ports = _top_ports(project)
    contracts = _group_contract(ports)
    groups = defaultdict(list)
    for row in ports:
        groups[str(row.get("interface_group") or "")].append(row)

    # ── assertions.csv：删除旧的 if_<group>_ 行，保留手工行（如 glsu_*）──
    apath = project / "data" / "assertions.csv"
    arows, afields = _read(apath)
    arows = [r for r in arows if not str(r.get("name") or "").startswith("if_")]
    generated = []
    facts = []
    for group, cid in sorted(contracts.items()):
        if group == "glsu":          # GLSU 已有手工可执行行
            continue
        rows = _assertions_for(group, groups[group])
        generated.extend(rows)
        facts.append({
            "contract_id": cid, "port": "*", "role": "DUT/TB",
            "event": "interface", "rule": (
                "start/vld/done/rls 复位后不得为 X；start/done/rls 为单拍脉冲；"
                "start_inst_id 与 start 同拍合法"),
            "source_ref": "2.1.5",
            "check_artifact": f"if_{group}_known / if_{group}_*",
        })
    arows.extend(generated)
    _write(apath, arows, afields)

    # ── testpoints.csv：每个接口组一个 SVA TP ──
    tpath = project / "docs" / "specs" / f"{project.name}_testpoints.csv"
    trows, tfields = _read(tpath)
    have = {str(r.get("tp_id") or "") for r in trows}
    for group, cid in sorted(contracts.items()):
        tp_id = f"TP_IF_{group.upper()}_TIMING"
        if tp_id in have:
            continue
        trows.append({
            "tp_id": tp_id,
            "feature_id": "F-011",
            "topic": "接口",
            "spec_ref": "2.1.5",
            "contract_id": cid,
            "test_point": f"{group} 接口时序与未知值",
            "stimulus": "按接口组协议驱动/采样 start、vld、done、rls",
            "expected": "复位后已知；start/done/rls 单拍；inst_id 合法",
            "check_method": "SVA",
            "case_plan": "",
            "priority": "P1",
            "status": "planned",
            "notes": "由 scripts/gen_interface_contracts.py 确定性生成",
        })
    _write(tpath, trows, tfields)

    # ── 事实表 ──
    fpath = project / "data" / "interface_timing.csv"
    frows, ffields = _read(fpath) if fpath.is_file() else ([], list(facts[0]))
    frows = [r for r in frows
             if not str(r.get("check_artifact") or "").startswith("if_")]
    frows.extend(facts)
    _write(fpath, frows, ffields)

    print(f"接口组 {len(contracts)}；生成断言 {len(generated)} 行；"
          f"TP {len(trows)}；事实 {len(frows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
