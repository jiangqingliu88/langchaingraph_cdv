"""参考模型产出总览 —— model agent 这次做了什么。

本文件只有 `ROLE` 一行实质内容 —— 视图本身是跨线共享件
（`modules/agent_output.py`）。一条线一个文件，是为了让
「看到清单里 `group: model` 就知道代码在 `modules/model/`」这条约定继续成立。
"""
from __future__ import annotations

from ..agent_output import AgentOutputModule


class ModelOutputModule(AgentOutputModule):
    """`model` agent 的产出总览。"""

    ROLE = "model"
