"""testpoint / 验证资产跟踪表 —— 读一份 YAML，吐结构化行。

本包**零 Qt 依赖**：它只把 `tracking.yaml` 解析成两张表的行，界面（
`src/workbench/modules/vms/tracking/`）与任何脚本都能直接用。这与
`casemodel_tools` 同一条纪律 —— 判定逻辑在工具层，界面只负责显示。

数据源是 YAML 而不是数据库：跟踪表是**给人看和手改的**，一份可 diff
的文本比一张需要迁移的表更合适（也是本轮设计的明确选择）。

    from src.tools.tracking_tools import run_tracking
    run_tracking("config/tracking/tracking.yaml")
    # → {"project": ..., "testpoints": [...], "assets": [...], "counts": {...}}
"""
from .api import run_tracking

__all__ = ["run_tracking"]
