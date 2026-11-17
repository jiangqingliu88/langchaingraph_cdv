"""业务测试点表（xlsx）→ Case IR（CCAT / CASE）。

## 为什么要这一层

`specs/*/data/*.csv` 回答的是"**怎么测/怎么量**"（维度、bin、cross、批次）；
业务 xlsx 回答的是"**该测什么**"（Feature → Sub_Feature → TestName/TestNum）。
两者不是同一条轴：

- 把人写的 feature 层级硬塞进 dimensions，会把"场景"误当成"属性取值"；
- 只用执行资产维度合成 CASE，会得到"12 个维度 CASE"，而不是业务表里的
  25 个 F / 7 个 IF / 7 个 E……的用例身份。

所以这里把 xlsx **投影成 CASE 身份**，维度/覆盖仓/checker **通过绑定表**接上：

    xlsx（what） ──project──► CaseDoc（CCAT/CASE）
                                   │ bindings（dimensions/cells/tests）
                                   ▼
                         执行资产（how）→ TP IR → CELL → EVD

**不自动猜维度**：文本相似度匹配会把"start_id0 先于 start_id1"错绑到
`D_queue`。没给绑定的 CASE 保留 `dimensions=[]`，由门禁报
`CASE_WITHOUT_BINDING`，等人来补 —— 不编一个看起来对的。

## 绑定表（`case_bindings_v1`）

```yaml
schema: case_bindings_v1
bindings:
  NPU_V2-CMDSCHED-IF02:
    dimensions: [D_seq, D_dependency]
    cells: [CELL-D_SEQ-P1]
    tests: [npu_sched_env_d_seq_s0_first_test]
    priority: P1
    owner: 刘江清
```
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .ir_core import (
    SOURCE_XLSX, CaseDoc, CaseIR, CCatIR, case_id_of, ccat_id_of, slug,
)

DEFAULT_ROOT = ccat_id_of("ROOT")

_CAT_LABEL = {
    "CR": "时钟和复位", "IF": "接口协议", "C": "参数化与配置",
    "F": "功能", "BP": "流控和反压", "BO": "形状/内存边界",
    "R": "随机", "E": "错误和异常恢复", "P": "性能常稳",
    "UNKNOWN": "未分类",
}
_UVM_TEST_RE = re.compile(r"^[A-Za-z_]\w*_test$")


def _as_list(value: Any) -> List[Any]:
    if value is None or value == "":
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _dict_list(value: Any) -> List[Dict[str, Any]]:
    return [dict(x) for x in _as_list(value) if isinstance(x, dict)]


def load_bindings(source: Any = None) -> Dict[str, Dict[str, Any]]:
    """`case_bindings_v1` → `{orig_id|case_id: {dimensions, cells, tests, ...}}`。"""
    if not source:
        return {}
    import yaml as _yaml

    if isinstance(source, dict):
        doc = source
    else:
        path = Path(str(source))
        try:
            text = (path.read_text(encoding="utf-8", errors="replace")
                    if path.is_file() else str(source))
            doc = _yaml.safe_load(text) or {}
        except (OSError, ValueError):
            return {}
    raw = doc.get("bindings") if isinstance(doc, dict) else None
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for key, value in raw.items():
        if isinstance(value, dict):
            out[str(key)] = dict(value)
    return out


def _feature_code(tp: Any) -> str:
    """`NPU_V2-CMDSCHED-IF02` → `IF02`；`…-CR01-F` → `CR01_F`。

    **取 `CMDSCHED-` 之后的整段**，不能只取最后一段 —— `CR01-F` 的最后一段
    是功能域标记 `F`，会跟 category `F` 撞车。
    """
    orig = str(getattr(tp, "orig_id", "") or getattr(tp, "tp_id", "") or "")
    head, _, tail = orig.partition("CMDSCHED-")
    base = tail if head else orig
    return slug(base) or slug(getattr(tp, "tp_id", "")) or "TP"


def _first_text(tp: Any, key: str) -> str:
    for row in getattr(tp, "raw_rows", None) or []:
        text = _clean(row.get(key))
        if text:
            return text
    return ""


def _raw_row(tp: Any) -> Dict[str, Any]:
    rows = getattr(tp, "raw_rows", None) or []
    return rows[0] if rows else {}


def _sub_texts(tp: Any) -> List[str]:
    """C/D/E 三列原文（去重保序）；E 只作为描述，不建分类节点。"""
    out: List[str] = []
    for row in getattr(tp, "raw_rows", None) or []:
        for key in ("sub_feature", "sub_sub_feature",
                    "sub_sub_sub_feature"):
            text = _clean(row.get(key))
            if text and text not in out:
                out.append(text)
    return out


def _categories_for(tp: Any, cats: Dict[str, CCatIR]) -> List[str]:
    """Category → Feature → C → D 的分类路径；返回 CASE 要挂的节点。"""
    cat = str(getattr(getattr(tp, "category", None), "value", "") or "UNKNOWN")
    cat_id = ccat_id_of(cat)
    cats.setdefault(cat_id, CCatIR(id=cat_id, name=_CAT_LABEL.get(cat, cat),
                                   parent=DEFAULT_ROOT))
    feature = _feature_code(tp)
    feature_id = ccat_id_of(cat, feature)
    cats.setdefault(feature_id, CCatIR(
        id=feature_id, name=_clean(getattr(tp, "feature_text", "")) or feature,
        parent=cat_id))

    nodes: List[str] = []
    c_text = _first_text(tp, "sub_feature")
    c_id = ccat_id_of(feature, "C", slug(c_text)) if c_text else ""
    if c_id:
        cats.setdefault(c_id, CCatIR(id=c_id, name=c_text, parent=feature_id))
        nodes.append(c_id)
    base_id = c_id or feature_id
    for row in getattr(tp, "raw_rows", None) or []:
        sub = _clean(row.get("sub_sub_feature"))
        if not sub:
            continue
        # **不再套一层 ccat_id_of**：c_id 已经是 `CCAT-…`，再套会变成
        # `CCAT-CCAT-…`。D 直接接在 C/Feature 后面。
        d_id = f"{base_id}-D-{slug(sub)}"
        cats.setdefault(d_id, CCatIR(id=d_id, name=sub, parent=base_id))
        nodes.append(d_id)
    # CASE 挂最具体的一层（category_path 从第一个节点往上走）
    return list(dict.fromkeys(nodes + [feature_id, cat_id]))


def _case_for(tp: Any, cats: Dict[str, CCatIR],
              binding: Dict[str, Any], *, case_id: str = "") -> CaseIR:
    orig = _clean(getattr(tp, "orig_id", "") or getattr(tp, "tp_id", ""))
    test_intent = _clean(getattr(tp, "test_name", ""))
    tests = [test_intent] if _UVM_TEST_RE.match(test_intent) else []
    tests = [str(t) for t in _as_list(binding.get("tests")) if str(t)] or tests
    dims = [str(d) for d in _as_list(binding.get("dimensions")) if str(d)]
    cells = [str(c) for c in _as_list(binding.get("cells")) if str(c)]
    proof = getattr(tp, "provenance", None)
    doc_section = _clean(getattr(proof, "doc_section", ""))
    chapter = _clean(getattr(proof, "chapter", ""))
    # **用 tp_id 而不是 orig_id**：源表允许同一个 feature id 出现多次
    #（BO02-F02 / R02 各 4 行），loader 用 `#2/#3` 区分；用 orig_id 做 CASE
    # 身份会让 4 条用例撞成 1 条。
    return CaseIR(
        id=case_id or case_id_of(getattr(tp, "tp_id", "") or orig),
        name=_clean(getattr(tp, "feature_text", "")) or orig,
        categories=_categories_for(tp, cats),
        feats=[orig] if orig else [],
        tests=tests,
        cells=cells,
        dimensions=dims,
        owner=str(binding.get("owner") or ""),
        priority=str(binding.get("priority") or ""),
        tags=[str(t) for t in _as_list(
            getattr(getattr(tp, "category", None), "value", "")) if str(t)],
        description="；".join(_sub_texts(tp)),
        test_intent=test_intent,
        test_count=getattr(tp, "test_num", None),
        waivers=_dict_list(binding.get("waivers") or binding.get("waiver")),
        doc_section=doc_section,
        chapter=chapter,
        provenance={
            "xlsx_rows": list(getattr(proof, "xlsx_rows", []) or []),
            "doc_section": doc_section, "chapter": chapter,
            "feature_text": _clean(getattr(tp, "feature_text", "")),
        },
        source=SOURCE_XLSX,
    )


def project_from_ontology(onto: Any, *, module: str = "",
                          bindings: Any = None) -> CaseDoc:
    """AIVM Ontology → CaseDoc（一条 xlsx 锚点 TP = 一条 CASE）。"""
    bind = load_bindings(bindings)
    cats: Dict[str, CCatIR] = {
        DEFAULT_ROOT: CCatIR(id=DEFAULT_ROOT, name="根")}
    cases: List[CaseIR] = []
    for tp in getattr(onto, "testpoints", None) or []:
        orig = _clean(getattr(tp, "orig_id", "") or getattr(tp, "tp_id", ""))
        cid = case_id_of(getattr(tp, "tp_id", "") or orig)
        # 绑定优先按 CASE id（源表允许 orig_id 重复：BO02-F02 / R02）
        binding = bind.get(cid) or bind.get(orig) or {}
        case = _case_for(tp, cats, binding, case_id=cid)
        if case.id:
            cases.append(case)
    doc = CaseDoc(
        module=module or _clean(getattr(onto, "module", "")),
        schema="case_ir_v1", source=SOURCE_XLSX,
        categories=list(cats.values()), cases=cases,
        notes=[f"由 xlsx 投影：{len(cases)} 条 CASE（source=xlsx）"
               + (f"；绑定 {len(bind)} 条" if bind else "；未给绑定表")],
    )
    doc.reindex()
    return doc


def bindings_skeleton(doc: CaseDoc) -> Dict[str, Any]:
    """CaseDoc → `case_bindings_v1` **空骨架**（每个 CASE 一条，dimensions/cells 留空）。

    业务表里 `TestName` 多数是 `func_cov监测` 这类意图，不是 UVM 类；维度/覆盖仓
    更不能靠文本猜。骨架的作用是让人**只填映射**，不重新抄一遍用例身份。
    """
    return {
        "schema": "case_bindings_v1",
        "module": doc.module,
        "bindings": {
            case.id: {
                "origin": case.feats[0] if case.feats else case.id,
                "name": case.name,
                "test_intent": case.test_intent,
                "dimensions": list(case.dimensions),
                "cells": list(case.cells),
                "tests": list(case.tests),
                "waivers": [dict(w) for w in case.waivers],
            }
            for case in doc.cases
        },
    }


def project_from_xlsx(path: str | Path, *, module: str = "",
                      bindings: Any = None) -> CaseDoc:
    """xlsx 文件 → CaseDoc（内部复用 `aivm_ir.load_xlsx_to_ontology`）。"""
    from src.runtime_plane.tools.humanview.aivm_ir import load_xlsx_to_ontology

    onto = load_xlsx_to_ontology(str(path))
    return project_from_ontology(onto, module=module, bindings=bindings)


__all__ = [
    "DEFAULT_ROOT", "bindings_skeleton", "load_bindings",
    "project_from_ontology", "project_from_xlsx",
]
