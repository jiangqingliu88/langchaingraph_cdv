"""L3 case 模型 —— 实现与门面同包（Phase 4 收尾）。"""
from .domain import CaseModel, CaseModelError
from .repository import (
    load_model, load_model_from_text, load_models, load_models_from_text,
)

__version__ = "2.0"

__all__ = [
    "CaseModel", "CaseModelError", "load_model", "load_model_from_text",
    "load_models", "load_models_from_text", "__version__",
]
