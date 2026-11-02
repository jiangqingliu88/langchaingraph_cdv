"""M1 计划编译器：把 Ontology 编译成『可直接给激励生成器』的覆盖计划。

三条铁律（也是这套方法论和『笛卡尔积再裁剪』方案的分水岭）：

1. 不做笛卡尔积。
   源表一格 = 一个候选 bin。IF02 的 (start_order, done_order, legality) 已经在
   D 列每格写死了，直接遍历 CoverageCell，天然是源表格子数，约束跟着格子走，
   不需要约束求解器。

2. 三通道分派，全部走 Enum，不比字符串：
   ┌──────────────────┬────────────────────┬──────────────────────────┐
   │ cell_type        │ 产物               │ 落点                     │
   ├──────────────────┼────────────────────┼──────────────────────────┤
   │ CONSTRAINT_COMBO │ cover_bin          │ covergroup bin / cross   │
   │ CONFIG_ENUM      │ config_enum_cover  │ 配置域穷举（13'b… 全踩） │
   │ DIRECTED_CASE    │ directed_case      │ 定向用例（test_num 定数） │
   │ DESCRIPTOR/HEADER│ 忽略               │ 只进 provenance 追溯     │
   └──────────────────┴────────────────────┴──────────────────────────┘

3. 所有分支判据都是 Enum 的 `is`：
     tp.category is Category.IF
     tp.execution_mode is ExecutionMode.COVERAGE_DRIVEN
     cell.cell_type is CellType.CONSTRAINT_COMBO
   新增专题 / 新增格子类型时，只改 Enum 与 classify，编译器主体不动。

输出：纯 dict + covergroup 桩，可直接喂给 UVM / Python 激励器。
"""
from __future__ import annotations

from .ir_core import (
    Ontology, TestPointIR, CoverageCell,
    Category, Component, TestNumKind, ExecutionMode, CellType, CellRole,
)
from .validate import validate_ontology


def _comp(tp: TestPointIR) -> str:
    """激励池分桶键：多模块取首个，缺省 'shared'。"""
    return tp.dut_components[0] if tp.dut_components else "shared"


def _bin_label(cell: CoverageCell, tp: TestPointIR) -> str:
    """覆盖 bin 标签：约束格保留原文；配置格用原文；超长时截短并留摘要。"""
    t = cell.raw_text.strip()
    if cell.legality and cell.legality not in t:
        return f"{t}  ::  {cell.legality}"
    return t


def compile_cell(cell: CoverageCell, tp: TestPointIR) -> dict | None:
    """把单个格子编译成计划条目；非产出型格子返回 None。"""
    if cell.cell_type is CellType.CONSTRAINT_COMBO and cell.role is CellRole.LEAF:
        return {
            "kind": "cover_bin",
            "cell_id": cell.cell_id,
            "label": _bin_label(cell, tp),
            "legality": cell.legality or None,
            "component": _comp(tp),
            "category": tp.category.value,
            "source_row": cell.source_row,
        }

    if cell.cell_type is CellType.CONFIG_ENUM and cell.is_material():
        return {
            "kind": "config_enum",
            "cell_id": cell.cell_id,
            "label": cell.raw_text.strip(),
            "component": _comp(tp),
            "category": tp.category.value,
            "source_row": cell.source_row,
            "note": "配置域穷举覆盖：该值必须被踩到，不做组合交叉",
        }

    if cell.cell_type is CellType.DIRECTED_CASE and cell.is_material():
        return {
            "kind": "directed_case",
            "cell_id": cell.cell_id,
            "label": cell.raw_text.strip() or tp.test_name or tp.tp_id,
            "component": _comp(tp),
            "category": tp.category.value,
            "source_row": cell.source_row,
        }

    # HEADER / DESCRIPTOR：只留追溯，不生成任何 bin
    return None


def compile_tp(tp: TestPointIR) -> dict:
    mode = tp.execution_mode
    points: list[dict] = []

    if mode is ExecutionMode.COVERAGE_DRIVEN:
        # 组合 bin 优先；若某 TP 全是配置枚举（如 C02 的 tile 模式段），退到配置通道
        bins = [compile_cell(c, tp) for c in tp.coverage_cells]
        points = [p for p in bins if p is not None]
        if not points and tp.config_enum_cells():
            points = [compile_cell(c, tp) for c in tp.config_enum_cells()]
            points = [p for p in points if p is not None]
    elif mode is ExecutionMode.DIRECTED:
        # 有明确命名用例格 → 一格一例；否则按 test_num 开出用例槽
        named = [compile_cell(c, tp) for c in tp.directed_case_cells()]
        named = [p for p in named if p is not None]
        if named:
            points = named
        else:
            n = tp.coverage_point_count() or 1
            for i in range(1, n + 1):
                points.append({
                    "kind": "directed_case",
                    "cell_id": f"{tp.tp_id}#c{i}",
                    "label": tp.test_name or tp.feature_text or tp.tp_id,
                    "component": _comp(tp),
                    "category": tp.category.value,
                    "source_row": tp.provenance.xlsx_rows[0]
                                 if tp.provenance.xlsx_rows else 0,
                })
    else:  # HYBRID
        points.append({
            "kind": "hybrid_shell",
            "cell_id": f"{tp.tp_id}#shell",
            "label": tp.feature_text or tp.tp_id,
            "component": _comp(tp),
            "category": tp.category.value,
            "cover_bins": len(tp.cover_bin_cells()),
            "config_enums": len(tp.config_enum_cells()),
            "note": "覆盖骨架 + 定向冒烟，需人工拆 bin",
        })

    kinds = Counter(p["kind"] for p in points)
    return {
        "tp_id": tp.tp_id,
        "category": tp.category.value,
        "mode": mode.value,
        "components": tp.dut_components,
        "test_num": tp.test_num,
        "test_num_kind": tp.test_num_kind.value,
        "cell_types": tp.cell_type_breakdown(),
        "point_count": len(points),
        "cover_bins": kinds.get("cover_bin", 0),
        "config_enums": kinds.get("config_enum", 0),
        "directed_cases": kinds.get("directed_case", 0),
        "points": points,
    }


from collections import Counter  # noqa: E402  (放顶部也行，保持 compile_tp 内聚)


def compile_ontology(onto: Ontology,
                     categories: set[Category] | None = None,
                     components: set[str] | None = None,
                     include_headers: bool = False,
                     validate: bool = True) -> dict:
    """编译整张本体。

    include_headers=False（默认）：HEADER/DESCRIPTOR 格不进 points，只出现在统计里，
        这正是『头行分组文本不算覆盖 bin』的实现。
    include_headers=True：头行也当 cover_bin 产出（PM 确认头行是合法组合时用）。
    """
    if validate:
        rep = validate_ontology(onto, strict=False)
        hard = [e for e in rep["errors"] if not e.startswith("[")]
        if hard:
            raise RuntimeError("[m1] 校验未通过，停止编译:\n  " + "\n  ".join(hard[:8]))
        if rep["errors"]:
            print(f"[m1] 告警 {len(rep['errors'])} 条（已降级，不阻断）", flush=True)

    plans: list[dict] = []
    for tp in onto.testpoints:
        if categories and tp.category not in categories:
            continue
        if components and not (set(tp.dut_components) & components):
            continue
        plans.append(compile_tp(tp))

    totals = Counter()
    for p in plans:
        totals["cover_bins"] += p["cover_bins"]
        totals["config_enums"] += p["config_enums"]
        totals["directed_cases"] += p["directed_cases"]

    return {
        "version": onto.version,
        "xlsx_rev": onto.xlsx_rev,
        "filter": {
            "categories": sorted(c.value for c in (categories or set())),
            "components": sorted(components or set()),
            "include_headers": include_headers,
        },
        "tp_count": len(plans),
        "by_mode": dict(Counter(p["mode"] for p in plans)),
        "totals": dict(totals),
        "plans": plans,
    }


if __name__ == "__main__":
    import json
    import sys
    from .xlsx_loader import load_xlsx_to_ontology

    src = sys.argv[1] if len(sys.argv) > 1 else "NPU_V2.CMDSCHED new testpoint.xlsx"
    onto = load_xlsx_to_ontology(src, version="m1-roundtrip")
    out = compile_ontology(onto, categories={Category.IF})
    print(json.dumps(out, ensure_ascii=False, indent=2))
    t = out["totals"]
    print(f"\n[summary] IF TPs={out['tp_count']} | "
          f"cover_bins={t['cover_bins']} config_enums={t['config_enums']} "
          f"directed={t['directed_cases']}")
