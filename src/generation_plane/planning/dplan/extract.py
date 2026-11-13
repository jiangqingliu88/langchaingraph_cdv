"""LLM 解析 spec → **设计契约 + 模型契约**。

确定性正则解析器（`analyze_specification`）只认固定表头/标题；像
`cmdsched.md` 这种纯文本架构文档会返回 `dut / 0 interfaces / 0 features`。
这里用一次 LLM 调用把它抽成机器可读的两份契约：

    design_contract: design_name / interfaces / registers / features
    model_contract:  module / ports / state / behaviors / checks

输出给现有 front/design/model 使用：design 用 interfaces/features 写 RTL，
model 用 interfaces/registers/model_contract 生成参考模型。LLM 不可用或输出
不合法时返回空 dict，调用方退回确定性解析（不假装成功）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

PROMPT_VERSION = "spec-contract-v3"

_IFACE = {
    "type": "object",
    "required": ["name", "data_width", "direction"],
    "properties": {
        "name": {"type": "string"},
        # LLM 常把位宽写成 "1"；先收下，解析后统一转 int。
        "data_width": {"type": ["integer", "string", "null"]},
        "direction": {"type": ["string", "null"]},
        "protocol": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
    },
}
_REG = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "width": {"type": ["integer", "string", "null"]},
        "offset": {"type": ["string", "integer", "null"]},
        "access": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
    },
}
# VPlan 表行格式：字段/顺序对齐 `docs/specs/*.csv` 的参考项目
# （requirements / features / topics / contracts / testpoints / cases）。
_FEATURE = {
    "type": "object",
    "properties": {
        "name": {"type": ["string", "null"]},          # 兼容旧消费者
        "feature_no": {"type": ["string", "integer", "null"]},
        "feature_id": {"type": ["string", "null"]},
        "feature_level": {"type": ["string", "null"]},  # root|branch|leaf
        "parent_feature_id": {"type": ["string", "null"]},
        "feature_l1": {"type": ["string", "null"]},
        "feature_l2": {"type": ["string", "null"]},
        "feature_l3": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "applicable_topics": {"type": ["array", "string", "null"]},
        "priority": {"type": ["string", "null"]},
    },
}
_REQUIREMENT = {
    "type": "object",
    "required": ["req_id"],
    "properties": {
        "req_id": {"type": "string"},
        "spec_section": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "feature_ids": {"type": ["array", "string", "null"]},
        "priority": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
}
_TOPIC = {
    "type": "object",
    "required": ["topic"],
    "properties": {
        "topic": {"type": "string"},
        "applicability": {"type": ["string", "null"]},
        "reason": {"type": ["string", "null"]},
    },
}
_CONTRACT = {
    "type": "object",
    "required": ["contract_id", "content"],
    "properties": {
        "contract_id": {"type": "string"},
        "category": {"type": ["string", "null"]},   # 接口/功能/配置/数据/异常...
        "content": {"type": "string"},
        "check_method": {"type": ["string", "null"]},   # SVA/SCB/Checker
        "gate": {"type": ["string", "null"]},
        "spec_ref": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        # 契约矩阵行（data/contract_matrix/<class>.csv）
        "class": {"type": ["string", "null"]},      # if/func/cfg/data/exc/res...
        "object": {"type": ["string", "null"]},
        "owner": {"type": ["string", "null"]},
        "p_level": {"type": ["string", "null"]},
        "check_artifact": {"type": ["string", "null"]},
        "assumption": {"type": ["string", "null"]},
        "remark": {"type": ["string", "null"]},
    },
}
_TESTPOINT = {
    "type": "object",
    "required": ["tp_id", "test_point"],
    "properties": {
        "tp_id": {"type": "string"},
        "feature_id": {"type": ["string", "null"]},
        "topic": {"type": ["string", "null"]},
        "spec_ref": {"type": ["string", "null"]},
        "contract_id": {"type": ["string", "null"]},
        "test_point": {"type": "string"},
        "stimulus": {"type": ["string", "null"]},
        "expected": {"type": ["string", "null"]},
        "check_method": {"type": ["string", "null"]},
        "case_plan": {"type": ["string", "null"]},
        "priority": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
}
_CASE = {
    "type": "object",
    "required": ["case_id", "test_name"],
    "properties": {
        "case_id": {"type": "string"},
        "test_name": {"type": "string"},
        "batch": {"type": ["string", "integer", "null"]},
        "contract_ids": {"type": ["array", "string", "null"]},
        "covergroups": {"type": ["array", "string", "null"]},
        "checks": {"type": ["array", "string", "null"]},
        "owner": {"type": ["string", "null"]},
        "status": {"type": ["string", "null"]},
        "notes": {"type": ["string", "null"]},
    },
}
_BEHAVIOR = {
    "type": "object",
    "required": ["name"],
    "properties": {
        "name": {"type": "string"},
        "when": {"type": ["string", "null"]},
        "expect": {"type": ["string", "null"]},
        "checks": {"type": "array", "items": {"type": "string"}},
    },
}

_MODULE = {
    "type": "object",
    "required": ["name", "function"],
    "properties": {
        "name": {"type": "string"},
        "level": {"type": ["string", "null"]},
        "parent": {"type": ["string", "null"]},
        "function": {"type": ["string", "null"]},
        "description": {"type": ["string", "null"]},
        "method": {"type": ["string", "null"]},
        "interfaces": {},   # LLM 可能给数组、名字数组或 {"$ref": "#/interfaces"}
        # 组合逻辑 / 时序逻辑分开写：组合用 assign/always_comb，时序用 always_ff
        "combinational": {"type": "array", "items": {}},
        "sequential": {"type": "array", "items": {}},
        "submodules": {"type": "array", "items": {"type": "string"}},
    },
}


SPEC_CONTRACT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["design_name", "interfaces", "registers", "features",
                 "model_contract"],
    "properties": {
        "design_name": {"type": "string"},
        "overview": {"type": "string"},
        "interfaces": {"type": "array", "items": _IFACE},
        "registers": {"type": "array", "items": _REG},
        "features": {"type": "array", "items": _FEATURE},
        # 流水架构 + 模块划分（dplan 的核心：先分模块/接口/功能，再写代码）
        "architecture": {
            "type": "object",
            "properties": {
                "top": {"type": "string"},
                "stages": {"type": "array", "items": {"type": "string"}},
                "method": {"type": "string"},
            },
        },
        "modules": {"type": "array", "items": _MODULE},
        # 模型契约是**附加产物**：结构不完美时不能让整份设计契约一起被
        # schema 拒绝（实测：LLM 把 ports 写成一句说明，design 直接没 RTL）。
        # 这里只要求是 object，字段在 `_normalize` 里逐项容错。
        "model_contract": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "ports": {},
                "state": {},
                "behaviors": {},
                "scoreboard": {"type": "string"},
            },
        },
    },
}


# VPlan 规划表单独一次 LLM 调用：六张表 + 交叉引用，输出量远大于设计契约；
# 和 design/model 契约混在一次调用里会被 max_tokens 截断（实测）。
VPLAN_TABLES_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["features", "requirements", "topics", "contracts",
                 "testpoints", "cases"],
    "properties": {
        "features": {"type": "array", "items": _FEATURE},
        "requirements": {"type": "array", "items": _REQUIREMENT},
        "topics": {"type": "array", "items": _TOPIC},
        "contracts": {"type": "array", "items": _CONTRACT},
        "testpoints": {"type": "array", "items": _TESTPOINT},
        "cases": {"type": "array", "items": _CASE},
    },
}


def _as_int(value: Any, default: int = 1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ifaces(items: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if isinstance(item, str) and item.strip():
            out.append({"name": item.strip(), "data_width": 1,
                        "direction": "INOUT", "protocol": "",
                        "description": ""})
            continue
        if not isinstance(item, dict) or not item.get("name"):
            continue
        clean = dict(item)
        clean["name"] = str(clean["name"])
        clean["data_width"] = _as_int(clean.get("data_width"), 1)
        clean["direction"] = str(clean.get("direction") or "INPUT").upper()
        out.append(clean)
    return out


def _as_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value or "")
    for sep in ("|", ",", ";", " ", "\n"):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.splitlines() if x.strip()]


def _normalize_features(items: Any) -> List[Dict[str, Any]]:
    out = []
    for idx, item in enumerate(items if isinstance(items, list) else [], 1):
        if not isinstance(item, dict):
            continue
        fid = str(item.get("feature_id") or item.get("name") or "").strip()
        if not fid:
            continue
        out.append({
            "feature_no": str(item.get("feature_no") or idx),
            "feature_id": fid,
            "feature_level": str(item.get("feature_level") or "leaf"),
            "parent_feature_id": str(item.get("parent_feature_id") or "-"),
            "feature_l1": str(item.get("feature_l1") or ""),
            "feature_l2": str(item.get("feature_l2") or "-"),
            "feature_l3": str(item.get("feature_l3") or "-"),
            "description": str(item.get("description") or item.get("name") or fid),
            "applicable_topics": "|".join(_as_list(item.get("applicable_topics"))),
            "name": str(item.get("name") or fid),
            "priority": str(item.get("priority") or "P1"),
        })
    return out


def _normalize_requirements(items: Any) -> List[Dict[str, Any]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("req_id"):
            continue
        out.append({
            "req_id": str(item["req_id"]),
            "spec_section": str(item.get("spec_section") or ""),
            "description": str(item.get("description") or ""),
            "feature_ids": "|".join(_as_list(item.get("feature_ids"))),
            "priority": str(item.get("priority") or "P1"),
            "notes": str(item.get("notes") or ""),
        })
    return out


def _normalize_topics(items: Any) -> List[Dict[str, Any]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("topic"):
            continue
        out.append({
            "topic": str(item["topic"]),
            "applicability": str(item.get("applicability") or "applicable"),
            "reason": str(item.get("reason") or ""),
        })
    return out


def _normalize_contracts(items: Any) -> List[Dict[str, Any]]:
    cls_map = {"接口": "if", "功能": "func", "配置": "cfg", "数据": "data",
               "异常": "exc", "资源": "res", "性能": "perf", "低功耗": "lp",
               "可观测": "dbg", "时序": "perf"}
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("contract_id"):
            continue
        category = str(item.get("category") or "功能")
        cls = str(item.get("class") or cls_map.get(category) or "func")
        out.append({
            "contract_id": str(item["contract_id"]),
            "category": category,
            "content": str(item.get("content") or ""),
            "check_method": str(item.get("check_method") or "SCB"),
            "gate": str(item.get("gate") or "契约测试"),
            "spec_ref": str(item.get("spec_ref") or ""),
            "status": str(item.get("status") or "已转 assume"),
            "class": cls,
            "object": str(item.get("object") or category),
            "owner": str(item.get("owner") or f"dv_{cls}"),
            "p_level": str(item.get("p_level") or "P1"),
            "check_artifact": str(item.get("check_artifact")
                                  or f"spec_{cls}_artifact"),
            "assumption": str(item.get("assumption")
                              or "LLM bootstrap；待人工评审与执行证据"),
            "remark": str(item.get("remark") or "bootstrap from spec"),
        })
    return out


def _normalize_testpoints(items: Any) -> List[Dict[str, Any]]:
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("tp_id"):
            continue
        out.append({
            "tp_id": str(item["tp_id"]),
            "feature_id": str(item.get("feature_id") or ""),
            "topic": str(item.get("topic") or "功能"),
            "spec_ref": str(item.get("spec_ref") or ""),
            "contract_id": str(item.get("contract_id") or ""),
            "test_point": str(item.get("test_point") or ""),
            "stimulus": str(item.get("stimulus") or ""),
            "expected": str(item.get("expected") or ""),
            "check_method": str(item.get("check_method") or "SCB"),
            "case_plan": str(item.get("case_plan") or ""),
            "priority": str(item.get("priority") or "P1"),
            "status": str(item.get("status") or "planned"),
            "notes": str(item.get("notes") or ""),
        })
    return out


def _normalize_cases(items: Any) -> List[Dict[str, Any]]:
    out = []
    for idx, item in enumerate(items if isinstance(items, list) else [], 1):
        if not isinstance(item, dict) or not item.get("case_id"):
            continue
        out.append({
            "case_id": str(item["case_id"]),
            "test_name": str(item.get("test_name") or item["case_id"]),
            "batch": str(item.get("batch") or idx),
            "contract_ids": "|".join(_as_list(item.get("contract_ids"))),
            "covergroups": "|".join(_as_list(item.get("covergroups"))),
            "checks": "|".join(_as_list(item.get("checks"))),
            "owner": str(item.get("owner") or "dv"),
            "status": str(item.get("status") or "planned"),
            "notes": str(item.get("notes") or ""),
        })
    return out


def _base_name(name: Any) -> str:
    """接口名去掉 `[N:0]` 位宽后缀（`paddr[7:0]` → `paddr`）。"""
    return str(name or "").split("[")[0].strip()


def _enrich_named_interfaces(items: Any,
                             full_by_name: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把只有名字的接口项按名字补回 data_width/direction/protocol。

    LLM 的 `modules[].interfaces` / `model_contract.ports` 经常只写端口名，
    而全局 `interfaces` 里同一端口是有位宽/方向/协议的。不补的话下游
    （design 写 RTL、verify 写 UVM interface）会把它当成 1-bit `inout` ——
    实测 74-bit 指令、512-bit wdata 全被压成 1 bit，回归全挂。
    """
    out: List[Dict[str, Any]] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        entry = dict(item)
        source = full_by_name.get(_base_name(entry["name"]))
        if source:
            merged = dict(source)
            # 模块里显式写出的非默认值优先；名字/1-bit/INOUT 只是缺省占位。
            if _as_int(entry.get("data_width"), 1) > 1:
                merged["data_width"] = _as_int(entry.get("data_width"), 1)
            direction = str(entry.get("direction") or "").upper()
            if direction not in ("", "INOUT"):
                merged["direction"] = direction
            if str(entry.get("protocol") or "").strip():
                merged["protocol"] = entry["protocol"]
            if str(entry.get("description") or "").strip():
                merged["description"] = entry["description"]
            merged["name"] = entry["name"]
            entry = merged
        out.append(entry)
    return out


def _enrich_contract(doc: Dict[str, Any]) -> Dict[str, Any]:
    """用全局 interfaces 补齐 modules[].interfaces 与 model_contract.ports。"""
    interfaces = [i for i in (doc.get("interfaces") or []) if isinstance(i, dict)]
    full_by_name = {_base_name(i.get("name")): i for i in interfaces
                    if _base_name(i.get("name"))}
    if not full_by_name:
        return doc
    out = dict(doc)
    modules = []
    for module in out.get("modules") or []:
        if not isinstance(module, dict):
            continue
        clean = dict(module)
        raw = clean.get("interfaces") or clean.get("ports") or []
        clean["interfaces"] = _enrich_named_interfaces(raw, full_by_name)
        modules.append(clean)
    if modules:
        out["modules"] = modules
    mc = dict(out.get("model_contract") or {})
    if mc.get("ports"):
        mc["ports"] = _enrich_named_interfaces(mc["ports"], full_by_name)
        out["model_contract"] = mc
    return out


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """LLM 输出容错：位宽字符串转 int，model_contract 字段不是数组就降级。"""
    design = str(doc.get("design_name") or "").strip()
    interfaces = _normalize_ifaces(doc.get("interfaces"))
    registers = []
    for item in doc.get("registers") if isinstance(doc.get("registers"), list) else []:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        clean = dict(item)
        clean["name"] = str(clean["name"])
        clean["width"] = _as_int(clean.get("width"), 8)
        registers.append(clean)
    features = _normalize_features(doc.get("features"))
    raw_modules = doc.get("modules")
    if isinstance(raw_modules, dict):
        raw_modules = list(raw_modules.values())
    modules = []
    for item in (raw_modules if isinstance(raw_modules, list) else []):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        clean = dict(item)
        clean["name"] = str(clean["name"])
        clean["function"] = str(clean.get("function") or clean.get("description") or "")
        clean["level"] = str(clean.get("level") or "sub")
        clean["parent"] = str(clean.get("parent") or "")
        clean["method"] = str(clean.get("method") or "")
        raw_if = clean.get("interfaces") or clean.get("ports")
        if isinstance(raw_if, dict):
            ref = str(raw_if.get("$ref") or "")
            raw_if = interfaces if "interfaces" in ref else []
        clean["interfaces"] = _normalize_ifaces(raw_if)
        clean["combinational"] = [str(x) for x in
                                  (clean.get("combinational") or [])]
        clean["sequential"] = [str(x) for x in (clean.get("sequential") or [])]
        clean["submodules"] = [str(x) for x in (clean.get("submodules") or [])]
        modules.append(clean)
    arch = doc.get("architecture") if isinstance(doc.get("architecture"), dict) else {}
    mc = doc.get("model_contract")
    mc = mc if isinstance(mc, dict) else {}
    ports = mc.get("ports")
    ports = _normalize_ifaces(ports) if isinstance(ports, list) else interfaces
    behaviors = [dict(item) for item in
                 (mc.get("behaviors") if isinstance(mc.get("behaviors"), list) else [])
                 if isinstance(item, dict) and item.get("name")]
    state = [str(s) for s in
             (mc.get("state") if isinstance(mc.get("state"), list) else [])]
    return _enrich_contract({
        "design_name": design,
        "overview": str(doc.get("overview") or ""),
        "interfaces": interfaces,
        "registers": registers,
        "features": features,
        "requirements": _normalize_requirements(doc.get("requirements")),
        "topics": _normalize_topics(doc.get("topics")),
        "contracts": _normalize_contracts(doc.get("contracts")),
        "testpoints": _normalize_testpoints(doc.get("testpoints")),
        "cases": _normalize_cases(doc.get("cases")),
        "architecture": {
            "top": str(arch.get("top") or design),
            "stages": [str(x) for x in (arch.get("stages") or [])],
            "method": str(arch.get("method") or ""),
        },
        "modules": modules,
        "model_contract": {
            "module": str(mc.get("module") or design),
            "ports": ports,
            "state": state,
            "behaviors": behaviors,
            "scoreboard": str(mc.get("scoreboard") or ""),
        },
    })


def extract_contracts(spec_text: str, *, module_hint: str = "",
                      max_chars: int = 60000) -> Dict[str, Any]:
    """调一次 LLM，返回 `{design_name, interfaces, registers, features,
    model_contract, ...}`；失败返回 `{}`。"""
    if not spec_text.strip():
        return {}
    from src.runtime_plane.tools.common.lib.llm_call import call_llm

    prompt = f"""你是 IC 验证架构师。阅读下面的设计规格，输出**机器可读**的
设计契约与模型契约，只输出 JSON，不要解释。

要求：
1. design_name 用英文 snake_case（提示：{module_hint or "按 spec 推断"}）。
2. interfaces：DUT 的端口/接口，name / data_width / direction(INPUT/OUTPUT/INOUT)
   / protocol / description。**只列 spec 明确写出的端口，不编造**。
3. registers：CSR 寄存器表（name / width / offset / access / description）。
   没有就空数组。
4. features：spec 的功能点（name / priority P0/P1/P2 / description）。
5. model_contract：参考模型契约。module 通常与 design_name 同名；
   ports 与 interfaces 对齐；state 是模型内部状态；behaviors 是
   “when 条件 → expect 结果”，checks 用 SVA/checker/scb 等检查名。
6. architecture：流水线架构（top / stages / method）。stages 是流水级名字，
   method 说明流水/状态机/组合并行等实现方法。
7. modules：**先把设计划分成模块**，每个模块写清 name / level(top|sub) /
   parent / function / method / interfaces / combinational / sequential；
   **必须有一个 level=top 的顶层模块**（name=design_name），它的 interfaces
   只能是 DUT 对外端口（不要列内部信号/子模块信号）；子模块 level=sub；
   `combinational` 是纯组合逻辑（assign / always_comb），`sequential` 是
   时序状态（always_ff / 状态机 / 寄存器）；接口只写该模块自己的端口。
8. 所有字段都必须能追溯到 spec；spec 没写的不要补。

设计规格：
{spec_text[:max_chars]}
"""
    try:
        raw = call_llm(
            prompt, "", "",
            output_schema=SPEC_CONTRACT_SCHEMA,
            prompt_version=PROMPT_VERSION,
            output_format="json",
            failure_policy="fallback",
        )
    except Exception as exc:                        # noqa: BLE001 调用方走确定性回退
        logger.warning(f"LLM spec 契约解析失败: {exc}")
        return {}
    if not raw or not str(raw).strip():
        return {}
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning(f"LLM spec 契约不是合法 JSON: {exc}")
        return {}
    if not isinstance(doc, dict):
        return {}
    doc = _normalize(doc)
    # 项目目录名（调用方给的 module_hint）是模块规范名：RTL 顶层 / UVM env /
    # run 目录全从它派生，LLM 自拟的名字只能在没 hint 时使用。
    hint = str(module_hint or "").strip()
    if hint:
        doc["design_name"] = hint
    # 最小校验：至少要有 design_name 和一个可用的端口/feature。
    if not doc.get("design_name"):
        return {}
    if not (doc.get("interfaces") or doc.get("features")):
        return {}
    return doc


PLAN_PROMPT_VERSION = "vplan-tables-v1"
_PLAN_TOPICS = ("接口", "时钟复位", "参数和配置", "数据值域", "数据形状",
                "错误异常", "中间复位", "边界", "流控和反压", "性能长稳")


def extract_plan_tables(spec_text: str, *, module_hint: str = "",
                        max_chars: int = 60000) -> Dict[str, Any]:
    """spec → VPlan 六张规划表（docs/specs/*.csv 的参考格式）。

    单独一次 LLM 调用；失败或全空返回 `{}`（调用方走确定性兜底）。
    """
    if not spec_text.strip():
        return {}
    from src.runtime_plane.tools.common.lib.llm_call import call_llm

    topics = "、".join(_PLAN_TOPICS)
    prompt = f"""你是 IC 验证架构师。把下面的设计规格抽取成 VPlan 规划表，
只输出 JSON，不要解释。模块/设计名提示：{module_hint or "按 spec 推断"}。

严格按下面的表头与语义输出六个数组（字段名必须一致）：

1) features —— 分层功能树（root/branch/leaf）：
   feature_no（1 / 1.1 / 1.1.1）、feature_id（F-XXX）、feature_level
   （root|branch|leaf）、parent_feature_id（root 用 "-"）、feature_l1、
   feature_l2、feature_l3、description、applicable_topics（| 分隔）。
2) requirements：
   req_id（R-SPEC-01）、spec_section、description、feature_ids（| 分隔，
   必须指向 features）、priority（P0/P1/P2）、notes。
3) topics —— 固定这 10 个专题：{topics}：
   topic、applicability（applicable）、reason（本设计为什么适用）。
4) contracts —— 验证契约：
   contract_id（前缀 C-IF- / C-FUNC- / C-CFG- / C-DATA- / C-EXC- /
   C-RES- / C-PERF- / C-LP- / C-DBG-）、category（接口/功能/配置/数据/
   异常/资源/性能/低功耗/可观测）、content、check_method（SVA|SCB|Checker）、
   gate（契约测试）、spec_ref、status（已转 assume）、class（if|func|cfg|
   data|exc|res|perf|lp|dbg）、object、owner、p_level、check_artifact、
   assumption、remark。
5) testpoints：
   tp_id（TP_XXX_001）、feature_id、topic、spec_ref、contract_id、
   test_point、stimulus、expected、check_method、case_plan、priority、
   status（planned）、notes。
6) cases：
   case_id（TC_XXX_001）、test_name、batch、contract_ids（| 分隔）、
   covergroups（| 分隔）、checks（| 分隔）、owner、status（planned）、notes。

硬约束：
- 六张表都不能为空；id 唯一。
- 交叉引用闭合：requirements.feature_ids ⊆ features；
  testpoints.feature_id/contract_id/case_plan 必须已定义；
  cases.contract_ids ⊆ contracts；features.parent_feature_id 必须已定义。
- 所有内容都能追溯到 spec；spec 没写的不要编造。
- 状态只写 assume/planned，不要写 active/covered。

设计规格：
{spec_text[:max_chars]}
"""
    try:
        raw = call_llm(
            prompt, "", "",
            output_schema=VPLAN_TABLES_SCHEMA,
            prompt_version=PLAN_PROMPT_VERSION,
            output_format="json",
            failure_policy="fallback",
        )
    except Exception as exc:                        # noqa: BLE001 调用方兜底
        logger.warning(f"LLM VPlan 表抽取失败: {exc}")
        return {}
    if not raw or not str(raw).strip():
        return {}
    try:
        doc = json.loads(raw)
    except (TypeError, ValueError) as exc:
        logger.warning(f"LLM VPlan 表不是合法 JSON: {exc}")
        return {}
    if not isinstance(doc, dict):
        return {}
    out = {
        "features": _normalize_features(doc.get("features")),
        "requirements": _normalize_requirements(doc.get("requirements")),
        "topics": _normalize_topics(doc.get("topics")),
        "contracts": _normalize_contracts(doc.get("contracts")),
        "testpoints": _normalize_testpoints(doc.get("testpoints")),
        "cases": _normalize_cases(doc.get("cases")),
    }
    return out if any(out.values()) else {}


def merge_contracts(spec: Dict[str, Any], contract: Dict[str, Any]) -> Dict[str, Any]:
    """把 LLM 契约合并进确定性 spec；LLM 有值优先，缺失字段保留原值。"""
    out = dict(spec or {})
    for key in ("design_name", "overview", "interfaces", "registers",
                "features", "requirements", "topics", "contracts",
                "testpoints", "cases", "architecture", "modules",
                "model_contract"):
        value = (contract or {}).get(key)
        if value:
            out[key] = value
    # sidecar 里的 modules[].interfaces 往往只有端口名 —— 复用 prebuilt 契约时
    # 也要按全局 interfaces 补齐，否则设计/验证双方都退化成 1-bit inout。
    return _enrich_contract(out)


__all__ = ["SPEC_CONTRACT_SCHEMA", "extract_contracts", "merge_contracts"]
