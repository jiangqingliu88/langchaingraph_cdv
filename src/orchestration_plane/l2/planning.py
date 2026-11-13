"""
Planning —— 长周期任务规划（L3 决策层之上、覆盖率目标之下的规划层）。

覆盖率驱动闭环缺的"计划"在这里补上：不是"裸奔冲 target"，而是
  跑之前有规划（目标分解 + 里程碑）
  跑之中有进度（每轮对比里程碑）
  跑之后有预测（按提升速率判断能否收敛）

统一覆盖率目标来源：消除散落 8 处的硬编码 95，收敛到
`Settings.verification.coverage_target`（环境变量 VERIFY_COVERAGE_TARGET 可覆盖）。

用法:
    from src.orchestration_plane.l2.planning import CoveragePlanner, get_coverage_target
    target = get_coverage_target()              # 统一来源（默认 95）
    planner = CoveragePlanner(target=target, start=0, max_rounds=5)
    planner.check_progress(round_num, coverage)  # 进度对比
    planner.predict_convergence(history)         # 收敛预测
"""
from __future__ import annotations

from typing import Dict, List, Optional


def get_coverage_target() -> float:
    """统一覆盖率目标来源：Settings.verification.coverage_target，默认 95。"""
    try:
        from config.settings import Settings
        return float(Settings.get_instance().verification.coverage_target)
    except Exception:
        return 95.0


def get_coverage_metric() -> str:
    """统一**口径**来源：`functional`（默认）或 `code`。

    与 `get_coverage_target` 是一对：目标说"要到多少"，口径说"盯着哪一个数"。
    分开是因为它们会各自被改（目标按项目调、口径按方法学定），而**口径不能是
    隐式的** —— 它原来是隐式的（永远看代码覆盖率），于是闭环一直拿一个它的动作
    推不动的数当收敛目标，六轮不动、还以为是"再跑跑就好了"。
    """
    try:
        from config.settings import Settings
        m = str(Settings.get_instance().verification.coverage_metric or "").strip().lower()
    except Exception:
        m = ""
    return m if m in ("functional", "code") else "functional"


#: 口径 → 覆盖率 dict 里的键。
#: `functional_pct` 来自 `vcover report -cvg`（covergroup 的 bin 命中），
#: `overall_pct` 来自代码覆盖率的解析（statement/branch/…）。
METRIC_KEYS = {"functional": "functional_pct", "code": "overall_pct"}


def pick_coverage_value(cov: dict, metric: str = "") -> Dict[str, Any]:
    """按口径从覆盖率 dict 里取"这次是多少" → `{value, key, metric, present}`。

    **缺就说缺**（`present=False`）：选定的口径没采到时不悄悄换另一个口径 ——
    那会让闭环的目标在无声中换掉，而"数字变了"和"口径变了"在报告里长得一样。
    调用方据此**响亮地**记一笔，再决定拿什么数值往下走。
    """
    metric = (metric or get_coverage_metric())
    key = METRIC_KEYS.get(metric, "functional_pct")
    raw = (cov or {}).get(key)
    if raw is None:
        return {"value": 0.0, "key": key, "metric": metric, "present": False}
    try:
        return {"value": float(raw), "key": key, "metric": metric, "present": True}
    except (TypeError, ValueError):
        return {"value": 0.0, "key": key, "metric": metric, "present": False}


class CoveragePlanner:
    """长周期任务规划器：目标分解 + 里程碑 + 进度跟踪 + 收敛预测。"""

    def __init__(self, target: Optional[float] = None,
                 start: float = 0.0, max_rounds: int = 5):
        self.target = target if target is not None else get_coverage_target()
        self.start = start
        self.max_rounds = max_rounds
        self.milestones = self._build_milestones()

    def _build_milestones(self) -> List[float]:
        """目标分解：非线性里程碑（边际递减——覆盖率前期提升快，后期慢）。

        例：target=95, start=0, max_rounds=5 → [≈86, ≈91, ≈93, ≈94, 95]
        """
        if self.target <= self.start:
            return [self.target] * self.max_rounds
        milestones = []
        for i in range(1, self.max_rounds + 1):
            progress = i / self.max_rounds
            # progress ** 0.6：前期快（大提升），后期慢（逼近目标）
            milestone = self.start + (self.target - self.start) * (progress ** 0.6)
            milestones.append(round(milestone, 1))
        milestones[-1] = self.target  # 最后一轮强制等于目标
        return milestones

    def check_progress(self, round_num: int, coverage: float) -> Dict:
        """对比当前覆盖率与里程碑。round_num 从 1 开始。"""
        idx = min(round_num - 1, len(self.milestones) - 1)
        milestone = self.milestones[idx]
        return {
            "round": round_num,
            "coverage": coverage,
            "milestone": milestone,
            "on_track": coverage >= milestone,
            "gap": round(coverage - milestone, 1),
        }

    def predict_convergence(self, history: List[float]) -> Dict:
        """按最近提升速率预测收敛。返回还需几轮 + 是否收敛。"""
        if len(history) < 2:
            return {"rounds_to_target": None, "converging": None}
        recent_growth = history[-1] - history[-2]
        remaining = self.target - history[-1]
        if recent_growth <= 0:
            return {"rounds_to_target": float("inf"), "converging": False,
                    "note": "覆盖率停滞，需换策略（决策层已处理）"}
        return {
            "rounds_to_target": max(1, int(remaining / recent_growth) + 1),
            "converging": True,
        }

    def to_dict(self) -> Dict:
        return {
            "target": self.target,
            "start": self.start,
            "max_rounds": self.max_rounds,
            "milestones": self.milestones,
        }
