"""资源交互策略：Overlap 是事实，Conflict 是策略推导。

不要把「地址重叠」直接判成错误：
  · FORBIDDEN_OVERLAP  禁止重叠；
  · ARBITRATED_OVERLAP 允许重叠，但必须有仲裁检查；
  · SERIALIZED / ORDERED / DEPENDENT 需要时序检查；
  · EXCLUSIVE 需要 owner 互斥检查；
  · UNRESTRICTED 无额外限制。
"""
from __future__ import annotations

from typing import Any, Dict

from .schema import RELATIONS


def evaluate(policy: str, overlap_kind: str, *,
             same_owner: bool = False) -> Dict[str, Any]:
    """策略 + 区间事实 → `{conflict, requires_checker, reason}`。"""
    policy = str(policy or "UNRESTRICTED").upper()
    if policy not in RELATIONS:
        return {"conflict": False, "requires_checker": False,
                "reason": f"未知策略 {policy}，按 UNRESTRICTED 处理"}
    if overlap_kind == "NONE" or overlap_kind == "ADJACENT":
        return {"conflict": False, "requires_checker": False,
                "reason": f"无重叠（{overlap_kind}）"}

    if policy == "FORBIDDEN_OVERLAP":
        return {"conflict": True, "requires_checker": True,
                "reason": "策略禁止重叠"}
    if policy == "ARBITRATED_OVERLAP":
        return {"conflict": False, "requires_checker": True,
                "reason": "允许重叠，但需要仲裁结果"}
    if policy == "EXCLUSIVE":
        return {"conflict": bool(not same_owner), "requires_checker": True,
                "reason": "同一时间只允许一个 owner"}
    if policy == "SERIALIZED":
        return {"conflict": False, "requires_checker": True,
                "reason": "要求串行执行，检查实际顺序"}
    if policy == "ORDERED":
        return {"conflict": False, "requires_checker": True,
                "reason": "要求先后顺序，检查时序"}
    if policy == "DEPENDENT":
        return {"conflict": False, "requires_checker": True,
                "reason": "后序操作依赖前序完成"}
    return {"conflict": False, "requires_checker": False,
            "reason": "无额外限制"}


__all__ = ["evaluate"]
