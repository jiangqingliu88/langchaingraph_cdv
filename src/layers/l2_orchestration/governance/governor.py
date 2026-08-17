"""
Governor —— 统一驾驭层：资源预算 + 熔断 + 细粒度干预。

驾驭自主智能体的核心不是"更强的限制"，而是"看得见 + 停得住 + 回得去 + 管得住"。
本模块提供三层保护：

1. ResourceBudget（资源预算）：token / 时间 / EDA 调用次数，超预算则拒绝继续
2. CircuitBreaker（熔断器）：某动作连续失败 N 次 → 熔断（暂停 + 升级人工）
3. Intervention（细粒度干预）：指令文件（pause/skip/step/override_action）

用法:
    from src.layers.l2_orchestration.governance.governor import Governor
    gov = Governor(output_root)
    gov.before_action("RELAX_CONSTRAINT")   # 执行前检查
    gov.after_action("RELAX_CONSTRAINT", success=True)  # 执行后记录
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


# ═══════════════════════════════════════════════════════════════
# 熔断器
# ═══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """熔断器：连续失败 N 次 → 熔断（open），成功或人工复位才恢复（close）。"""

    def __init__(self, threshold: int = 3):
        self.threshold = threshold
        self._failures: Dict[str, int] = {}
        self._open: set = set()

    def record_failure(self, key: str) -> bool:
        """记录一次失败，返回是否触发熔断。"""
        self._failures[key] = self._failures.get(key, 0) + 1
        if self._failures[key] >= self.threshold:
            self._open.add(key)
            return True
        return False

    def record_success(self, key: str):
        self._failures[key] = 0
        self._open.discard(key)

    def reset(self, key: str):
        """人工复位（清除熔断状态）。"""
        self._failures[key] = 0
        self._open.discard(key)

    def is_open(self, key: str) -> bool:
        return key in self._open

    def status(self) -> Dict[str, Any]:
        return {
            "open": sorted(self._open),
            "failures": dict(self._failures),
            "threshold": self.threshold,
        }


# ═══════════════════════════════════════════════════════════════
# 资源预算
# ═══════════════════════════════════════════════════════════════

class ResourceBudget:
    """统一资源预算：token / 时间 / EDA 调用次数。"""

    def __init__(self, token_budget: int = 200_000,
                 time_budget_s: float = 3600.0, eda_budget: int = 100):
        self.token_budget = token_budget
        self.time_budget_s = time_budget_s
        self.eda_budget = eda_budget
        self.tokens_used = 0
        self.time_start = time.monotonic()
        self.eda_calls = 0

    def consume(self, tokens: int = 0, eda: int = 0):
        self.tokens_used += tokens
        self.eda_calls += eda

    @property
    def time_used_s(self) -> float:
        return time.monotonic() - self.time_start

    def is_exhausted(self) -> bool:
        return (self.tokens_used >= self.token_budget
                or self.time_used_s >= self.time_budget_s
                or self.eda_calls >= self.eda_budget)

    def status(self) -> Dict[str, Any]:
        return {
            "tokens": {"used": self.tokens_used, "budget": self.token_budget},
            "time_s": {"used": round(self.time_used_s, 1), "budget": self.time_budget_s},
            "eda": {"used": self.eda_calls, "budget": self.eda_budget},
            "exhausted": self.is_exhausted(),
        }


# ═══════════════════════════════════════════════════════════════
# 细粒度干预（指令文件）
# ═══════════════════════════════════════════════════════════════

class Intervention:
    """细粒度干预：通过指令文件（.harness_cmd）人工精准控制闭环。

    指令文件格式（JSON）: {"cmd": "pause" | "skip" | "step" | "override_action",
                          "action_type": "...",  # override_action 时用
                          "stage": "..."}          # skip/step 时用
    """

    CMD_FILE = ".harness_cmd"

    def __init__(self, output_root: str = "output"):
        self.cmd_path = Path(output_root) / self.CMD_FILE

    def read(self) -> Optional[Dict[str, Any]]:
        """读取当前指令（读后不清除，由闭环显式确认）。"""
        if not self.cmd_path.exists():
            return None
        try:
            return json.loads(self.cmd_path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def write(self, cmd: Dict[str, Any]):
        self.cmd_path.write_text(json.dumps(cmd, ensure_ascii=False), encoding="utf-8")

    def clear(self):
        if self.cmd_path.exists():
            self.cmd_path.unlink()


# ═══════════════════════════════════════════════════════════════
# Governor 统一入口
# ═══════════════════════════════════════════════════════════════

@dataclass
class GovernDecision:
    """驾驭决策：是否允许执行某动作 + 原因。"""
    allowed: bool = True
    reason: str = ""
    intervention: Optional[Dict[str, Any]] = None


class Governor:
    """统一驾驭层：预算 + 熔断 + 干预。"""

    def __init__(self, output_root: str = "output"):
        self.breaker = CircuitBreaker()
        self.budget = ResourceBudget()
        self.intervention = Intervention(output_root)

    def before_action(self, action_type: str) -> GovernDecision:
        """执行动作前检查：预算 + 熔断 + 人工干预。"""
        # 1. 人工干预优先（人能接管）
        cmd = self.intervention.read()
        if cmd:
            return GovernDecision(allowed=False, reason=f"人工干预: {cmd.get('cmd')}",
                                  intervention=cmd)
        # 2. 熔断（连续失败）
        if self.breaker.is_open(action_type):
            return GovernDecision(allowed=False,
                                  reason=f"熔断: {action_type} 连续失败 {self.breaker.threshold} 次，需人工介入")
        # 3. 预算耗尽
        if self.budget.is_exhausted():
            return GovernDecision(allowed=False, reason="预算耗尽: " + str(self.budget.status()))
        return GovernDecision(allowed=True)

    def after_action(self, action_type: str, success: bool,
                     tokens: int = 0, eda: int = 0):
        """执行动作后记录：失败计数 + 预算消耗。"""
        if success:
            self.breaker.record_success(action_type)
        else:
            self.breaker.record_failure(action_type)
        self.budget.consume(tokens=tokens, eda=eda)

    def status(self) -> Dict[str, Any]:
        return {
            "breaker": self.breaker.status(),
            "budget": self.budget.status(),
            "intervention": self.intervention.read(),
        }
