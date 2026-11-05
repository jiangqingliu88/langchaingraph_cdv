"""取数层 —— 模型与 case 列表从哪来、case 属性表往哪去。

设计模式：**Repository**（loader / case_list）+ **Strategy**（exporters）。
上层只拿「已解析好的领域对象」，不关心 YAML 长什么样、别名怎么归一。
"""
from __future__ import annotations

from .loader import (load_model, load_model_from_text, load_models,
                     load_models_from_text, model_from_dict, models_from_dict)

__all__ = ["load_model", "load_model_from_text", "model_from_dict",
           "load_models", "load_models_from_text", "models_from_dict"]
