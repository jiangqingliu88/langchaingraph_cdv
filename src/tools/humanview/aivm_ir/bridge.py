"""AIVM（xlsx 测试点表）→ casemodel 导入桥（方案 B）。

## 职责分层

    xlsx（该测什么：TP 行 / 覆盖点 / 优先级 / 依据章节）   ← 人评审、diff
        │  import_ontology()
        ▼
    casemodel.yaml（怎么测：维度 / 字段 / 取值 / 交叉仓）  ← 过 JSON Schema 硬门禁
        │
    source_map.json（双向出处 + xlsx/casemodel 双哈希）    ← 防漂移

## 三条纪律

1. **不静默丢格**：绑不上、超过二维、没有 material 的格子进 `dropped`，带原因；
2. **生成的 casemodel 必须过 `run_validate`（0 error）**，否则拒绝写盘；
3. **双哈希**：xlsx 与 casemodel 的 sha256 一起写进 source_map，`verify_import`
   比对 —— 表改了没重新导入，能被查出来。

`bind_cells()` 是本模块的关键一步：`CoverageCell.dim_bindings` 在 AIVM 里一直
空着，没有它，格子只是"一段中文"，拼不出 casemodel 的交叉仓。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "aivm_import_v1"
AXES_SCHEMA = "aivm_axes_v1"
NAME_MAX = 40

_CATEGORY_NAMES = {"CR": "代码规则", "IF": "接口时序", "C": "控制", "F": "功能",
                   "BP": "背压", "BO": "边界", "R": "复位", "E": "错误异常",
                   "P": "性能", "UNKNOWN": "未分类"}

#: sub_object.code 的 schema 要求 `^[A-Z][A-Z0-9]{1,7}$`（至少两个字符）。
_CATEGORY_CODES = {"C": "CTRL", "F": "FUNC", "R": "RST", "E": "ERR", "P": "PERF"}


class AivmImportError(RuntimeError):
    """导入失败（结构问题 / schema 不通过）。"""


# ════════════════════════════════════════════════════════════
# 命名
# ════════════════════════════════════════════════════════════

def _sv_ident(text: Any, fallback: str = "x") -> str:
    """任意文本 → SV 标识符片段（ASCII、小写下划线）。"""
    out = "".join(ch if ch.isascii() and ch.isalnum() else "_" for ch in str(text or ""))
    out = "_".join(part for part in out.split("_") if part).lower()
    return (out or fallback)[:NAME_MAX]


def _unique(name: str, used: set) -> str:
    base = name
    index = 2
    while name in used:
        name = f"{base}_{index}"
        index += 1
    used.add(name)
    return name


def _default_code(module_name: str) -> str:
    raw = "".join(ch for ch in (module_name or "OBJ").upper() if ch.isalnum())
    return raw[:8] or "OBJ"


def _short_tag(tp: Any, index: int) -> str:
    tail = str(tp.orig_id or tp.tp_id or f"tp{index}").split("-")[-1]
    return _sv_ident(tail, f"tp{index}")[:24] or f"tp{index}"


# ════════════════════════════════════════════════════════════
# 1) 绑定：格子文本 → (dim_id, 取值短码)
# ════════════════════════════════════════════════════════════

def _best_value(haystack: str, dim: Any) -> Tuple[Optional[Any], str]:
    """在该维度里找**最长命中**的取值原文；找不到返回 (None, '')。"""
    best = None
    best_len = 0
    ties = 0
    for value in dim.material_values():
        needle = (value.raw_text or value.value or "").strip()
        if not needle or needle not in haystack:
            continue
        if len(needle) > best_len:
            best, best_len, ties = value, len(needle), 1
        elif len(needle) == best_len:
            ties += 1
    if best is None:
        return None, ""
    return best, ("ambiguous" if ties > 1 else "")


def bind_cells(onto: Any) -> Dict[str, Any]:
    """回填 `CoverageCell.dim_bindings`。返回 {cells, bound, unbound, ambiguous}。"""
    stats = {"cells": 0, "bound": 0, "unbound": 0, "ambiguous": 0}
    for tp in onto.testpoints:
        for cell in tp.coverage_cells:
            if not cell.is_cover_bin():
                continue
            stats["cells"] += 1
            bindings: Dict[str, str] = {}
            ambiguous = False
            for dim in tp.dimensions:
                value, flag = _best_value(cell.raw_text, dim)
                if value is not None:
                    bindings[dim.dim_id] = value.value
                ambiguous = ambiguous or flag == "ambiguous"
            cell.dim_bindings = bindings
            if not bindings:
                stats["unbound"] += 1
            else:
                stats["bound"] += 1
                stats["ambiguous"] += 1 if ambiguous else 0
    return stats


# ════════════════════════════════════════════════════════════
# 1.5) 轴声明（sidecar）：给"没有维度建模的 xlsx"补上验证轴
# ════════════════════════════════════════════════════════════

def load_axes(path: str | Path) -> Dict[str, Any]:
    """读轴声明文件（YAML）；结构不对直接报，不猜。"""
    import yaml as _yaml

    try:
        doc = _yaml.safe_load(Path(path).read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        raise AivmImportError(f"轴声明读不了：{exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("tps"), dict):
        raise AivmImportError("轴声明必须是 {tps: {<tp>: {dimensions: [...]}}}")
    return doc


def _axis_entry(axes: Dict[str, Any], tp: Any) -> Optional[Dict[str, Any]]:
    tps = axes.get("tps") or {}
    for key in (tp.orig_id, tp.tp_id):
        if key and key in tps:
            return tps[key]
    tail = str(tp.orig_id or tp.tp_id or "").split("-")[-1]
    return tps.get(tail)


def _axis_values(raw_dim: Dict[str, Any], texts: List[str], tp: Any,
                 dim_id: str, stats: Dict[str, Any]) -> List[Any]:
    """轴取值 → DimensionValue 列表；表里没有的值**记账并丢弃**。"""
    from .ir_core import DimensionValue

    values = []
    for raw_value in raw_dim.get("values") or []:
        if not isinstance(raw_value, dict):
            continue
        text = str(raw_value.get("raw_text") or raw_value.get("value") or "")
        code = str(raw_value.get("value") or _sv_ident(text, "v"))
        if text and not any(text in cell for cell in texts):
            # 表是"该测什么"的真源：轴里多出来的值不能凭空变覆盖点
            stats["unmatched"].append({"tp": tp.orig_id or tp.tp_id,
                                       "dim": dim_id, "raw_text": text})
            continue
        values.append(DimensionValue(value=code, raw_text=text, source_row=0))
    return values


def _axis_dimension(raw_dim: Any, texts: List[str], existing: set,
                    tp: Any, stats: Dict[str, Any]) -> Any:
    from .ir_core import Dimension, DimType

    if not isinstance(raw_dim, dict):
        return None
    dim_id = str(raw_dim.get("id") or raw_dim.get("name") or "").strip()
    if not dim_id or dim_id in existing:
        return None
    values = _axis_values(raw_dim, texts, tp, dim_id, stats)
    if not values:
        return None
    return Dimension(
        dim_id=dim_id, name=str(raw_dim.get("name") or dim_id),
        dim_type=DimType.CATEGORICAL, value_domain=values,
        semantics=str(raw_dim.get("semantics") or ""))


def apply_axes(onto: Any, axes: Dict[str, Any]) -> Dict[str, Any]:
    """把 sidecar 里的轴挂到 TP 上（已存在的 dim_id 不覆盖）。

    `raw_text` 必须能在该 TP 的某个组合格里找到 —— 找不到就记 `unmatched`
    并丢弃该值：宁可说"这条轴没接上"，也不让它悄悄多出覆盖点。
    """
    stats: Dict[str, Any] = {"tps": 0, "dims": 0, "unmatched": []}
    for tp in onto.testpoints:
        entry = _axis_entry(axes, tp)
        if not isinstance(entry, dict):
            continue
        texts = [c.raw_text for c in tp.coverage_cells if c.is_cover_bin()]
        existing = {d.dim_id for d in tp.dimensions}
        added = 0
        for raw_dim in entry.get("dimensions") or []:
            dim = _axis_dimension(raw_dim, texts, existing, tp, stats)
            if dim is None:
                continue
            tp.dimensions.append(dim)
            existing.add(dim.dim_id)
            added += 1
        if added:
            stats["tps"] += 1
            stats["dims"] += added
    return stats


# ════════════════════════════════════════════════════════════
# 2) 映射：Ontology → casemodel dict
# ════════════════════════════════════════════════════════════

def _collect_values(dim: Any) -> List[Tuple[str, str]]:
    """维度取值 → [(原文, 短码)]；短码去重。"""
    used: set = set()
    out: List[Tuple[str, str]] = []
    for value in dim.material_values():
        code = _unique(_sv_ident(value.value or value.raw_text, "v"), used)
        out.append((value.raw_text or value.value, code))
    return out


def _dimension_entry(tp_key: str, dim: Any, leaf_id: str) -> Tuple[Dict[str, Any], str]:
    """AIVM 维度 → casemodel dimension；返回值与字段名（cross 的 when 用）。"""
    field_name = f"{tp_key}_{_sv_ident(dim.dim_id or dim.name, 'dim')}"
    codes = [code for _raw, code in _collect_values(dim)]
    entry = {
        "id": f"D_{tp_key}_{_sv_ident(dim.dim_id or dim.name, 'dim')}",
        "name": dim.name or dim.dim_id,
        "description": dim.semantics or "",
        "sub_objects": [leaf_id],
        "fields": [{
            "name": field_name,
            "type": "enum",
            "values": codes,
            # 一值一仓：保证取值点都有归属（模型级 canary），组合语义另走 cross。
            # 字符串形式的 named bin 与取值点按下标对齐（schema 的 `at` 只收整数）
            "cover_bins": list(codes),
        }],
    }
    return entry, field_name


def _tp_dimensions(tp: Any, tp_key: str, leaf_id: str):
    """→ (维度条目, {raw_dim_id: (完整维度 id, 字段名)})。

    cross 的键与 `when` 必须用**完整 id / 全局唯一字段名** —— 不同 TP 的轴
    都叫 `start_order`，用 raw id 会把它们的仓合进同一个 cross。
    """
    entries: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {}
    for dim in tp.dimensions:
        if not dim.material_values():
            continue
        entry, field_name = _dimension_entry(tp_key, dim, leaf_id)
        entries.append(entry)
        meta[dim.dim_id] = (entry["id"], field_name)
    return entries, meta


def _scenario_dimension(tp: Any, tp_key: str, leaf_id: str,
                        cells: List[Any], bins: Dict[str, Any]) -> Dict[str, Any]:
    """无维度建模时的退化：一个 TP 一条场景维度，一格一仓。"""
    used: set = set()
    values: List[str] = []
    for cell in cells:
        token = _unique(_sv_ident(f"r{cell.source_row}") if cell.source_row
                        else _sv_ident(cell.cell_id, "sc"), used)
        values.append(token)
        bins[token] = _bin_source(tp, cell, "scenario")
    return {
        "id": f"D_{tp_key}_scenario",
        "name": f"{tp.feature_text or tp.orig_id or tp.tp_id}（场景）"[:120],
        "description": "xlsx 未提供维度轴：按格子做场景覆盖（非交叉）",
        "sub_objects": [leaf_id],
        "fields": [{"name": f"{tp_key}_scenario", "type": "enum",
                    "values": values, "cover_bins": list(values)}],
    }


def _value_dimension(tp: Any, tp_key: str, leaf_id: str, kind: str,
                     cells: List[Any], bins: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """配置枚举 / 定向用例 → 一条独立维度：一值一仓（不参与交叉）。"""
    if not cells:
        return None
    used: set = set()
    field_name = _unique(_sv_ident(f"{tp_key}_{kind}", kind), used)
    values: List[str] = []
    cover: List[str] = []
    for cell in cells:
        token = _unique(_sv_ident(cell.raw_text or cell.cell_id, kind), used)
        values.append(token)
        cover.append(token)
        bins[token] = _bin_source(tp, cell, "config_enum" if kind == "cfg"
                                  else "directed_case")
    return {
        "id": f"D_{tp_key}_{kind}",
        "name": f"{tp.feature_text or tp.orig_id or tp.tp_id}（{kind}）"[:120],
        "sub_objects": [leaf_id],
        "fields": [{"name": field_name, "type": "enum", "values": values,
                    "cover_bins": cover}],
    }


def _combo_cells(tp: Any, cells: List[Any], dim_meta: Dict[str, Any],
                 cross_matrix: Dict[str, Any], bins: Dict[str, Any],
                 dropped: List[Dict[str, Any]]) -> int:
    """二维组合格 → cross bin（一格一仓）；其它情况记账不硬造。"""
    used: set = set()
    produced = 0
    for cell in cells:
        bound = [dim for dim in dim_meta if dim in cell.dim_bindings]
        if len(bound) == 1:
            token = _sv_ident(cell.dim_bindings[bound[0]], "v")
            bins.setdefault(token, _bin_source(tp, cell, "single_dim"))
            continue                     # 单维：field 的一值一仓已覆盖
        if len(bound) > 2:
            dropped.append({"tp": tp.orig_id or tp.tp_id, "cell": cell.cell_id,
                            "reason": "n_way_unsupported", "bound": len(bound)})
            continue
        if not bound:
            dropped.append({"tp": tp.orig_id or tp.tp_id, "cell": cell.cell_id,
                            "reason": "unbound"})
            continue
        dim_a, dim_b = bound
        key = f"{dim_meta[dim_a][0]}×{dim_meta[dim_b][0]}"
        decl = cross_matrix.setdefault(
            key, {"level": "required", "cover_id": tp.orig_id or tp.tp_id,
                  "bins": []})
        name = _unique(_sv_ident(f"r{cell.source_row}") if cell.source_row
                       else _sv_ident(cell.cell_id, "bin"), used)
        decl["bins"].append({"name": name, "when": {
            dim_meta[dim_a][1]: cell.dim_bindings[dim_a],
            dim_meta[dim_b][1]: cell.dim_bindings[dim_b]}})
        bins[name] = _bin_source(tp, cell, "cross")
        produced += 1
    return produced


def _bin_source(tp: Any, cell: Any, kind: str) -> Dict[str, Any]:
    return {"orig_id": tp.orig_id or tp.tp_id, "source_row": cell.source_row,
            "doc_section": tp.provenance.doc_section,
            "chapter": tp.provenance.chapter,
            "kind": kind, "raw_text": cell.raw_text,
            "legality": cell.legality}


def _child_code(tag: str) -> str:
    """sub_object.code：`^[A-Z][A-Z0-9]{1,7}$`。"""
    raw = "".join(ch for ch in str(tag or "").upper() if ch.isalnum())
    raw = raw[:8] or "TP"
    if not raw[0].isalpha():
        raw = ("T" + raw)[:8]
    return raw if len(raw) >= 2 else raw + "0"


def _build_sub_objects(onto: Any) -> List[Dict[str, Any]]:
    groups: Dict[str, Dict[str, Any]] = {}
    for index, tp in enumerate(onto.testpoints, start=1):
        cat = tp.category.value
        root = groups.setdefault(cat, {
            "id": f"OBJ-{cat}", "name": _CATEGORY_NAMES.get(cat, cat),
            "code": _CATEGORY_CODES.get(cat, cat),
            "children": []})
        root["children"].append({
            "id": f"OBJ-{cat}-{_short_tag(tp, index)}",
            "name": (tp.feature_text or tp.orig_id or tp.tp_id)[:120],
            "code": _child_code(_short_tag(tp, index)),
        })
    return list(groups.values())


def _theme_entry(tp: Any, tp_key: str, leaf_id: str, dim_ids: List[str],
                 directed: bool) -> Dict[str, Any]:
    entry = {
        "id": f"TH-{tp_key}",
        "name": (tp.feature_text or tp.orig_id or tp.tp_id)[:120],
        "priority": "P0" if getattr(tp.status, "value", "") == "confirmed" else "P1",
        "dimensions": list(dim_ids),
        "applies_to": [leaf_id],
        "method": "D" if directed else "G",
        "checks": list(tp.checks) or ["CHECK-FUNC"],
    }
    if directed and tp.test_name:
        entry["test"] = str(tp.test_name)
    if isinstance(tp.test_num, int) and tp.test_num > 0:
        entry["repeat"] = tp.test_num
    return entry


def to_casemodel(onto: Any, *, module_name: str,
                 object_code: Optional[str] = None) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Ontology → (casemodel dict, source_map dict)。**不写盘、不校验**。"""
    code = object_code or _default_code(module_name)
    dimensions: List[Dict[str, Any]] = []
    themes: List[Dict[str, Any]] = []
    cross_matrix: Dict[str, Any] = {}
    bins: Dict[str, Any] = {}
    dropped: List[Dict[str, Any]] = []

    for index, tp in enumerate(onto.testpoints, start=1):
        tp_key = _short_tag(tp, index)
        leaf_id = f"OBJ-{tp.category.value}-{tp_key}"
        dim_entries, dim_meta = _tp_dimensions(tp, tp_key, leaf_id)

        combos = [c for c in tp.coverage_cells if c.is_cover_bin()]
        cfgs = [c for c in tp.coverage_cells if c.is_config_enum()]
        cases = [c for c in tp.coverage_cells if c.is_directed_case()]
        if dim_meta:
            _combo_cells(tp, combos, dim_meta, cross_matrix, bins, dropped)
        elif combos:
            # xlsx loader 不建维度 → 没有可交叉的轴。退化成一个"场景"维度：
            # 一格一仓，保留"一个格子 = 一个覆盖点"，但**不冒充交叉覆盖**。
            scenario = _scenario_dimension(tp, tp_key, leaf_id, combos, bins)
            dim_entries.append(scenario)
        cfg_dim = _value_dimension(tp, tp_key, leaf_id, "cfg", cfgs, bins)
        case_dim = _value_dimension(tp, tp_key, leaf_id, "case", cases, bins)
        for extra in (cfg_dim, case_dim):
            if extra is not None:
                dim_entries.append(extra)

        dim_ids = [entry["id"] for entry in dim_entries]
        if not dim_ids:
            dropped.append({"tp": tp.orig_id or tp.tp_id,
                            "reason": "no_material_cells"})
            continue
        dimensions.extend(dim_entries)
        directed = bool(cases) or (tp.directed and bool(tp.test_name))
        themes.append(_theme_entry(tp, tp_key, leaf_id, dim_ids, directed))

    model: Dict[str, Any] = {
        "version": "1",
        "object": module_name,
        "object_code": code,
        "description": f"由 AIVM xlsx 导入（{onto.xlsx_rev or ''}）",
        "sub_objects": _build_sub_objects(onto),
        "themes": themes,
        "dimensions": dimensions,
    }
    if cross_matrix:
        model["cross_matrix"] = cross_matrix
    source_map = {"schema": SCHEMA, "module": module_name, "object_code": code,
                  "bins": bins, "dropped": dropped}
    return model, source_map


# ════════════════════════════════════════════════════════════
# 3) 写盘 + schema 门禁 + 双哈希
# ════════════════════════════════════════════════════════════

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def casemodel_yaml(model: Dict[str, Any]) -> str:
    import yaml as _yaml

    return _yaml.safe_dump(model, allow_unicode=True, sort_keys=False, width=110)


def import_ontology(onto: Any, out_dir: str | Path, *, module_name: str,
                    object_code: Optional[str] = None,
                    source_path: Optional[str | Path] = None,
                    axes_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """编译 Ontology → casemodel.yaml + source_map.json（过 schema 才落盘）。

    `axes_path` 是"怎么拆轴"的 sidecar —— 真实 xlsx 不建维度，组合格要变成
    真正的 cross bin，就靠这份声明。
    """
    from src.layers.l3_decision.casemodel.api import run_validate

    axes_stats = {}
    axes_doc: Dict[str, Any] = {}
    if axes_path:
        axes_doc = load_axes(axes_path)
        axes_stats = apply_axes(onto, axes_doc)
    bind_cells(onto)          # 导入步骤总是先绑定：调用方不必记得
    model, source_map = to_casemodel(onto, module_name=module_name,
                                     object_code=object_code)
    text = casemodel_yaml(model)
    report = run_validate(text)
    errors = [i for i in (report.get("issues") or []) if i.get("severity") == "error"]
    if errors:
        raise AivmImportError(
            "生成的 casemodel 未通过校验，拒绝写盘：\n  "
            + "\n  ".join(str(e)[:200] for e in errors[:8]))
    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)
    (root / "casemodel.yaml").write_text(text, encoding="utf-8", newline="\n")
    source_map["inputs"] = {
        "xlsx": str(source_path or onto.xlsx_rev),
        "xlsx_sha256": _sha256(Path(source_path).read_bytes()) if source_path else "",
    }
    source_map["outputs"] = {"casemodel_sha256": _sha256(text.encode("utf-8"))}
    if axes_path:
        source_map["axes"] = {
            "path": str(axes_path),
            "sha256": _sha256(Path(axes_path).read_bytes()),
            "applied": axes_stats,
        }
    (root / "source_map.json").write_text(
        json.dumps(source_map, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8", newline="\n")
    return {"casemodel": str(root / "casemodel.yaml"),
            "source_map": str(root / "source_map.json"),
            "bins": len(source_map["bins"]),
            "dropped": len(source_map["dropped"]),
            "warnings": len([i for i in (report.get("issues") or [])
                             if i.get("severity") != "error"]),
            "casemodel_sha256": source_map["outputs"]["casemodel_sha256"]}


def verify_import(xlsx_path: str | Path, casemodel_path: str | Path,
                  source_map_path: str | Path,
                  axes_path: Optional[str | Path] = None) -> Dict[str, Any]:
    """双哈希比对：表或模型被单边改过，都要报。"""
    issues: List[Dict[str, str]] = []
    try:
        source_map = json.loads(Path(source_map_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "issues": [{"check": "source_map_unreadable",
                                         "detail": str(exc)}]}
    expect_xlsx = (source_map.get("inputs") or {}).get("xlsx_sha256", "")
    expect_model = (source_map.get("outputs") or {}).get("casemodel_sha256", "")
    if expect_xlsx:
        actual = _sha256(Path(xlsx_path).read_bytes())
        if actual != expect_xlsx:
            issues.append({"check": "xlsx_changed",
                           "detail": f"{actual[:12]} != {expect_xlsx[:12]}"})
    if expect_model:
        actual = _sha256(Path(casemodel_path).read_bytes())
        if actual != expect_model:
            issues.append({"check": "casemodel_changed",
                           "detail": f"{actual[:12]} != {expect_model[:12]}"})
    expect_axes = (source_map.get("axes") or {}).get("sha256", "")
    if expect_axes and axes_path:
        actual = _sha256(Path(axes_path).read_bytes())
        if actual != expect_axes:
            issues.append({"check": "axes_changed",
                           "detail": f"{actual[:12]} != {expect_axes[:12]}"})
    return {"ok": not issues, "issues": issues}
