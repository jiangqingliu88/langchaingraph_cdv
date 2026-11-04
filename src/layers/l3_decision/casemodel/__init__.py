"""L3 case 模型门面 —— 新代码从这里导入，旧路径在 Phase 4 前保留。"""
from src.tools.generation.casemodel_tools.domain import (
    CaseModel, CaseModelError,
)
from src.tools.generation.casemodel_tools.repository import (
    load_model, load_model_from_text, load_models, load_models_from_text,
)

__all__ = [
    "CaseModel", "CaseModelError", "load_model", "load_model_from_text",
    "load_models", "load_models_from_text",
]
