"""测试点 IR —— **框架的公共门面**。

实现已经收进 `framework/`（阶段 + 注册表 + 流水线）。本模块只保留两件事：

  1. **向后兼容的入口** —— `build_testpoints` / `run_testpoints` /
     `testpoints_yaml` 的签名与产物形状不变；
  2. **命名契约的再导出** —— `tp_id_for` / `attribute_test_name` /
     `iter_value_points` 被 `api` 与测试直接引用。

## 为什么还要这一层

框架是"给实现者用的"，`plan` 是"给调用方用的"。上游（verify / find_spec_yaml /
CLI）不该知道流水线里有几个阶段、realization 是怎么注册的 —— 它们只调
`run_testpoints()`，拿一份稳定的 YAML/JSON 契约。

## 包内结构

    framework/
      contracts.py     阶段契约 / 上下文 / 注册表
      model.py         Realization / Execution / TestPoint（稳定数据形状）
      naming.py        tp_id / test 类名 / 整型投影
      realization.py   realization 策略注册表（stimulus / sequence / observe）
      stages.py        decompose → trace → realize → execute
      pipeline.py      MethodologyPipeline / MethodBundle / manifest
      constraints.py   约束编译器注册表（associate 用）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .framework import (DEFAULT_STAGE, FRAMEWORK_NAME, FRAMEWORK_VERSION,
                        KIND_OBSERVE, KIND_SEQUENCE, KIND_STIMULUS,
                        MethodologyPipeline, MethodBundle, REALIZATIONS,
                        STAGE_BY_PRIORITY, TestPoint, attribute_test_name,
                        int_value_of, iter_value_points, tp_id_for,
                        unique_tp_id)
from .framework.naming import attr_class_slug, ascii_slug

#: 兼容旧名字：`plan.REALIZATION_KINDS` 曾是内置 kind 的元组。
REALIZATION_KINDS = (KIND_STIMULUS, KIND_SEQUENCE, KIND_OBSERVE)


def build_bundle(model: Any, *, env_name: str = "",
                 agents: Optional[Dict[str, List[str]]] = None,
                 module_name: str = "", coverage: Any = "auto",
                 max_tests: Optional[int] = None) -> MethodBundle:
    """跑框架流水线，拿**完整产物包**（含 manifest）。

    需要写 `coverage/methodology.json` 的调用方用这个；只要 payload 的用
    `build_testpoints`。
    """
    return MethodologyPipeline().run(
        model, env_name=env_name, agents=agents, module_name=module_name,
        coverage=coverage, max_tests=max_tests)


def build_testpoints(model: Any, *, env_name: str = "",
                     agents: Optional[Dict[str, List[str]]] = None,
                     module_name: str = "dut",
                     max_tests: Optional[int] = None) -> Dict[str, Any]:
    """`CaseModel` → 测试点 IR payload（**旧接口，形状不变**）。

    `env_name` 决定属性 test 的类名；不给就按 `{object}_env` 推。
    `agents` = `{agent 名: [事务字段名]}`，用来把 stimulus 解析到具体 agent。
    """
    bundle = build_bundle(model, env_name=env_name, agents=agents,
                          module_name=module_name, max_tests=max_tests)
    return bundle.to_dict()


def testpoints_yaml(payload: Dict[str, Any]) -> str:
    """payload → YAML 文本（`coverage/testpoints.yaml` 的正文）。

    **与 `MethodBundle.testpoints_yaml()` 共用一份实现** —— manifest 里的
    IR 哈希算的就是这份文本；两处各写一份会让"哈希 ≠ 实际文件"。
    """
    from .framework.serialize import testpoints_yaml as _impl

    return _impl(payload)


def run_testpoints(yaml_text: str, *, env_name: str = "",
                   agents: Optional[Dict[str, List[str]]] = None,
                   module_name: str = "",
                   max_tests: Optional[int] = None) -> Dict[str, Any]:
    """`case 模型` 文本 → 测试点 IR（API / CLI 入口）。

    纯函数、零 LLM 依赖 —— 测试点是**模型推出来的**，不是模型编出来的。
    payload 里额外带 `methodology`（阶段/计数/输入/IR 哈希），供签核落盘。
    """
    from .domain import CaseModelError
    from .repository import load_models_from_text

    try:
        models = load_models_from_text(yaml_text, source="<testpoints>")
    except CaseModelError as exc:
        return {"error": str(exc)}
    if not models:
        return {"error": "case 模型里没有任何对象"}

    bundle = build_bundle(models[0], env_name=env_name, agents=agents,
                          module_name=module_name, max_tests=max_tests)
    payload = bundle.to_dict()
    payload["testpoints_yaml"] = testpoints_yaml(payload)
    payload["methodology"] = bundle.manifest()
    return payload
