"""完备性评分 —— 八项子分加权成 0~100。

评分必须**只是模型的属性**：同一个模型无论你传哪份外部 case 列表、
无论跑在谁的机器上，分数都该一样。所以：

  · 只吃模型自身的诊断（外部核对的 Issue 不进评分，见 facade）
  · 每项子分都从可枚举的事实算出来，权重集中在这里、可审计
  · 每项都给出「为什么扣分」—— rows() 里的子分就是解释

权重和为 1。子分错了会直接反映到总分，所以每项都配了单测。
"""
from __future__ import annotations

from dataclasses import dataclass, field as _field
from typing import Dict, List, Sequence, Tuple

from ..domain import CaseModel
from .issues import (CATEGORY_CROSS, CATEGORY_ORG_TREE, CATEGORY_ORTHOGONAL,
                     CATEGORY_REFERENCE, CATEGORY_THEME, Issue)
from .specifications import RuleContext

# 权重与展示名 —— 集中一处，便于审计
SCORE_WEIGHTS: Dict[str, float] = {
    "layers": 0.15,          # 分层完备
    "references": 0.12,      # 引用完整
    "orthogonality": 0.16,   # 层级正交
    "org_tree": 0.12,        # 组织树
    "themes": 0.15,          # 专题
    "cross": 0.10,           # 维度交叉
    "coverage": 0.15,        # 取值覆盖
    "environment": 0.05,     # 环境与检查
}

SCORE_NAMES: Dict[str, str] = {
    "layers": "分层完备",
    "references": "引用完整",
    "orthogonality": "层级正交",
    "org_tree": "组织树",
    "themes": "专题",
    "cross": "维度交叉",
    "coverage": "取值覆盖",
    "environment": "环境与检查",
}


@dataclass
class ScoreBreakdown:
    """八项子分（各 0~1）+ 每项的扣分理由。"""
    layers: float = 0.0
    references: float = 0.0
    orthogonality: float = 0.0
    org_tree: float = 0.0
    themes: float = 0.0
    cross: float = 0.0
    coverage: float = 0.0
    environment: float = 0.0
    reasons: Dict[str, List[str]] = _field(default_factory=dict)

    @property
    def total(self) -> float:
        return sum(getattr(self, k) * w for k, w in SCORE_WEIGHTS.items()) * 100.0

    def rows(self) -> List[Tuple[str, float, float]]:
        """(项, 子分, 加权后得分) —— 报告与 GUI 展示用。"""
        return [(SCORE_NAMES[k], getattr(self, k), getattr(self, k) * w * 100.0)
                for k, w in SCORE_WEIGHTS.items()]

    def row_reasons(self) -> List[Tuple[str, float, float, List[str]]]:
        return [(SCORE_NAMES[k], getattr(self, k), getattr(self, k) * w * 100.0,
                 self.reasons.get(k, []))
                for k, w in SCORE_WEIGHTS.items()]


def _penalty(issues: Sequence[Issue], per_error: float = 0.25,
             per_warning: float = 0.05) -> Tuple[float, List[str]]:
    """按严重度扣分，并把「扣在哪条规则上」记下来。"""
    score = 1.0
    reasons: List[str] = []
    for i in issues:
        if i.is_error:
            score -= per_error
        elif i.severity == "warning":
            score -= per_warning
        else:
            continue
        if len(reasons) < 5:
            reasons.append(f"{i.rule}（{i.severity}）")
    if len(issues) > 5:
        reasons.append(f"…共 {len(issues)} 条")
    return max(0.0, score), reasons


def compute_score(ctx: RuleContext, model_issues: Sequence[Issue]) -> ScoreBreakdown:
    """从上下文与**模型自身**的诊断算出八项子分。"""
    model: CaseModel = ctx.model
    sb = ScoreBreakdown()
    by_cat: Dict[str, List[Issue]] = {}
    for i in model_issues:
        by_cat.setdefault(i.category, []).append(i)

    # ── 分层完备：八层都有实质内容才给满分 ──
    layers = [
        bool(model.object),
        bool(model.tree_nodes),
        bool(model.themes),
        bool(model.dimensions),
        any(f.cover_tokens() for f in model.all_fields),
        bool(model.methods),
        bool(model.checks),
        bool(model.env_required and model.case_defaults.environment),
    ]
    sb.layers = sum(1 for x in layers if x) / len(layers)
    missing = [n for n, ok in zip(("对象", "组织树", "专题", "维度", "字段取值",
                                   "方法", "检查", "环境指纹"), layers) if not ok]
    if missing:
        sb.reasons["layers"] = [f"缺：{'、'.join(missing)}"]

    # ── 引用完整：悬空引用是硬错误，一条扣 1/3 ──
    ref_errors = sum(1 for i in by_cat.get(CATEGORY_REFERENCE, []) if i.is_error)
    sb.references = max(0.0, 1.0 - ref_errors / 3.0)
    if ref_errors:
        sb.reasons["references"] = [
            f"{ref_errors} 条悬空引用（{'、'.join(sorted({i.rule for i in by_cat[CATEGORY_REFERENCE] if i.is_error}))}）"]

    # ── 层级正交 ──
    sb.orthogonality, sb.reasons["orthogonality"] = _penalty(
        by_cat.get(CATEGORY_ORTHOGONAL, []))

    # ── 组织树：叶子覆盖率为主，代号冲突一票重扣 ──
    leaves = model.leaf_nodes
    if leaves:
        covered = sum(1 for n in leaves if ctx.cases_for_node(n.id))
        sb.org_tree = covered / len(leaves)
        if covered < len(leaves):
            sb.reasons["org_tree"] = [f"{len(leaves) - covered}/{len(leaves)} 个叶子没有专题覆盖"]
    else:
        sb.org_tree = 0.0
        sb.reasons["org_tree"] = ["没有组织树节点"]
    tree_errors = sum(1 for i in by_cat.get(CATEGORY_ORG_TREE, []) if i.is_error)
    if tree_errors:
        sb.org_tree = max(0.0, sb.org_tree - 0.4 * tree_errors)
        # setdefault：上面那条只在**有叶子没被专题覆盖**时才建这个 key，
        # 于是"每个叶子都覆盖到了、但叶子代号重复"会在这里 KeyError ——
        # 而那恰恰是更接近正确的一份模型（实测：spec 合成的模型就是这么崩的）。
        sb.reasons.setdefault("org_tree", []).append(
            f"{tree_errors} 条组织树硬错误（如叶子代号重复）")

    # ── 专题：维度被专题选中的比例 + 优先级阶梯 + 专题自身问题 ──
    if model.themes:
        used = {d.key for t in model.themes for d in t.dims}
        dim_part = len(used) / max(1, len(model.dimensions))
        from ..domain import priority_gaps
        ladder = 0.9 if priority_gaps(model.themes) else 1.0
        theme_pen, sb.reasons["themes"] = _penalty(
            by_cat.get(CATEGORY_THEME, []), per_error=0.2, per_warning=0.05)
        sb.themes = max(0.0, dim_part * ladder * theme_pen)
        if dim_part < 1.0:
            sb.reasons.setdefault("themes", []).append(
                f"{len(model.dimensions) - len(used)} 个维度没被任何专题选中")
        if not sb.reasons.get("themes"):
            sb.reasons["themes"] = ["专题范围或优先级有不完整之处"]
    else:
        sb.themes = 0.0
        sb.reasons["themes"] = ["没有声明专题"]

    # ── 维度交叉 ──
    # 每一项扣分都要留下理由：分数如果不能解释，就没法行动。
    matrix = ctx.matrix
    if matrix is not None and matrix.total_pairs():
        total_pairs = matrix.total_pairs()
        declared = matrix.declared_count() / total_pairs
        participation = matrix.participation()
        orphan = sum(1 for d in model.dimensions if not participation.get(d.key))
        orphan_penalty = orphan / max(1, len(model.dimensions))
        cross_err = sum(1 for i in by_cat.get(CATEGORY_CROSS, []) if i.is_error)
        sb.cross = max(0.0, declared * (1 - orphan_penalty) - 0.2 * cross_err)
        reasons: List[str] = []
        undeclared = total_pairs - matrix.declared_count()
        if undeclared:
            reasons.append(f"{undeclared}/{total_pairs} 对维度没声明交叉关系")
        if orphan:
            reasons.append(f"{orphan} 个维度没参与任何交叉")
        if cross_err:
            reasons.append(f"{cross_err} 条交叉硬错误")
        if reasons:
            sb.reasons["cross"] = reasons
    else:
        sb.cross = 1.0 if len(model.dimensions) < 2 else 0.0
        if len(model.dimensions) >= 2:
            sb.reasons["cross"] = ["维度之间没有任何交叉关系"]

    # ── 取值覆盖 ──
    total = sum(d.total for d in ctx.dimension_coverage)
    hit = sum(d.hit_count for d in ctx.dimension_coverage)
    sb.coverage = (hit / total) if total else 0.0
    if total and hit < total:
        sb.reasons["coverage"] = [f"{total - hit}/{total} 个取值点未被覆盖"]

    # ── 环境与检查 ──
    env_part = _env_ratio(ctx)
    check_part = _check_ratio(ctx)
    sb.environment = (env_part + check_part) / 2
    if env_part < 1.0:
        sb.reasons["environment"] = ["必需环境键没有全部落到 case 上"]
    if check_part < 1.0:
        sb.reasons.setdefault("environment", []).append("检查项覆盖不全")

    return sb


def _env_ratio(ctx: RuleContext) -> float:
    required = ctx.model.env_required
    cases = ctx.generation.cases
    if not required:
        return 0.0
    if not cases:
        return 0.0
    ok = sum(1 for k in required
             if all(k in c.environment and c.environment.get(k) not in (None, "")
                    for c in cases))
    return ok / len(required)


def _check_ratio(ctx: RuleContext) -> float:
    model = ctx.model
    cases = ctx.generation.cases
    if not model.checks:
        return 0.0
    used = {c for case in cases for c in case.checks}
    declared = len(used & set(model.checks)) / len(model.checks)
    if not cases:
        return 0.0
    blank = sum(1 for c in cases if not c.checks) / len(cases)
    return declared * (1 - blank)
