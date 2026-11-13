"""不调 executor 的节点

确定性逻辑：决策引擎、治理门控、人工审批、轮次推进、收尾。
**这一族里不可能出现 LLM 调用** —— 需要 LLM 就去 `nodes/agent/`。
"""
from __future__ import annotations
