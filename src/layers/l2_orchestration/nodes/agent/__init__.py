"""经 `_run_agent` 调 executor 的节点

每个节点只做三件事：选哪个 executor、给它什么参数、拿到结果后怎么落状态。
「拿结果之后」那一段（质量校验 + 证据链 + 熔断计数）在 `runtime._run_agent` 里，
**不在节点里** —— 24 个节点各写一遍就会漂。
"""
from __future__ import annotations
