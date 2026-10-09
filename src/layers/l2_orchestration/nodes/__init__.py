"""闭环图的节点 —— 按「节点里有没有 LLM」分两族

    pure/   不碰 executor 的 12 个：决策、治理、审批、轮次、收尾
    agent/  经 `_run_agent` 调 executor 的 12 个：构建、执行、修复、签核

这个划分不是分类癖：它决定了**一个节点会不会烧 token**。改 `pure/` 里的东西
不可能引入 LLM 调用，改 `agent/` 里的就可能 —— 这是能一眼看出来的那种边界。
"""
from __future__ import annotations
