"""流程与证据工具层 —— 读一次运行目录，吐结构化的视图数据。

按域拆到同目录的几个模块，本文件只做**统一入口**（旧导入路径保持不变）：

    _shared.py        共享只读辅助（目录解析 / JSON(JSONL) / 产物体检）
    signoff_api.py    门禁 + 六层证据链 + 总判定
    regression_api.py 回归状态矩阵 + 运行对比
    coverage_api.py   覆盖率汇总 + 功能覆盖率明细
    run_api.py        任务总览 / agent 产出 / 决策轨迹 / 清单 / 产物 / TODO

**数据从哪来**（全部是已经落盘的，不需要重跑、不碰运行中的进程）：
  · `report.json`              —— audit agent 写的四道门禁与 verdict
  · `docs/evidence_chain.json` —— n_finalize 写的六层领域证据链与 signoff_ready
  · `docs/run_events.jsonl`    —— 运行日志（阶段事件自带 `agent`，按 agent 过滤不必
                                  去 import 领域代码）
  · `docs/manifest.json` / `docs/file_change_chain.json`
  · 产物目录（`rtl/` `model/` `sv/` `sim/` `coverage/` …）

**两份来源都要看**：门禁回答"该跑的都跑了吗"，证据链回答"证据链每一层都闭合了吗"。
一份缺失不算错 —— 运行可能还没跑到那一步；如实标 `available: false`，
**不拿空数据冒充通过**（全仓库的"失败响亮"纪律）。

失败**响亮**：目录不在 / 不是一个目录 / 文件不是目录 → `{"error": ...}`，不抛异常。
"""
from __future__ import annotations

from src.layers.l2_orchestration.flow_shared import UVM_SCHEMA  # noqa: F401
from .coverage_api import run_coverage, run_fcov  # noqa: F401
from .regression_api import compare_runs, run_regression_status  # noqa: F401
from .run_api import (  # noqa: F401
    ROLE_TITLES, TODO_KINDS, collect_todos, run_agent_outputs, run_artifacts,
    run_decision_trace, run_manifest_info, run_rule_drafts, run_task,
)
from .signoff_api import (  # noqa: F401
    CHECK_TITLES, GATE_TITLES, LAYER_TITLES, run_signoff,
)

__all__ = [
    "GATE_TITLES", "LAYER_TITLES", "CHECK_TITLES",
    "ROLE_TITLES", "UVM_SCHEMA", "TODO_KINDS",
    "run_signoff", "run_coverage", "run_agent_outputs",
    "run_regression_status", "run_decision_trace", "run_manifest_info",
    "run_task", "run_fcov", "run_artifacts", "compare_runs",
    "collect_todos", "run_rule_drafts",
]
