"""
人工审批门控模块

借鉴原型设计的 input() 审批，升级为多模式可配置版本。
支持 interactive / auto / threshold 三种模式，完整审计记录。

用法:
  gate = create_approval_gate("interactive")
  if gate.requires_approval("rtl", "medium"):
      record = gate.ask("rtl", summary, "medium")
      if record.decision == ApprovalDecision.REJECT:
          raise PipelineTerminatedError(...)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field


# ═══════════════════════════════════════════════════════════════
# 审批决策
# ═══════════════════════════════════════════════════════════════

class ApprovalDecision(str, Enum):
    APPROVE = "approve"     # 通过，继续
    REJECT = "reject"       # 拒绝，终止流程
    SKIP = "skip"           # 跳过此阶段，继续后续
    REVIEW = "review"       # 查看详情后再决定


# ═══════════════════════════════════════════════════════════════
# 审批记录
# ═══════════════════════════════════════════════════════════════

@dataclass
class ApprovalRecord:
    stage: str
    decision: ApprovalDecision
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    reviewer: str = "human"
    reason: str = ""
    context_snapshot: Optional[Dict] = None


# ═══════════════════════════════════════════════════════════════
# 审批模式
# ═══════════════════════════════════════════════════════════════

class ApprovalMode(str, Enum):
    INTERACTIVE = "interactive"   # 终端交互：等待 y/n
    AUTO = "auto"                 # 全自动：全部通过（CI 模式）
    THRESHOLD = "threshold"       # 阈值模式：风险 > threshold 才审批


# ═══════════════════════════════════════════════════════════════
# 审批门控
# ═══════════════════════════════════════════════════════════════

class ApprovalGate:
    """审批门控 — 借鉴原型 input() 但升级为多模式可配置"""

    def __init__(
        self,
        mode: ApprovalMode = ApprovalMode.THRESHOLD,
        risk_threshold: str = "high",
        input_func: Callable = input,
        output_func: Callable = print,
    ):
        self.mode = mode
        self.risk_threshold = risk_threshold
        self._input = input_func
        self._output = output_func
        self.records: List[ApprovalRecord] = []

    def requires_approval(self, stage_name: str, risk_level: str = "low") -> bool:
        """判断阶段是否需要审批"""
        if self.mode == ApprovalMode.AUTO:
            return False
        if self.mode == ApprovalMode.INTERACTIVE:
            return True
        if self.mode == ApprovalMode.THRESHOLD:
            risk_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            return risk_order.get(risk_level, 0) >= risk_order.get(self.risk_threshold, 1)
        return False

    def ask(self, stage_name: str, summary: str,
            risk_level: str = "low") -> ApprovalRecord:
        """执行审批询问"""
        if not self.requires_approval(stage_name, risk_level):
            record = ApprovalRecord(
                stage=stage_name,
                decision=ApprovalDecision.APPROVE,
                reason=f"自动通过 (模式: {self.mode.value})"
            )
            self.records.append(record)
            return record

        self._output(f"\n{'='*60}")
        self._output(f"🔴 审批节点: {stage_name}")
        self._output(f"   风险等级: {risk_level.upper()}")
        self._output(f"   摘要: {summary}")
        self._output(f"{'='*60}")

        while True:
            choice = self._input(
                f"  确认通过并继续？\n"
                f"  [y] 通过  [n] 拒绝(终止)  [s] 跳过此阶段  [d] 查看详情\n"
                f"  [r] 转人工复核(本次不执行该动作)  [q] 退出\n"
                f"  选择: "
            ).strip().lower()

            if choice == 'y':
                decision = ApprovalDecision.APPROVE
                break
            elif choice == 'n':
                decision = ApprovalDecision.REJECT
                break
            elif choice == 's':
                decision = ApprovalDecision.SKIP
                break
            elif choice == 'r':
                # REVIEW：本次不执行该动作，交给人工线下复核。
                # 此前该枚举值声明了却没有任何产生路径（ask() 永不返回它）。
                decision = ApprovalDecision.REVIEW
                self._output("  ⏸️ 已标记待人工复核；本次不执行该动作，闭环继续但跳过它。")
                break
            elif choice == 'd':
                self._output(f"  📋 完整上下文: {summary}")
                continue
            elif choice == 'q':
                self._output("🛑 用户退出流程")
                sys.exit(0)
            else:
                self._output("  请输入 y/n/s/d/r/q")

        record = ApprovalRecord(
            stage=stage_name,
            decision=decision,
            reason=f"用户手动选择: {choice}"
        )
        self.records.append(record)

        if decision == ApprovalDecision.REJECT:
            approved = len([r for r in self.records
                           if r.decision == ApprovalDecision.APPROVE])
            self._output(f"⛔ 用户拒绝 {stage_name}，流程终止。")
            self._output(f"   已通过的审批: {approved} 条")

        return record

    def summary(self) -> Dict:
        """输出审批摘要（对标原型的 spa['approvals']）"""
        return {
            "total_gates": len(self.records),
            "approved": len([r for r in self.records
                           if r.decision == ApprovalDecision.APPROVE]),
            "rejected": len([r for r in self.records
                           if r.decision == ApprovalDecision.REJECT]),
            "skipped": len([r for r in self.records
                          if r.decision == ApprovalDecision.SKIP]),
            "records": [
                {
                    "stage": r.stage,
                    "decision": r.decision.value,
                    "timestamp": r.timestamp,
                    "reason": r.reason,
                }
                for r in self.records
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.summary(), indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 管道终止异常
# ═══════════════════════════════════════════════════════════════

class PipelineTerminatedError(Exception):
    """用户审批拒绝导致管道终止"""
    pass


# ═══════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════

def create_approval_gate(mode: str) -> ApprovalGate:
    """从 CLI 参数创建审批门控"""
    mode_map = {
        "interactive": ApprovalMode.INTERACTIVE,
        "auto": ApprovalMode.AUTO,
        "threshold": ApprovalMode.THRESHOLD,
    }
    # 未知取值回落到 THRESHOLD 而非 AUTO：宁可多问一次，也不要静默全放行
    return ApprovalGate(mode=mode_map.get(mode, ApprovalMode.THRESHOLD))
