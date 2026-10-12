"""流程与证据工具层 —— 目前只有「签核判定」的读取。

本包**零 Qt 依赖、零引擎依赖**：它只读一次运行目录里已经落盘的两份文件，
把「能不能签核」拼成一个可显示的模型：

    report.json          （audit agent 写）  → 四道门禁 + verdict
    docs/evidence_chain.json（n_finalize 写）→ 六层领域证据链 + signoff_ready

> 为什么放在 `src/tools/` 而不是 `src/layers/`：它不调用任何引擎，只做
> 「磁盘 JSON → 结构化 dict」这一件事 —— 与 `trend_tools`
> 同一条纪律（工具层只放纯函数）。界面（`src/workbench/modules/vms/signoff/`）
> 是它的只读视图。

**不做的事（诚实标注）**：治理状态（预算 / 熔断 / 干预）**不在本包**。
`Governor` 是运行线程里 `Runtime` 的一个字段（`execution.py:606`），既不落盘
也没有对外访问口 —— 拿不到真数据就不画，见 docs/design/agent_gui_business_architecture.md §1.3。

    from src.tools.flow_tools import run_signoff
    run_signoff("output/apb_uart")
    # → {"verdict", "gates": [...], "chain": {...}, ...}
"""
from .api import (ROLE_TITLES, UVM_SCHEMA, run_agent_outputs, run_artifacts,
                  run_decision_trace, run_manifest_info, run_signoff, run_task)

__all__ = ["run_signoff", "run_task", "run_agent_outputs",
           "run_decision_trace", "run_manifest_info", "run_artifacts",
           "ROLE_TITLES", "UVM_SCHEMA"]
