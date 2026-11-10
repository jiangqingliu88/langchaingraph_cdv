"""front：不规则 spec → VPlan 项目骨架（bootstrap）。

裸 spec（如 `cmdsched.md`）没有 `docs/specs/*.csv` / `data/contract_matrix` /
`cases/*.yaml`。这里把 front 抽取到的 dplan 契约投影成 VPlan 的**候选输入**，
表头/字段/交叉引用对齐参考项目（`D:\\vplan\\demo\\docs\\specs\\*.csv`）：

    requirements  req_id,spec_section,description,feature_ids,priority,notes
    features      feature_no,feature_id,feature_level,parent_feature_id,
                  feature_l1,feature_l2,feature_l3,description,applicable_topics
    topics        topic,applicability,reason
    contracts     contract_id,category,content,check_method,gate,spec_ref,status
    testpoints    tp_id,feature_id,topic,spec_ref,contract_id,test_point,
                  stimulus,expected,check_method,case_plan,priority,status,notes
    cases         case_id,test_name,batch,contract_ids,covergroups,checks,
                  owner,status,notes

LLM 给了表就原样落盘；缺表才用模块划分做确定性兜底。落盘后调用
`validate_project_inputs` 检查格式与引用闭合，不通过就抛错 —— 坏表不能流入内核。

状态一律从 `assume` / `planned` 起步；没有执行证据，不冒充 active/covered。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

TOPICS = ("接口", "时钟复位", "参数和配置", "数据值域", "数据形状",
          "错误异常", "中间复位", "边界", "流控和反压", "性能长稳")

REQ_FIELDS = ("req_id", "spec_section", "description", "feature_ids",
              "priority", "notes")
FEATURE_FIELDS = ("feature_no", "feature_id", "feature_level",
                  "parent_feature_id", "feature_l1", "feature_l2",
                  "feature_l3", "description", "applicable_topics")
TOPIC_FIELDS = ("topic", "applicability", "reason")
CONTRACT_FIELDS = ("contract_id", "category", "content", "check_method",
                   "gate", "spec_ref", "status")
TESTPOINT_FIELDS = ("tp_id", "feature_id", "topic", "spec_ref",
                    "contract_id", "test_point", "stimulus", "expected",
                    "check_method", "case_plan", "priority", "status",
                    "notes")
CASE_FIELDS = ("case_id", "test_name", "batch", "contract_ids",
               "covergroups", "checks", "owner", "status", "notes")
MATRIX_FIELDS = ("contract_id", "class", "object", "description",
                 "source_ref", "owner", "p_level", "check_method",
                 "check_artifact", "gate", "status", "assumption", "remark")
CLASS_NAMES = ("cfg", "data", "dbg", "exc", "func", "if", "lp", "perf", "res")
_CATEGORY_CLASS = {"接口": "if", "功能": "func", "配置": "cfg", "数据": "data",
                   "异常": "exc", "资源": "res", "性能": "perf",
                   "低功耗": "lp", "可观测": "dbg", "时序": "perf"}


def _write_csv(path: Path, fields, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(fields),
                                extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    for sep in ("|", ",", ";", " ", "\n"):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.splitlines() if x.strip()]


def _join(value: Any) -> str:
    return "|".join(_as_list(value))


def _modules(contract: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = [m for m in (contract.get("modules") or [])
           if isinstance(m, dict) and m.get("name")]
    return out or [{"name": contract.get("design_name") or "dut",
                    "level": "top", "function": contract.get("overview") or "",
                    "interfaces": list(contract.get("interfaces") or [])}]


def _merge_iface_attrs(entry: Dict[str, Any],
                       source: Dict[str, Any] | None) -> Dict[str, Any]:
    """只有名字的端口项 → 用全局接口补位宽/方向/协议（显式非默认值优先）。"""
    if not source:
        return dict(entry)
    merged = dict(source)
    try:
        width = int(entry.get("data_width", 1) or 1)
    except (TypeError, ValueError):
        width = 1
    if width > 1:
        merged["data_width"] = width
    direction = str(entry.get("direction") or "").upper()
    if direction not in ("", "INOUT"):
        merged["direction"] = direction
    if str(entry.get("protocol") or "").strip():
        merged["protocol"] = entry["protocol"]
    merged["name"] = entry["name"]
    return merged


def _top_ifaces(contract: Dict[str, Any], modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """顶层端口列表 —— 用全局 interfaces 补齐 modules 里只有名字的条目。

    `modules[].interfaces` 常是名字数组（LLM 模块表只列端口名）。直接用会让
    VPlan 维度把 74-bit 指令 / 512-bit wdata 记成 1-bit；执行资产（维度/覆盖率
    /激励）都从这里长出来，所以必须回全局 `interfaces` 取位宽/方向/协议。
    """
    name = str((contract.get("architecture") or {}).get("top")
               or contract.get("design_name") or "")
    global_ifaces = [i for i in (contract.get("interfaces") or [])
                     if isinstance(i, dict)]
    full = {str(i.get("name") or "").split("[")[0].strip(): i
            for i in global_ifaces}
    top_module = next(
        (m for m in modules
         if (str(m.get("level") or "").lower() == "top"
             or str(m.get("name")) == name) and m.get("interfaces")), None)
    chosen = ([i for i in top_module["interfaces"] if isinstance(i, dict)]
              if top_module else global_ifaces)
    return [_merge_iface_attrs(item,
                               full.get(str(item.get("name") or "").split("[")[0].strip()))
            for item in chosen]


# ── 表构建：LLM 表优先，缺失才确定性兜底 ──────────────────────

def _fallback_features(top: str, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    root_id = f"F-{top.upper().replace('-', '_')}"
    topics = "|".join(TOPICS)
    rows = [{"feature_no": "1", "feature_id": root_id,
             "feature_level": "root", "parent_feature_id": "-",
             "feature_l1": top, "feature_l2": "-", "feature_l3": "-",
             "description": f"{top} 主功能域", "applicable_topics": topics}]
    for idx, module in enumerate(
            [m for m in modules if str(m.get("level") or "").lower() != "top"],
            start=1):
        mid = str(module["name"])
        rows.append({
            "feature_no": f"1.{idx}", "feature_id": f"F-{mid.upper()}",
            "feature_level": "leaf", "parent_feature_id": root_id,
            "feature_l1": top, "feature_l2": mid, "feature_l3": "-",
            "description": str(module.get("function") or mid),
            "applicable_topics": topics})
    return rows


def _fallback_requirements(modules, features) -> List[Dict[str, Any]]:
    leaves = [f for f in features if f["feature_level"] == "leaf"]
    rows = []
    for idx, (module, feat) in enumerate(
            zip([m for m in modules if str(m.get("level") or "").lower() != "top"],
                leaves), start=1):
        rows.append({"req_id": f"R-SPEC-{idx:02d}",
                     "spec_section": str(module.get("method") or ""),
                     "description": str(module.get("function") or module["name"]),
                     "feature_ids": feat["feature_id"], "priority": "P0",
                     "notes": "bootstrap"})
    return rows


def _fallback_contracts(modules, top: str) -> List[Dict[str, Any]]:
    rows = []
    for idx, module in enumerate(modules, start=1):
        mid = str(module["name"]).upper().replace("-", "_")
        rows.append({
            "contract_id": f"C-FUNC-{mid}-{idx:03d}", "category": "功能",
            "content": str(module.get("function") or module["name"]),
            "check_method": "SCB", "gate": "契约测试",
            "spec_ref": str(module.get("method") or ""),
            "status": "已转 assume", "class": "func", "object": "功能",
            "owner": "dv_func", "p_level": "P0",
            "check_artifact": "spec_func_artifact",
            "assumption": "LLM bootstrap；待人工评审与执行证据",
            "remark": f"bootstrap from {top}"})
    return rows


def _fallback_cases(modules, contracts) -> List[Dict[str, Any]]:
    rows = []
    for idx, (module, contract) in enumerate(zip(modules, contracts), start=1):
        mid = str(module["name"]).upper()
        rows.append({"case_id": f"TC_{mid}_001",
                     "test_name": f"{module['name']}_test", "batch": str(idx),
                     "contract_ids": contract["contract_id"],
                     "covergroups": f"CG_{mid}", "checks": "cfg_scb",
                     "owner": "dv", "status": "planned",
                     "notes": str(module.get("function") or mid)})
    return rows


def _fallback_testpoints(modules, contracts, cases,
                         features) -> List[Dict[str, Any]]:
    root_id = features[0]["feature_id"] if features else ""
    leaf_by_l2 = {str(f.get("feature_l2") or ""): f["feature_id"]
                  for f in features if f.get("feature_level") == "leaf"}
    rows = []
    for module, contract, case in zip(modules, contracts, cases):
        mid = str(module["name"]).upper()
        is_top = str(module.get("level") or "").lower() == "top"
        fid = root_id if is_top else leaf_by_l2.get(str(module["name"]), root_id)
        rows.append({
            "tp_id": f"TP_{mid}_001", "feature_id": fid,
            "topic": "功能", "spec_ref": str(module.get("method") or ""),
            "contract_id": contract["contract_id"],
            "test_point": str(module.get("function") or mid),
            "stimulus": " | ".join(str(x) for x in
                                   (module.get("combinational") or [])),
            "expected": " | ".join(str(x) for x in
                                   (module.get("sequential") or [])),
            "check_method": "SCB", "case_plan": case["case_id"],
            "priority": "P0", "status": "planned", "notes": "bootstrap"})
    return rows


def _default_topics() -> List[Dict[str, Any]]:
    return [{"topic": t, "applicability": "applicable",
             "reason": "bootstrap from spec"} for t in TOPICS]


def _has_rows(rows: Any, key: str) -> bool:
    """LLM 表是否可用：必须至少一行且带主键。

    确定性 spec 解析出的 features 只有 name 没有 feature_id —— 这种旧形状
    不能当 VPlan 表用，必须走兜底。
    """
    return any(isinstance(row, dict) and str(row.get(key) or "").strip()
               for row in (rows if isinstance(rows, list) else []))


def _tables(contract: Dict[str, Any], modules,
            top: str) -> Dict[str, List[Dict[str, Any]]]:
    features = (contract.get("features")
                if _has_rows(contract.get("features"), "feature_id")
                else _fallback_features(top, modules))
    contracts = (contract.get("contracts")
                 if _has_rows(contract.get("contracts"), "contract_id")
                 else _fallback_contracts(modules, top))
    cases = (contract.get("cases")
             if _has_rows(contract.get("cases"), "case_id")
             else _fallback_cases(modules, contracts))
    testpoints = (contract.get("testpoints")
                  if _has_rows(contract.get("testpoints"), "tp_id")
                  else _fallback_testpoints(modules, contracts, cases, features))
    requirements = (contract.get("requirements")
                    if _has_rows(contract.get("requirements"), "req_id")
                    else _fallback_requirements(modules, features))
    topics = (contract.get("topics")
              if _has_rows(contract.get("topics"), "topic")
              else _default_topics())
    return {"requirements": requirements, "features": features,
            "topics": topics, "contracts": contracts,
            "testpoints": testpoints, "cases": cases}


def _feature_rows(features) -> List[Dict[str, Any]]:
    return [{f: str(row.get(f) if row.get(f) is not None else "")
             for f in FEATURE_FIELDS} for row in features
            if isinstance(row, dict)]


def _contract_rows(contracts) -> List[Dict[str, Any]]:
    return [{f: str(row.get(f) if row.get(f) is not None else "")
             for f in CONTRACT_FIELDS} for row in contracts
            if isinstance(row, dict)]


def _testpoint_rows(testpoints) -> List[Dict[str, Any]]:
    return [{f: str(row.get(f) if row.get(f) is not None else "")
             for f in TESTPOINT_FIELDS} for row in testpoints
            if isinstance(row, dict)]


def _case_rows(cases) -> List[Dict[str, Any]]:
    rows = []
    for row in cases:
        if not isinstance(row, dict):
            continue
        clean = {f: str(row.get(f) if row.get(f) is not None else "")
                 for f in CASE_FIELDS}
        for key in ("contract_ids", "covergroups", "checks"):
            clean[key] = _join(row.get(key))
        rows.append(clean)
    return rows


def _write_yaml_cases(root: Path, cases: List[Dict[str, Any]]) -> None:
    case_dir = root / "cases"
    case_dir.mkdir(parents=True, exist_ok=True)
    for case in cases:
        (case_dir / f"{case['case_id']}.yaml").write_text(
            yaml.safe_dump({
                "case_id": case["case_id"], "test_name": case["test_name"],
                "batch": case["batch"], "title": case["notes"],
                "contract_refs": _as_list(case["contract_ids"]),
                "covergroups": _as_list(case["covergroups"]),
                "constraints": []}, allow_unicode=True, sort_keys=False),
            encoding="utf-8")


# ── 接口契约分组 ──────────────────────────────────────────────
#: 端口协议 → interface 分组（与 UVM 的 agent 分组同一口径，见 verify 的
#: `_interface_protocol`）。docs/specs 里也按这个分组给契约，否则后面
#: 契约/TP/case/UVM 各用一套名字，对不上账。
IF_GROUP_FIELDS = ("interface_group", "protocol", "port_count", "ports",
                   "contract_ids", "check_method", "status")
#: 逐端口展开：顶层 + 各子模块；含描述与位域。
IF_PORT_FIELDS = ("scope", "module", "level", "interface_group", "protocol",
                  "port_name", "width", "direction", "description",
                  "bit_fields", "contract_ids")
_IF_CONTRACT_GROUP = {
    "C-IF-001": "valid_ready", "C-IF-002": "valid_ready",
    # SPAD ch0/ch1 是 valid-ready 通道（xbr req/rsp），不是 5 个 master 的 config
    "C-IF-003": "valid_ready", "C-IF-004": "valid_ready",
    # master done/释放 是跨 5 个 master 的详细契约，主归属记到 niu（组契约各自覆盖）
    "C-IF-005": "niu", "C-IF-006": "interrupt",
}
_CLOCK_PROTOS = {"clock", "clk"}
_RESET_PROTOS = {"reset", "rst", "rst_n", "reset_n"}


def _group_name(protocol: Any) -> str:
    """协议字段 → 分组名（合法标识符）。"""
    proto = str(protocol or "").strip().lower()
    if proto in _CLOCK_PROTOS:
        return "clock"
    if proto in _RESET_PROTOS:
        return "reset"
    return re.sub(r"[^a-z0-9_]+", "_", proto).strip("_") or "cmd_if"


#: 每个 master 一组接口：config + start + done + 释放（tile/page/rdram rls）。
#: 塞进一个 `config`/`pulse` 会把 5 个模块的启停与释放混在一起，契约评审时
#: 分不清归属，也写不出“这个 master 的 start/done/释放”义务。
_MASTER_MODULES = ("niu", "glsu", "llsu", "vpu", "mpu")


def _group_name(protocol: Any, port_name: Any = "") -> str:
    """协议字段（+ 端口名）→ 分组名：`config` / `pulse` 按 master 归组。

    例：`cmd_niu_dst_base_addr`（config）与 `niu_cmd_inst0_page_rls_vld`
    （pulse）都归到 `niu` —— 一个 master 的接口边界应该同时包含配置、
    启动、完成与资源释放。其余协议保持原样。
    """
    proto = str(protocol or "").strip().lower()
    if proto in _CLOCK_PROTOS:
        return "clock"
    if proto in _RESET_PROTOS:
        return "reset"
    base = re.sub(r"[^a-z0-9_]+", "_", proto).strip("_") or "cmd_if"
    if base in ("config", "pulse"):
        tokens = set(str(port_name or "").split("_"))
        module = next((m for m in _MASTER_MODULES if m in tokens), "")
        if module:
            return module
    return base


def _interface_groups(top_ifaces: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for itf in top_ifaces:
        if not isinstance(itf, dict):
            continue
        group = _group_name(itf.get("protocol"), itf.get("name"))
        if group in ("clock", "reset"):
            continue
        groups.setdefault(group, []).append(itf)
    return groups


def _port_width(port: Dict[str, Any]) -> int:
    try:
        return int(port.get("data_width", 1) or 1)
    except (TypeError, ValueError):
        return 1


def _group_ports_text(ports: List[Dict[str, Any]],
                      limit: Optional[int] = 360) -> str:
    parts = []
    for port in ports:
        name = str(port.get("name") or "").split("[")[0]
        width = _port_width(port)
        parts.append(f"{name}[{width}]" if width > 1 else name)
    text = " ".join(parts)
    if limit is None or limit <= 0:
        return text
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _signal_kind(port_name: str) -> str:
    """master 接口里的信号类别：start / done / release / config。"""
    name = str(port_name or "")
    if "_rls_" in name or name.endswith("_rls_vld"):
        return "release"
    if "done" in name:
        return "done"
    if "start" in name:
        return "start"
    return "config"


def _master_contract_content(group: str,
                             ports: List[Dict[str, Any]]) -> str:
    counts = {"start": 0, "done": 0, "release": 0, "config": 0}
    for port in ports:
        counts[_signal_kind(str(port.get("name") or ""))] += 1
    return (
        f"接口组 {group}（master）：{len(ports)} 个端口 —— "
        f"配置 {counts['config']} / 启动 {counts['start']} / "
        f"完成 {counts['done']} / 释放 {counts['release']}。"
        "启动：cmd_<m>_start*；完成：<m>_cmd_inst*_done_vld；"
        "释放：rtile/wtile/page/rdram_rls_*（SPAD tile/page 占用释放）。"
        "同一 master 的 start/done/释放须与配置字段同拍对应、不得丢失；"
        f"端口清单：{_group_ports_text(ports, limit=None)}。")


def _group_contract_rows(groups: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """每个接口分组一条契约（`C-IF-GRP-<GROUP>`）。"""
    rows = []
    for group, ports in sorted(groups.items()):
        if group in _MASTER_MODULES:
            content = _master_contract_content(group, ports)
        else:
            content = (
                f"接口组 {group}：{len(ports)} 个顶层端口"
                f"（{_group_ports_text(ports, limit=None)}）。"
                "协议边界内 valid/ready 同拍握手、握手期间 payload 保持稳定、"
                "输出不得为 X。")
        rows.append({
            "contract_id": f"C-IF-GRP-{group.upper()}",
            "category": "接口",
            "content": content,
            "check_method": "SVA", "gate": "契约测试",
            "spec_ref": "2.1.5", "status": "assume",
            # `_write_matrix` 用它作为 agent 名（contracts.csv 不写这一列）
            "object": group,
        })
    return rows


_BIT_FIELD_RE = re.compile(
    r"(bit\s*\[\s*\d+\s*:\s*\d+\s*\]\s*=\s*[^,，;；)）]+"
    r"|[0-9]+'b[01xXzZ]+=[^,，;；)）]+)")


def _bit_fields(description: Any) -> str:
    """从端口描述里抽位域（`bit[9:3]=func7` / `2'b01=...`）。"""
    found = [m.group(0).strip() for m in
             _BIT_FIELD_RE.finditer(str(description or ""))]
    return "|".join(found)


def _port_row(scope: str, module: str, level: str, group: str,
              port: Dict[str, Any], ids: str) -> Dict[str, str]:
    name = str(port.get("name") or "").split("[")[0]
    description = str(port.get("description") or "")
    return {
        "scope": scope, "module": module, "level": level,
        "interface_group": group, "protocol": group,
        "port_name": name, "width": str(_port_width(port)),
        "direction": str(port.get("direction") or "INPUT").upper(),
        "description": description, "bit_fields": _bit_fields(description),
        "contract_ids": ids,
    }


def _contract_ids_by_group(contract_rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    detail: Dict[str, List[str]] = {}
    for row in contract_rows:
        group = _IF_CONTRACT_GROUP.get(str(row.get("contract_id") or ""))
        if group:
            detail.setdefault(group, []).append(str(row["contract_id"]))
    return detail


def _module_port_rows(modules: Optional[List[Dict[str, Any]]],
                      full: Dict[str, Dict[str, Any]],
                      detail: Dict[str, List[str]]) -> List[Dict[str, str]]:
    """子模块端口 → 逐行（顶层不重复；`modules` 里的 top 跳过）。"""
    rows: List[Dict[str, str]] = []
    for module in modules or []:
        if not isinstance(module, dict) or not module.get("name"):
            continue
        if str(module.get("level") or "").lower() == "top":
            continue
        mname = str(module["name"])
        for itf in module.get("interfaces") or []:
            if not isinstance(itf, dict) or not itf.get("name"):
                continue
            merged = _merge_iface_attrs(
                itf, full.get(str(itf["name"]).split("[")[0].strip()))
            group = _group_name(merged.get("protocol"), merged.get("name"))
            ids = "|".join([f"C-IF-GRP-{group.upper()}"]
                           + detail.get(group, []))
            rows.append(_port_row("module", mname,
                                  str(module.get("level") or "sub"),
                                  group, merged, ids))
    return rows


def _write_interface_ports_table(spec_dir: Path, prefix: str,
                                 groups: Dict[str, List[Dict[str, Any]]],
                                 contract_rows: List[Dict[str, Any]],
                                 modules: Optional[List[Dict[str, Any]]] = None,
                                 contract: Optional[Dict[str, Any]] = None) -> None:
    """`docs/specs/<prefix>_interface_ports.csv`：一个端口一行（含子模块）。

    顶层一行一个端口；子模块再按 `modules[].interfaces` 展开一层 —— 这样
    `dsp_en` / `ins_inst_info` / 各组 master 的输出都能看到归属、位宽与描述，
    而不是只剩顶层那 272 个端口。
    """
    detail = _contract_ids_by_group(contract_rows)
    full = {str(i.get("name") or "").split("[")[0].strip(): i
            for i in (contract or {}).get("interfaces") or []
            if isinstance(i, dict)}
    port_rows = []
    for group, ports in sorted(groups.items()):
        ids = "|".join([f"C-IF-GRP-{group.upper()}"] + detail.get(group, []))
        for port in ports:
            port_rows.append(_port_row("top", prefix, "top", group, port, ids))
    port_rows.extend(_module_port_rows(modules, full, detail))
    _write_csv(spec_dir / f"{prefix}_interface_ports.csv",
               IF_PORT_FIELDS, port_rows)


def _write_matrix(project_root: Path, contracts) -> None:
    by_class: Dict[str, List[Dict[str, Any]]] = {}
    for row in contracts:
        cls = str(row.get("class") or "").strip() or \
            _CATEGORY_CLASS.get(str(row.get("category") or ""), "func")
        cls = cls if cls in CLASS_NAMES else "func"
        by_class.setdefault(cls, []).append({
            "contract_id": row.get("contract_id", ""), "class": cls,
            "object": row.get("object") or row.get("category") or "",
            "description": row.get("content") or row.get("description") or "",
            "source_ref": row.get("spec_ref") or "",
            "owner": row.get("owner") or f"dv_{cls}",
            "p_level": row.get("p_level") or "P1",
            "check_method": row.get("check_method") or "SCB",
            "check_artifact": row.get("check_artifact") or f"spec_{cls}_artifact",
            "gate": "gate_matrix",
            "status": "assume",
            "assumption": row.get("assumption") or "LLM bootstrap；待人工评审",
            "remark": row.get("remark") or "bootstrap from spec"})
    for cls, rows in by_class.items():
        _write_csv(project_root / "data" / "contract_matrix" / f"{cls}.csv",
                   list(MATRIX_FIELDS), rows)


def _write_assets(project_root: Path, contract: Dict[str, Any],
                  modules: List[Dict[str, Any]], top_ifaces: List[Dict[str, Any]],
                  top: str) -> None:
    data = project_root / "data"
    clock = next((i["name"] for i in top_ifaces
                  if "clk" in str(i.get("name"))), "clk")
    reset = next((i["name"] for i in top_ifaces
                  if str(i.get("name")).lower() in ("rst", "rst_n", "reset")), "rst_n")
    _write_csv(data / "execution_meta.csv",
               ["version", "object", "object_cn", "object_code", "description",
                "sampling", "generation"],
               [{"version": "1", "object": top,
                 "object_cn": contract.get("overview") or top,
                 "object_code": top.upper().replace("-", "_"),
                 "description": contract.get("overview") or top,
                 "sampling": yaml.safe_dump({"dut_module": top, "clock": clock,
                                             "reset": reset}, default_flow_style=True).strip(),
                 "generation": yaml.safe_dump({"seed": 12345, "max_cases": 400},
                                              default_flow_style=True).strip()}])
    fields = []
    for itf in top_ifaces:
        name = str(itf.get("name") or "")
        if not name or name in (clock, reset):
            continue
        # 一个字段 = 一个维度：维度 id 必须唯一。全部塞进 `D_TOP` 时，
        # 属性测试类按 (维度, 取值) 命名，不同字段会撞成同名 typedef
        # （实测 vlog-2426 multiply defined）。
        dim_id = "D_" + re.sub(r"[^0-9A-Za-z]+", "_", name).strip("_").upper()
        fields.append({"dimension_id": dim_id, "dimension_name": name,
                       "dimension_description": f"顶层接口 {name}",
                       "dimension_sub_objects": "[]",
                       "dimension_stimulus": "{}",
                       "field_name": name, "field_type": "enum",
                       "width": str(itf.get("data_width") or 1),
                       "values": '["0","1"]', "boundary": "[]",
                       "cover_bins": '["0","1"]', "cover_illegal": "[]",
                       "description": str(itf.get("description") or name),
                       "sample": "stimulus", "cover_id": f"CP_{name.upper()}",
                       "requirement": "", "realization_kind": "stimulus",
                       "realization_path": "", "realization_sequence": "",
                       "realization_sequences": "{}"})
    _write_csv(data / "dimensions.csv",
               ["dimension_id", "dimension_name", "dimension_description",
                "dimension_sub_objects", "dimension_stimulus", "field_name",
                "field_type", "width", "values", "boundary", "cover_bins",
                "cover_illegal", "description", "sample", "cover_id",
                "requirement", "realization_kind", "realization_path",
                "realization_sequence", "realization_sequences"], fields)
    behaviors = ((contract.get("model_contract") or {}).get("behaviors") or [])
    _write_csv(data / "assertions.csv",
               ["name", "expr", "message", "signals", "tp_bindings"],
               [{"name": b.get("name", ""),
                 "expr": f"({b.get('when')}) |-> ({b.get('expect')})"
                 if b.get("when") and b.get("expect") else "",
                 "message": b.get("expect", ""), "signals": "[]",
                 "tp_bindings": "[]"} for b in behaviors if isinstance(b, dict)])
    _write_csv(data / "scoreboards.csv",
               ["id", "name", "checks", "evidence", "description", "rules"],
               [{"id": f"SB-{top.upper()}", "name": top, "checks": '["CHECK-FUNC"]',
                 "evidence": "auto", "description": "bootstrap scoreboard",
                 "rules": yaml.safe_dump([b.get("name") for b in behaviors
                                          if isinstance(b, dict)]).strip()}])
    _write_csv(data / "sub_objects.csv", ["id", "name", "code"],
               [{"id": f"OBJ-{i:02d}", "name": m["name"],
                 "code": str(m["name"]).upper()[:8]}
                for i, m in enumerate(modules, 1)])
    _write_csv(data / "cross_matrix.csv", ["matrix_key", "payload"], [])
    _write_csv(data / "behavior.csv", ["rows"], [])
    _write_csv(data / "config_space.csv", ["rows"], [])


def bootstrap_project(project_root: str | Path, spec_text: str,
                      contract: Dict[str, Any]) -> Dict[str, Any]:
    """裸 spec + dplan 契约 → VPlan 项目骨架；返回摘要（含校验结果）。"""
    from src.skills.front.vplan.validate import (
        ProjectFormatError, validate_project_inputs)

    root = Path(project_root)
    # 项目目录名是模块的规范名：run 目录、UVM env/test、资产都从
    # `project.module`（= 目录名）派生；LLM 的 design_name 只作候选提示。
    prefix = root.name
    top = str((contract.get("architecture") or {}).get("top")
              or contract.get("design_name") or prefix)
    if top != prefix:
        top = prefix
    modules = _modules(contract)
    top_ifaces = _top_ifaces(contract, modules)
    # docs/specs 的接口契约用**全局** interfaces：`modules[].interfaces` 是
    # LLM 的模块表，可能漏端口（实测 npu_sched 顶层漏了 54 个 per-instance
    # `cmd_creg_*_exce*`，而全局 interfaces 与 spec 328/328 全对得上）。
    all_ifaces = [i for i in (contract.get("interfaces") or [])
                  if isinstance(i, dict)]
    tables = _tables(contract, modules, top)

    spec_dir = root / "docs" / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"{prefix}.md"
    # 按字节原样落盘：hash 必须与文件字节一致（write_text 在 Windows 会把
    # `\n` 翻成 `\r\n`，导致 spec_meta 的 hash 检查立刻漂移）。
    spec_bytes = spec_text.encode("utf-8")
    spec_path.write_bytes(spec_bytes)
    (spec_dir / f"{prefix}_spec_meta.json").write_text(json_dumps({
        "source": f"docs/specs/{prefix}.md",
        "spec_version": "bootstrap",
        "spec_hash": hashlib.sha256(spec_bytes).hexdigest(),
        "plan_version": "0.1.0-bootstrap",
        "note": "LLM bootstrap：契约 assume / TP/case planned，需人工评审",
        # `vplan execute` 的硬门：没人 review 过这些表就不允许往下跑。
        "review_required": True,
    }), encoding="utf-8")
    # dplan 契约 sidecar：本次 run 的 front 直接复用它，不再二次调 LLM ——
    # 否则 bootstrap 与执行期两次抽取结果会不一致（实测 18 vs 328 个接口）。
    (spec_dir / f"{prefix}_dplan.json").write_text(
        json_dumps({**contract, "design_name": top}),
        encoding="utf-8")
    # JSON 是机器 sidecar；人读/人工修正走 CSV（审阅门覆盖 docs/specs）。
    from .dplan_csv import write_dplan_csvs

    write_dplan_csvs(spec_dir, prefix, {**contract, "design_name": top})

    feature_rows = _feature_rows(tables["features"])
    contract_rows = _contract_rows(tables["contracts"])
    # 接口契约按协议分组：老契约挂到主分组，再补每组一条 `C-IF-GRP-*`。
    # 用全局 interfaces（不是模块表）→ 契约/端口表不丢 spec 里的端口。
    interface_groups = _interface_groups(all_ifaces or top_ifaces)
    for row in contract_rows:
        group = _IF_CONTRACT_GROUP.get(str(row.get("contract_id") or ""))
        if group:
            row["object"] = group
    contract_rows.extend(_group_contract_rows(interface_groups))
    testpoint_rows = _testpoint_rows(tables["testpoints"])
    case_rows = _case_rows(tables["cases"])
    requirement_rows = [{f: str(row.get(f) if row.get(f) is not None else "")
                         for f in REQ_FIELDS}
                        for row in tables["requirements"] if isinstance(row, dict)]
    topic_rows = [{f: str(row.get(f) if row.get(f) is not None else "")
                   for f in TOPIC_FIELDS}
                  for row in tables["topics"] if isinstance(row, dict)]

    _write_csv(spec_dir / f"{prefix}_requirements.csv", REQ_FIELDS,
               requirement_rows)
    _write_csv(spec_dir / f"{prefix}_features.csv", FEATURE_FIELDS,
               feature_rows)
    _write_csv(spec_dir / f"{prefix}_topics.csv", TOPIC_FIELDS, topic_rows)
    _write_csv(spec_dir / f"{prefix}_contracts.csv", CONTRACT_FIELDS,
               contract_rows)
    _write_interface_ports_table(spec_dir, prefix, interface_groups,
                                 contract_rows, modules=modules,
                                 contract=contract)
    _write_csv(spec_dir / f"{prefix}_testpoints.csv", TESTPOINT_FIELDS,
               testpoint_rows)
    _write_csv(spec_dir / f"{prefix}_cases.csv", CASE_FIELDS, case_rows)
    _write_matrix(root, contract_rows)
    _write_yaml_cases(root, case_rows)
    _write_assets(root, contract, modules, top_ifaces, top)

    validation = validate_project_inputs(root)
    if all_ifaces and len(top_ifaces) < len(all_ifaces):
        validation["warnings"].append(
            f"modules[].interfaces 只列了 {len(top_ifaces)} 个顶层端口，"
            f"全局 interfaces 有 {len(all_ifaces)} 个（漏 "
            f"{len(all_ifaces) - len(top_ifaces)} 个）；docs/specs 已按全局补齐，"
            "但 RTL/UVM 仍按模块表生成 —— 需要把漏掉的端口补进顶层模块表。")
    summary = {
        "project": str(root), "prefix": prefix, "modules": len(modules),
        "contracts": len(contract_rows), "interfaces": len(top_ifaces),
        "requirements": len(requirement_rows), "features": len(feature_rows),
        "topics": len(topic_rows), "testpoints": len(testpoint_rows),
        "cases": len(case_rows),
        "dplan": str(spec_dir / f"{prefix}_dplan.json"),
        "validation": validation,
    }
    if not validation["ok"]:
        raise ProjectFormatError(
            "bootstrap 产物格式/引用校验失败：\n- " +
            "\n- ".join(validation["errors"][:20]))
    return summary


def bootstrap_assets(project_root: str | Path, spec_text: str,
                     contract: Dict[str, Any]) -> Dict[str, Any]:
    """给已有 docs/specs 的项目补执行资产（`data/*.csv`）。

    参考项目（`D:\\vplan\\demo`）只有规划表、没有 dimensions/scoreboards 等
    执行资产 —— 直接 execute 会报"缺少执行资产"。这里用同一份 dplan 契约补
    `data/*.csv`，并把契约 sidecar 放在 `data/dplan_contract.json`，**不改
    docs/specs 下的人工表**。
    """
    from src.skills.front.vplan.validate import (
        ProjectFormatError, validate_execution_assets)

    root = Path(project_root)
    top = root.name
    modules = _modules(contract)
    top_ifaces = _top_ifaces(contract, modules)
    _write_assets(root, contract, modules, top_ifaces, top)
    sidecar = root / "data" / "dplan_contract.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json_dumps({**contract, "design_name": top}),
                       encoding="utf-8")
    validation = validate_execution_assets(root)
    if not validation["ok"]:
        raise ProjectFormatError(
            "执行资产格式校验失败：\n- " +
            "\n- ".join(validation["errors"][:20]))
    return {"project": str(root), "interfaces": len(top_ifaces),
            "dimensions": validation["counts"].get("dimensions", 0),
            "dplan": str(sidecar), "validation": validation}


def json_dumps(doc: Dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2) + "\n"


__all__ = ["bootstrap_project"]
