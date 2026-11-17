"""兼容入口：VPlan IR 类型已并入 `mental_ir_plane.unified.vplan_types`。

执行层仍从这里 import；融合 IR 权威只在 `mental_ir_plane`。
"""
from src.mental_ir_plane.unified.vplan_types import *  # noqa: F401,F403
from src.mental_ir_plane.unified.vplan_types import __all__  # noqa: F401
