"""Agent harness —— 显式状态机 + 结果回填 + 会话持久化（对齐 DeepSeek Harness）。

目录即能力：

  · `state.py`       状态机（new→planning→acting→observing→…→done/blocked）
  · `session.py`     会话（messages / working / usage / pending / projection / 恢复）
  · `backfill.py`    工具结果回填（assistant tool_call → tool message → working state）
  · `context.py`     token 估算 + compaction / tool-result pruner
  · `goal.py`        goal + rounds（失败提案进入下一轮）
  · `plan.py`        plan 字段与审批门
  · `tools.py`       ToolSpec 注册表（schema / risk / 审批）
  · `permissions.py` 风险策略（exec 可要求人工批准）
  · `jobs.py`        后台命令（start/output/kill）
  · `skills.py`      文件系统 skill 发现与注入
  · `subagent.py`    受限子 harness
  · `events.py`      JSONL 事件流（UI/审计）
  · `harness.py`     驱动循环
"""
from .harness import Harness, HarnessConfig
from .state import HarnessState, StateMachine

__all__ = ["Harness", "HarnessConfig", "HarnessState", "StateMachine"]
