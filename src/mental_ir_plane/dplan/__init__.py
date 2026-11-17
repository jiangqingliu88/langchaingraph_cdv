"""DPlan IR —— 设计与参考模型契约（`dplan_ir_v1`）。

分层位置：与 `model.py` / `unified/` 同属“总”层；它不描述验证义务或执行结果。
"""
from .load import from_dict, load_dplan
from .model import (
    SCHEMA,
    Architecture,
    DesignPlan,
    Feature,
    Interface,
    ModelBehavior,
    ModelContract,
    ModelState,
    Module,
    Register,
)
from .store import read_dplan, write_dplan
from .validate import validate

__all__ = [
    "SCHEMA", "DesignPlan", "Interface", "Register", "Feature", "Module",
    "ModelState", "ModelBehavior", "ModelContract", "Architecture",
    "load_dplan", "from_dict", "read_dplan", "write_dplan", "validate",
]
