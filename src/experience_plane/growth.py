"""
Growth —— L4/L5 成长层：让智能体跨 run 越用越懂。

成长性 = 经验的可累积、可蒸馏、可迁移，而非"更强的 LLM"。

L4 记忆层：决策效果反馈（action_effectiveness → L3 决策增强）
  - 记录每轮"动作 → 覆盖率变化"，学习哪个动作对这个项目有效
  - 历史证明无效的动作（多次尝试但改善率低），决策层降级/避开

L5 进化层：经验蒸馏（零散经验 → 确定性能力）
  - 调试经验（success >= N 的成熟修复）→ auto_fix 模板（查表命中，跳过 LLM）
  - gap 经验 → 策略建议（跨项目迁移）

用法:
    from src.experience_plane.growth import (get_action_experience, is_action_proven_ineffective,
                                 get_mature_fixes, get_policy_evolution)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 无效动作判定阈值：尝试 >= 2 次且改善率 <= 0.3，视为"历史已证明无效"
MIN_TRIALS = 2
MAX_INEFFECTIVE_RATE = 0.3
# 蒸馏门槛：稳定通过 >= 3 次的成熟调试经验
DISTILL_MIN_SUCCESS = 3


# ═══════════════════════════════════════════════════════════════
# L4 记忆：决策效果
# ═══════════════════════════════════════════════════════════════

def get_action_experience(action_type: str, source: Optional[str] = None
                          ) -> Optional[Dict[str, Any]]:
    """查某决策动作的历史效果（trials / improve_rate / avg_delta）。

    `source` 给了就只统计那个来源。**RL 权重的学习必须传 `"rl_suggested"`** ——
    否则统计里会混进"这个动作被提名过、但当场被规则退掉、根本没执行"的轮次，
    算出来的改善率是**幸存者偏差**（见 `action_effectiveness` 的注释）。
    """
    try:
        from src.knowledge_plane.coverage_experience import get_coverage_experience_store
        return get_coverage_experience_store().action_effectiveness(source=source) \
            .get(action_type)
    except Exception:
        return None


def rl_suggested_actions() -> List[str]:
    """库里有 `rl_suggested` 记录的动作 —— **按构造**就是 RL 选过的那些。

    ## 为什么用这个替代"RL 的动作清单"

    蒸馏原来手写四个动作名，其中 `REFACTOR_RTL` 早已下线 —— 那一桶永远空着，
    而"少学了一个动作"从输出上看不出来。改成 `import SOFT_ACTIONS` 又会
    让 **L5 依赖 L3**，被层向测试当场拦下（实测）。

    而这个函数**根本不需要那份清单**：一条记录带 `rl_suggested` 来源，就意味着
    那一轮 RL 选了它并被采纳 —— 没进过 RL 动作空间的动名字**不可能**有这种记录。
    所以"库里有哪些"就是"RL 学得会哪些"的现成答案，既不手写也不跨层。
    """
    try:
        from src.knowledge_plane.coverage_experience import get_coverage_experience_store
        return sorted(get_coverage_experience_store()
                      .action_effectiveness(source="rl_suggested").keys())
    except Exception:
        return []


def is_action_proven_ineffective(action_type: str,
                                 min_trials: int = MIN_TRIALS,
                                 max_rate: float = MAX_INEFFECTIVE_RATE) -> bool:
    """判断某动作是否"历史已证明无效"（多次尝试但改善率低）。"""
    exp = get_action_experience(action_type)
    if not exp:
        return False
    return exp.get("trials", 0) >= min_trials and exp.get("improve_rate", 1.0) <= max_rate


def get_action_experience_note(action_type: str) -> str:
    """生成某动作的历史效果说明（附加到 Action.reason，供审计）。"""
    exp = get_action_experience(action_type)
    if not exp:
        return ""
    return (f" [经验: 该动作历史 {exp.get('trials', 0)} 次尝试，"
            f"改善率 {exp.get('improve_rate', 0):.0%}，"
            f"平均 Δ{exp.get('avg_delta', 0):+.1f}%]")


# ═══════════════════════════════════════════════════════════════
# L5 进化：经验蒸馏
# ═══════════════════════════════════════════════════════════════

def get_mature_fixes(min_success: int = DISTILL_MIN_SUCCESS) -> List[Dict[str, Any]]:
    """蒸馏成熟调试经验（稳定通过 N 次）成可复用修复模板。

    返回 [{fingerprint, category, root_cause, fix_name, success_count, confidence}]
    """
    try:
        from src.knowledge_plane.debug_experience import get_debug_experience_store
        return get_debug_experience_store().distill_candidates(min_success)
    except Exception:
        return []


def get_policy_evolution() -> List[Dict[str, Any]]:
    """从 gap 归因经验蒸馏出策略建议（跨项目迁移）。

    返回有效 gap reason 的改善率，供策略包进化（把高价值的 gap 模式
    追加到策略包的 coverage_bins）。
    """
    try:
        from src.knowledge_plane.coverage_experience import get_coverage_experience_store
        acc = get_coverage_experience_store().reason_accuracy()
        # 过滤出"验证有效"的 gap reason（改善率高）
        return [{"reason": r, **v} for r, v in acc.items()
                if v.get("confidence", 0) >= 0.5 and v.get("trials", 0) >= 1]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════
# L5 进化：跨项目迁移（按领域语义检索，而非 fingerprint）
# ═══════════════════════════════════════════════════════════════

def lookup_experience_by_category(category: str, min_confidence: float = 0.5) -> List[Dict[str, Any]]:
    """按领域语义（category）跨项目检索成熟调试经验。

    fingerprint 是"某个特定错误"，category 是"某类问题"（如 rtl_issue/
    model_issue）。跨项目迁移时，同 category 的经验可复用——比如项目 A
    的"前递失效"经验，迁移到项目 B 的同类"前递失效"。
    """
    try:
        from src.knowledge_plane.debug_experience import get_debug_experience_store
        all_exp = get_debug_experience_store().list_all()
        return [e for e in all_exp
                if e.get("category") == category
                and e.get("confidence", 0) >= min_confidence]
    except Exception:
        return []

# ═══════════════════════════════════════════════════════════════
# 交给 L2 装配的经验查询对象
# ═══════════════════════════════════════════════════════════════

class _GrowthExperienceProvider:
    """`ExperienceProvider` 的实现 —— 接口在 L3、实现在这里、装配在 L2。

    三方**互不 import**：
      · `l3_decision.decision_engine` 定义 `ExperienceProvider`（它不该知道 L5）
      · 本模块实现那个形状（它当然可以知道自己的函数）
      · `l2_orchestration.runtime` 在 `hydrate_runtime` 里把两者接起来

    在这之前，L3 是在 `_with_experience` 的函数体里延迟 import 本模块 ——
    那是**越级反向依赖**，只是被延迟 import 遮住了。
    """

    def note(self, action_type: str) -> str:
        return get_action_experience_note(action_type)

    def ineffective(self, action_type: str) -> bool:
        return is_action_proven_ineffective(action_type)


#: 单例 —— 无状态，装配处直接用。
experience_provider = _GrowthExperienceProvider()
