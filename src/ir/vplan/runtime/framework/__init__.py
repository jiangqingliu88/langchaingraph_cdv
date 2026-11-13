"""SignOffAI 方法学框架 —— 用例建模到测试点/约束/执行的**可组合流水线**。

对外只用从这里取名字：

    from src.ir.vplan.runtime.framework import MethodologyPipeline, REALIZATIONS

    bundle = MethodologyPipeline().run(model, env_name="...", agents={...})
    bundle.testpoints / bundle.summary / bundle.manifest()

扩展点：
  · `REALIZATIONS.register("backdoor")` —— 新增一种"取值怎么进仿真"；
  · `MethodologyPipeline().insert(stage, after="decompose")` —— 新增一个阶段；
  · `framework.constraints.CONSTRAINT_COMPILERS` —— 新增一种约束编译器。
"""
from __future__ import annotations

from .contracts import (PipelineContext, Registry, Stage, StageRecord)
from .model import (BUILTIN_KINDS, KIND_OBSERVE, KIND_SEQUENCE, KIND_STIMULUS,
                    Execution, Realization, TestPoint)
from .naming import (ascii_slug, attr_class_slug, attribute_test_name,
                     int_value_of, iter_value_points, tp_id_for,
                     unique_tp_id)
from .pipeline import (DEFAULT_STAGES, FRAMEWORK_NAME, FRAMEWORK_VERSION,
                       MethodBundle, MethodologyPipeline)
from .realization import (REALIZATIONS, RealizationRequest, RealizationStrategy,
                          resolve_realization, validate_bundled_kinds)
from .stages import (DEFAULT_STAGE, STAGE_BY_PRIORITY, DecomposeStage,
                     ExecuteStage, RealizeStage, TraceStage, stage_for)

__all__ = [
    # 契约
    "Registry", "Stage", "PipelineContext", "StageRecord",
    # 数据模型
    "Realization", "Execution", "TestPoint",
    "KIND_STIMULUS", "KIND_SEQUENCE", "KIND_OBSERVE", "BUILTIN_KINDS",
    # 命名
    "ascii_slug", "attr_class_slug", "attribute_test_name", "int_value_of",
    "iter_value_points", "tp_id_for", "unique_tp_id",
    # 流水线
    "MethodologyPipeline", "MethodBundle", "DEFAULT_STAGES",
    "FRAMEWORK_NAME", "FRAMEWORK_VERSION",
    # realization
    "REALIZATIONS", "RealizationStrategy", "RealizationRequest",
    "resolve_realization", "validate_bundled_kinds",
    # 内置阶段
    "DecomposeStage", "TraceStage", "RealizeStage", "ExecuteStage",
    "STAGE_BY_PRIORITY", "DEFAULT_STAGE", "stage_for",
]
