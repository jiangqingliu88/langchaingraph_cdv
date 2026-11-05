"""Case IR 的加载与**投影**。

两种来源，优先级从高到低：

1. `declared`      —— 模型里写了 `cases:` 段（人设计的分类与用例）
2. `synthesized`   —— 没写时按结构合成：**每个维度一条 CASE**，
                      分类树沿用组织树（`sub_objects`）

合成本身不是错，错的是**假装那是人设计的**：`CaseDoc.source` 与每条
`CaseIR.source` 都会写清楚，视图与门禁据此区分。

## 为什么不做“从测试名反推 CASE”

测试名是执行细节（`npu_sched_env_d_dep_pRAW_test` 由 env 名 + 维度 + 取值拼
出来）。改名、换 env、换生成器都会变，用它当身份等于把身份挂在实现上。
声明式 → 稳定；合成式 → 至少挂在**模型结构**（维度/组织树）上也稳定。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .ir_core import (
    SCHEMA, SOURCE_DECLARED, SOURCE_SYNTHESIZED, SOURCE_XLSX, CaseDoc,
    CaseIR, CCatIR, case_id_of, ccat_id_of, slug,
)

DEFAULT_ROOT = ccat_id_of("ROOT")


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _strs(value: Any) -> List[str]:
    return [str(v).strip() for v in _as_list(value) if str(v).strip()]


def _load_doc(source: Any) -> Dict[str, Any]:
    """YAML/JSON 文本、路径、或已经解析好的 dict → dict。"""
    if isinstance(source, dict):
        return source
    text = ""
    path = Path(str(source))
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
    else:
        text = str(source)
    doc = yaml.safe_load(text) or {}
    if not isinstance(doc, dict):
        raise ValueError("Case IR 必须是一个映射（YAML/JSON object）")
    return doc


# ════════════════════════════════════════════════════════════
# declared：按 `cases:` 段解析
# ════════════════════════════════════════════════════════════

def _parse_categories(raw: Any) -> List[CCatIR]:
    out: List[CCatIR] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append(CCatIR(id=item.strip(), name=item.strip()))
            continue
        if not isinstance(item, dict):
            continue
        cid = str(item.get("id") or "").strip()
        if not cid:
            continue
        out.append(CCatIR(
            id=cid,
            name=str(item.get("name") or "").strip(),
            parent=str(item.get("parent") or "").strip(),
            description=str(item.get("description") or "").strip(),
        ))
    return out


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    return [dict(x) for x in _as_list(value) if isinstance(x, dict)]


def _dict_of(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _source_of(item: Dict[str, Any]) -> str:
    source = str(item.get("source") or "").strip()
    return (source if source in
            (SOURCE_DECLARED, SOURCE_SYNTHESIZED, SOURCE_XLSX)
            else SOURCE_DECLARED)


def _parse_case(item: Any) -> Optional[CaseIR]:
    if not isinstance(item, dict):
        return None
    cid = str(item.get("id") or "").strip()
    if not cid:
        return None
    return CaseIR(
        id=cid,
        name=str(item.get("name") or "").strip(),
        categories=_strs(item.get("category") or item.get("categories")),
        feats=_strs(item.get("feats") or item.get("requirements")),
        tests=_strs(item.get("tests") or item.get("test")),
        cells=_strs(item.get("cells")),
        dimensions=_strs(item.get("dimensions") or item.get("dims")),
        owner=str(item.get("owner") or "").strip(),
        priority=str(item.get("priority") or "").strip(),
        tags=_strs(item.get("tags")),
        description=str(item.get("description") or "").strip(),
        test_intent=str(item.get("test_intent") or "").strip(),
        test_count=item.get("test_count"),
        doc_section=str(item.get("doc_section") or "").strip(),
        chapter=str(item.get("chapter") or "").strip(),
        provenance=_dict_of(item.get("provenance")),
        source=_source_of(item),
        groups=_dict_list(item.get("groups")),
        sva=_dict_list(item.get("sva")),
        scb=_dict_list(item.get("scb")),
        not_applicable=_dict_of(item.get("not_applicable")),
        waivers=_dict_list(item.get("waivers") or item.get("waiver")),
    )


def _parse_cases(raw: Any) -> List[CaseIR]:
    return [c for c in (_parse_case(item) for item in _as_list(raw))
            if c is not None]


def parse_declared(raw: Dict[str, Any], *, module: str = "") -> CaseDoc:
    """`cases:` 段（或其外层文档）→ CaseDoc。"""
    # 三种形状都认：
    #   · 完整文档 `{schemas/categories/cases/notes}`        → 原样
    #   · 外层包一层 `{cases: {categories, cases}}`          → 拆包
    #   · 只有 `{cases: [...]}`                              → 原样（没有分类）
    section = raw
    _doc_keys = ("categories", "schema", "module", "notes")
    if not any(k in raw for k in _doc_keys) and isinstance(raw.get("cases"), dict):
        section = raw["cases"]
    doc = CaseDoc(
        module=module or str(section.get("module") or ""),
        schema=str(section.get("schema") or SCHEMA),
        source=SOURCE_DECLARED,
        categories=_parse_categories(section.get("categories")),
        cases=_parse_cases(section.get("cases")),
        notes=_strs(section.get("notes")),
    )
    doc.reindex()
    return doc


# ════════════════════════════════════════════════════════════
# synthesized：按模型结构合成
# ════════════════════════════════════════════════════════════

def _org_nodes(model: Any) -> List[Any]:
    """拿组织树的全部节点（CaseModel 对象或 dict 都认）。"""
    nodes = getattr(model, "org_root", None)
    if nodes is None and isinstance(model, dict):
        nodes = model.get("sub_objects") or []
    return list(nodes or [])


def _walk(nodes: List[Any], out: List[Any], parent: str = "") -> None:
    for node in nodes:
        out.append((node, parent))
        children = getattr(node, "children", None)
        if children is None and isinstance(node, dict):
            children = node.get("children") or []
        _walk(list(children or []), out, _node_id(node))


def _node_id(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("id") or node.get("code") or "")
    return str(getattr(node, "id", "") or getattr(node, "code", ""))


def _node_name(node: Any) -> str:
    if isinstance(node, dict):
        return str(node.get("name") or "")
    return str(getattr(node, "name", "") or "")


def _dimensions(model: Any) -> List[Any]:
    if isinstance(model, dict):
        return list(model.get("dimensions") or [])
    return list(getattr(model, "dimensions", []) or [])


def _dim_attr(dim: Any, name: str, default: Any = "") -> Any:
    if isinstance(dim, dict):
        return dim.get(name, default)
    return getattr(dim, name, default)


def _safe_id(text: Any) -> str:
    """与 `framework/behavior._safe` 同一口径（非字母数字 → `_`）。"""
    out = "".join(ch if ch.isalnum() else "_" for ch in str(text or ""))
    return out.strip("_") or "NODE"


def _domain_cases(model: Any) -> List[CaseIR]:
    """行为域 / PATH 组也各合成一条 CASE。

    这两类 TP 不走属性维度那条线（`dimension` 分别是 `BEH_<id>` 与 `PATH`），
    不给它们身份的话，行为/PATH 的 TP 会永远 `CASE_MISSING`。
    """
    out: List[CaseIR] = []
    behavior = (model.get("behavior") if isinstance(model, dict)
                else getattr(model, "behavior", None))
    if behavior:
        bid = str((behavior.get("id", "") if isinstance(behavior, dict)
                   else getattr(behavior, "id", "")) or "").strip()
        if bid:
            name = _safe_id(bid)
            dim = name if name.upper().startswith("BEH") else f"BEH_{name}"
            out.append(CaseIR(id=case_id_of(dim), name=f"行为域 {bid}",
                              categories=[DEFAULT_ROOT], dimensions=[dim],
                              description="行为/状态迁移用例（执行后端 P1b 待接）",
                              source=SOURCE_SYNTHESIZED))
    paths = (model.get("path_groups") if isinstance(model, dict)
             else getattr(model, "path_groups", None)) or []
    if paths:
        out.append(CaseIR(id=case_id_of("PATH"), name="指令生命周期路径",
                          categories=[DEFAULT_ROOT], dimensions=["PATH"],
                          description="PATH 组（端到端路径，后端待接）",
                          source=SOURCE_SYNTHESIZED))
    return out


def synthesize(model: Any, *, module: str = "") -> CaseDoc:
    """没声明 `cases:` 时：**一个维度一条 CASE**，分类树沿用组织树。

    这是结构兜底，不是方法学结论 —— 所以整份文档与每条 CASE 都标
    `source: synthesized`，视图里能一眼看出“这批用例还没有人来设计分类”。
    """
    cats: Dict[str, CCatIR] = {DEFAULT_ROOT: CCatIR(id=DEFAULT_ROOT, name="根")}
    flat: List[Any] = []
    _walk(_org_nodes(model), flat)
    node_category: Dict[str, str] = {}
    for node, parent in flat:
        nid = _node_id(node)
        if not nid:
            continue
        cid = ccat_id_of(nid)
        parent_id = ccat_id_of(parent) if parent else DEFAULT_ROOT
        cats.setdefault(cid, CCatIR(id=cid, name=_node_name(node) or nid,
                                    parent=parent_id if parent_id in cats
                                    or parent_id == DEFAULT_ROOT else DEFAULT_ROOT))
        node_category[nid] = cid

    cases: List[CaseIR] = list(_domain_cases(model))
    for dim in _dimensions(model):
        key = str(_dim_attr(dim, "id") or _dim_attr(dim, "key") or "").strip()
        if not key:
            continue
        subs = _strs(_dim_attr(dim, "sub_objects"))
        category = node_category.get(subs[0]) if subs else DEFAULT_ROOT
        cases.append(CaseIR(
            id=case_id_of(key),
            name=str(_dim_attr(dim, "name") or key),
            categories=[category or DEFAULT_ROOT],
            dimensions=[key],
            priority=str(_dim_attr(dim, "priority") or ""),
            description=str(_dim_attr(dim, "description") or ""),
            source=SOURCE_SYNTHESIZED,
        ))
    doc = CaseDoc(
        module=module or str(getattr(model, "object", "") or ""),
        source=SOURCE_SYNTHESIZED,
        categories=list(cats.values()),
        cases=cases,
        notes=["模型没有 `cases:` 段 —— 按维度合成 CASE（source=synthesized）"],
    )
    doc.reindex()
    return doc


# ════════════════════════════════════════════════════════════
# 入口
# ════════════════════════════════════════════════════════════

def _resolve_path(raw: str, base: str = "") -> Path:
    """模型里写的路径 → 可读文件：绝对 → cwd → 模型目录。"""
    p = Path(raw)
    if p.is_absolute():
        return p
    candidates = [Path.cwd() / p]
    if base:
        candidates += [Path(base).parent / p, Path(base) / p]
    for cand in candidates:
        if cand.is_file():
            return cand
    return p


def project_from_casemodel(model: Any, *, module: str = "",
                           synthesize_missing: bool = True) -> CaseDoc:
    """case 模型（对象或原始 dict）→ CaseDoc。

    **业务来源优先**：模型声明 `case_source.xlsx` 时，CASE/CCAT 来自
    人写的测试点表（xlsx + case_bindings），**不是**按维度合成。xlsx 读不了
    就返回空文档 + note（让 `CASE_MISSING` 门禁响），不悄悄退回合成。

    `synthesize_missing=False` 时没声明就返回空文档 —— 给“只认人设计用例”
    的场景用（例如统计声明率）。
    """
    source = (model.get("case_source") if isinstance(model, dict)
              else getattr(model, "case_source", None)) or {}
    if isinstance(source, dict) and source.get("xlsx"):
        base = str(model.get("source") or "") if isinstance(model, dict) \
            else str(getattr(model, "source", "") or "")
        xlsx = _resolve_path(str(source["xlsx"]), base)
        bindings = source.get("bindings") or ""
        try:
            from .xlsx_projection import project_from_xlsx

            return project_from_xlsx(
                xlsx, module=module or str(source.get("module") or ""),
                bindings=_resolve_path(str(bindings), base) if bindings else None)
        except Exception as exc:                   # noqa: BLE001 身份层不挡生成
            return CaseDoc(module=module, source=SOURCE_DECLARED,
                           notes=[f"case_source.xlsx 读取失败：{exc}"])
    raw_cases = (model.get("cases") if isinstance(model, dict)
                 else getattr(model, "cases_doc", None))
    if raw_cases:
        return parse_declared(raw_cases if isinstance(raw_cases, dict)
                              else {"cases": raw_cases}, module=module)
    if not synthesize_missing:
        return CaseDoc(module=module or str(getattr(model, "object", "") or ""))
    return synthesize(model, module=module)


def load_case_ir(source: Any, *, module: str = "",
                 synthesize_missing: bool = True) -> CaseDoc:
    """YAML/JSON 文本、路径或 dict → CaseDoc。

    文档里出现 `cases:` 键 → 按声明解析；否则当作 case 模型来投影。
    """
    doc = _load_doc(source)
    if "cases" in doc:
        return parse_declared(doc, module=module or str(doc.get("object") or ""))
    return project_from_casemodel(doc, module=module,
                                  synthesize_missing=synthesize_missing)


__all__ = [
    "DEFAULT_ROOT", "load_case_ir", "parse_declared", "project_from_casemodel",
    "slug", "synthesize",
]
