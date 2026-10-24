"""验证阶段进度趋势 —— 读一份 YAML 进度模型，吐可绘制的折线序列。

本包**零 Qt 依赖**：它把 `trend.yaml` 归一化成「哪些阶段、每轮的值是多少」，
界面（`src/workbench/modules/vms/trend/`）只负责把它们画成折线。判定与建模
在工具层，界面是只读视图 —— 与 `casemodel_tools` 同一条纪律。

为什么是 YAML 而不是从 pipeline 现采：build 数量与 P0–P3 分层通过数**当前
pipeline 里没有采集**（journal 只有覆盖率与阶段状态）。一份可 diff 的进度
模型能立刻表达「每轮 build 了几次、各优先级测过了多少」，且不碰闭环代码。

    from src.tools.flow.trend_tools import run_trend
    run_trend("config/trend/trend.yaml")
    # → {"stages", "rounds", "build_series", "test_series", "summary", "counts"}
"""
from .api import run_trend

__all__ = ["run_trend"]
