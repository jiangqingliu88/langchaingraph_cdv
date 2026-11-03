"""框架的内置阶段 —— 用例建模 → 测试点 IR 的四段。

    DecomposeStage   取值点 → 测试点身份（dimension/value/专题/优先级/需求）
    TraceStage       测试点 → 覆盖仓（coverpoint.bin）
    RealizeStage     测试点 → realization（走注册表，可扩展）
    ExecuteStage     测试点 → test 类名 / 分级 / 起点种子 / 判据

**阶段之间不互相 import**：只通过 `ctx.artifacts["testpoints"]` 交换。
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..domain import priority_rank
from .contracts import PipelineContext, Stage
from .model import KIND_OBSERVE, Execution, TestPoint, Timing
from .naming import ascii_slug, attribute_test_name, iter_value_points
from .realization import REALIZATIONS, resolve_realization

#: 优先级 → 分级回归的级名。与 `infrastructure.REGRESSION_STAGES` 同名。
STAGE_BY_PRIORITY: Dict[int, str] = {0: "p0", 1: "p1", 2: "p2"}
DEFAULT_STAGE = "p3"


def stage_for(priority: str) -> str:
    return STAGE_BY_PRIORITY.get(priority_rank(priority), DEFAULT_STAGE)


def bind_case_identity(ctx: PipelineContext, *, test: str,
                       dimension: str) -> Tuple[str, str]:
    """(case_id, tst_id) —— **身份在生成期注入**，不做事后反推。

    Case IR 的来源：模型 `cases:` 段（人声明）> 按维度合成（结构兜底）。
    拿不到就返回空串 —— 门禁会报 `CASE_MISSING`，而不是编一个默认用例。
    """
    try:
        from src.tools.humanview.case_ir import project_from_casemodel, tst_id_of
    except Exception:                          # noqa: BLE001 身份层不可用不挡生成
        return "", ""

    doc = ctx.take("case_doc")
    if doc is None:
        doc = project_from_casemodel(ctx.model, module=ctx.module_name or "")
        ctx.put("case_doc", doc)
    case_id = doc.resolve(test=test, dimension=dimension) if not doc.empty else ""
    return case_id, (tst_id_of(test) if test else "")


def priority_of(themes: List[Any]) -> str:
    """一组专题里**最高**的优先级（P0 最优先）。没有专题 → P3。"""
    ranked = [t for t in themes if t.priority]
    if not ranked:
        return "P3"
    return min(ranked, key=lambda t: t.rank).priority


def theme_seeds(themes: List[Any], limit: int = 16) -> List[int]:
    """覆盖该测试点的专题 → 基线种子（`base … base+count-1`，去重保序）。"""
    out: List[int] = []
    for t in themes:
        try:
            base = int((t.seeds or {}).get("base", 0))
            count = int((t.seeds or {}).get("count", 0))
        except (TypeError, ValueError):
            continue
        for s in range(base, base + max(0, count)):
            if s not in out:
                out.append(s)
            if len(out) >= limit:
                return out
    return out


class DecomposeStage(Stage):
    """取值点 → 测试点身份。

    **一条取值点 = 一条测试点**。这里只建立身份与模型引用，不判断实现方式 ——
    那是 RealizeStage 的事。
    """
    name = "decompose"
    consumes: Tuple[str, ...] = ()
    produces = "testpoints"

    def run(self, ctx: PipelineContext) -> None:
        model = ctx.model
        points: List[TestPoint] = []
        conflicts: Dict[str, Tuple[List[str], str]] = {}

        for dim, fld, index, point, value_int, tp_id in iter_value_points(model):
            dim_ref = dim.id or dim.name or dim.key
            covering = [t for t in model.themes
                        if any(d.key == dim.key for d in (t.dims or []))]
            methods = sorted({t.method for t in covering if t.method})
            method = ""
            if methods:
                top = min((t for t in covering if t.method), key=lambda t: t.rank)
                method = top.method
                if len(methods) > 1:
                    conflicts.setdefault(dim.key, (methods, f"{top.key}={method}"))

            points.append(TestPoint(
                tp_id=tp_id,
                object=model.object,
                dimension=dim.key,
                dimension_name=dim.name,
                field=fld.name,
                value=str(point.token),
                tree_path="、".join(dim.sub_objects),
                requirement=fld.requirement,
                cover_id=fld.cover_id,
                method=method,
                checks=sorted({c for t in covering for c in (t.checks or [])}),
                themes=[t.key for t in covering],
                priority=priority_of(covering),
                boundary=bool(point.boundary),
            ))

        for dim_key, (methods, chosen) in sorted(conflicts.items()):
            ctx.notes.append(
                f"维度 {dim_key} 被多个方法的专题覆盖 {methods} —— "
                f"测试点的 method 取最高优先级那个（{chosen}）；"
                f"批次层的约束仍由各专题自己的策略决定")

        ctx.put(self.produces, points)


class TraceStage(Stage):
    """测试点 → 覆盖仓（观测端）。

    模型与生成的覆盖率模型漂了（取值对不上仓）时**记账**，不猜一个 bin。
    """
    name = "trace"
    consumes = ("testpoints",)
    produces = "testpoints"

    def run(self, ctx: PipelineContext) -> None:
        points: List[TestPoint] = ctx.require("testpoints")
        cps = {}
        if ctx.coverage is not None:
            cps = {(cp.dimension, cp.field): cp for cp in ctx.coverage.coverpoints}

        for tp in points:
            cp = cps.get((tp.dimension, tp.field))
            tp.coverpoint = cp.sv_name if cp is not None else ""
            if cp is None:
                if ctx.coverage is not None:
                    ctx.notes.append(
                        f"{tp.tp_id}: 维度 {tp.dimension} 没有对应的 coverpoint")
                continue
            tp.bin = _bin_for_value(cp, tp.value)
            if not tp.bin:
                ctx.notes.append(
                    f"{tp.tp_id}: 取值 {tp.value} 对不上任何覆盖仓"
                    f"（{cp.sv_name}）—— 覆盖端会漏掉它")


def _bin_for_value(cp: Any, token: Any) -> str:
    """取值点 → 它落在哪个覆盖仓里（显式仓按数值/区间判断）。"""
    text = str(token)
    for b in cp.bins:
        if b.token and b.token == text:
            return b.name
    # 非数字 token（枚举）按下标投影
    try:
        v = int(text)
    except (TypeError, ValueError):
        v = None
    if v is None:
        return ""
    for b in cp.bins:
        if b.value is not None and b.value == v:
            return b.name
        if b.values and v in b.values:
            return b.name
        if b.lo is not None and v >= b.lo and (b.hi is None or v <= b.hi):
            return b.name
    return ""


def _attach_timing(tp: TestPoint, dim: Any, ctx: Any) -> None:
    """维度的 `realization.timing` → TP 的时序窗口（按取值点覆盖 `*`）。

    **没有 timing 就不设**（`tp.timing` 保持 None）：不判时序 ≠ 通过时序。
    声明了但缺 `start`/`end` 时照样记进 IR，并在 `notes` 里说"不可判" ——
    生成期说出来，比生成一个永远不报的空检查强。
    """
    spec_map = getattr(dim, "realization_timing", None) or {}
    if not spec_map:
        return
    spec = (spec_map.get(str(tp.value))
            or spec_map.get("*") or spec_map.get("default"))
    timing = Timing.from_dict(spec)
    if timing is None:
        ctx.notes.append(f"{tp.tp_id}: timing 写法无法解析（需要 min/max 整数）"
                         f"—— 这条不判时序")
        return
    tp.timing = timing
    if not timing.checkable:
        ctx.notes.append(
            f"{tp.tp_id}: timing 缺 start/end（或窗口非法）—— 时序不可判，"
            f"env 不会为它生成检查；补 `start: <DUT 信号>` / `end: <DUT 信号>`")


class RealizeStage(Stage):
    """测试点 → realization（**走注册表**，新增 kind 不用改这里）。"""
    name = "realize"
    consumes = ("testpoints",)
    produces = "testpoints"

    def run(self, ctx: PipelineContext) -> None:
        points: List[TestPoint] = ctx.require("testpoints")
        observe_dims: set = set()

        for tp in points:
            dim = ctx.model.dimension(tp.dimension) or _dim_by_key(ctx.model, tp.dimension)
            fld = _field_of(dim, tp.field) if dim is not None else None
            if dim is None:
                ctx.notes.append(f"{tp.tp_id}: 找不到维度 {tp.dimension}")
                tp.realization.kind = KIND_OBSERVE
                continue
            value = _int_of(tp.value, tp.field, dim)
            tp.realization = resolve_realization(dim, fld, value,
                                                 ctx.agents, ctx.notes,
                                                 token=tp.value)
            _attach_timing(tp, dim, ctx)
            if tp.observe_only:
                observe_dims.add(dim.key)

            # 策略自校验（扩展策略可以在这里暴露"缺参数"）
            strategy = REALIZATIONS.get(tp.realization.kind)
            if strategy is not None:
                instance = strategy() if isinstance(strategy, type) else strategy
                for issue in instance.validate(tp, ctx):
                    ctx.notes.append(issue)

        if observe_dims:
            ctx.notes.append(
                f"观测型维度 {len(observe_dims)} 个（{'、'.join(sorted(observe_dims))}）："
                f"没有事务字段可驱动，测试点按 OBSERVE_ONLY 统计 —— "
                f"要把它们变成可驱动的，在模型里写 "
                f"`stimulus: {{field: <seq_item 字段>}}`，或声明 "
                f"`realization: {{kind: sequence}}` 用场景序列到达该状态")


class ExecuteStage(Stage):
    """测试点 → 执行计划（test 类名 / 分级 / 起点种子 / 判据）。"""
    name = "execute"
    consumes = ("testpoints",)
    produces = "testpoints"

    def run(self, ctx: PipelineContext) -> None:
        points: List[TestPoint] = ctx.require("testpoints")
        env_name = ctx.env_name or f"{ascii_slug(ctx.model.object) or 'dut'}_env"

        for tp in points:
            dim = ctx.model.dimension(tp.dimension) or _dim_by_key(ctx.model, tp.dimension)
            dim_ref = (dim.id or dim.name or dim.key) if dim is not None else tp.dimension
            value_int = _int_of(tp.value, tp.field, dim)
            covering = [t for t in ctx.model.themes
                        if any(d.key == tp.dimension for d in (t.dims or []))]

            test_name = attribute_test_name(env_name, dim_ref, tp.value, value_int)
            tp.execution = Execution(
                test=test_name,
                stage=stage_for(tp.priority),
                seeds=theme_seeds(covering),
            )
            tp.case_id, tp.tst_id = bind_case_identity(
                ctx, test=test_name, dimension=dim_ref)
            rule: Dict[str, str] = {
                "pass": "UVM_ERROR=0 and mismatched=0",
                "evidence": (f"bin {tp.coverpoint}.{tp.bin}" if tp.bin else ""),
            }
            if tp.observe_only:
                rule["observe_only"] = "bin_hit > 0"
            tp.status_rule = rule


# ── 小工具 ──

def _dim_by_key(model: Any, key: str):
    for d in model.dimensions:
        if d.key == key:
            return d
    return None


def _field_of(dim: Any, name: str):
    if dim is None:
        return None
    for f in dim.fields:
        if f.name == name:
            return f
    return None


def _int_of(value: str, field: str, dim: Any) -> int:
    """测试点里的取值 → 整型（数字优先，否则用它在字段取值点里的下标）。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        pass
    fld = _field_of(dim, field) if dim is not None else None
    if fld is not None:
        for i, p in enumerate(fld.value_points()):
            if str(p.token) == str(value):
                return i
    return 0
