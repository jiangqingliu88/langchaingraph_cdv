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


def assertion_bindings(model: Any) -> List[Dict[str, Any]]:
    """断言 ↔ 测试点（反向索引的来源）。

    每条断言给出它**实际绑到的** tp_id（模型里写错的不算，单独列 `unknown`）——
    失败归因、TP 矩阵反查、签核报告都从这一份读。
    """
    from .framework.naming import iter_value_points

    known = {tp_id for *_rest, tp_id in iter_value_points(model)}
    out: List[Dict[str, Any]] = []
    for assertion in getattr(model, "assertions", None) or []:
        bound = [b for b in assertion.tp_bindings if b["tp_id"] in known]
        out.append({
            "assertion_id": assertion.id,
            "name": assertion.name,
            # 规则原文与说明：签核视图要能回答"这条 SVA 到底在查什么"，
            # 只给一个 id 等于让人回头翻模型。
            "expr": assertion.expr,
            "message": assertion.message,
            "signals": [s.get("name") if isinstance(s, dict) else str(s)
                        for s in (assertion.signals or [])],
            "tp_ids": [b["tp_id"] for b in bound],
            "roles": {b["tp_id"]: b["role"] for b in bound},
            "unknown": [b["tp_id"] for b in assertion.tp_bindings
                        if b["tp_id"] not in known],
        })
    return out


def _with_config(payload: Dict[str, Any], model: Any) -> Dict[str, Any]:
    """模型没写 `config_space:` → payload 形状与 v1 一致。

    写了的话：每条 TP 挂 `config_instances`（可执行配置组合），摘要里带
    实例总数 —— tp_id 不变，配置是**执行实例维度**，不是新的测试点。
    """
    from .framework.config_space import attach_instances, combination_summary

    summary = combination_summary(model)
    if summary:
        summary["instances_total"] = attach_instances(
            model, payload.get("testpoints") or [])
        payload["config_space"] = summary
    return payload


def _with_assertions(payload: Dict[str, Any], model: Any) -> Dict[str, Any]:
    """模型里没写断言 → payload 形状与 v1 完全一致。"""
    bindings = assertion_bindings(model)
    if bindings:
        payload["assertion_bindings"] = bindings
    return payload


def build_bundle(model: Any, *, env_name: str = "",
                 agents: Optional[Dict[str, List[str]]] = None,
                 module_name: str = "", coverage: Any = "auto",
                 max_tests: Optional[int] = None) -> MethodBundle:
    """跑框架流水线，拿**完整产物包**（含 manifest）。

    需要写 `coverage/methodology.json` 的调用方用这个；只要 payload 的用
    `build_testpoints`。
    """
    bundle = MethodologyPipeline().run(
        model, env_name=env_name, agents=agents, module_name=module_name,
        coverage=coverage, max_tests=max_tests)
    # 行为域（P1a）：行为节点与属性测试点并列进同一份 TP IR。
    from .framework.behavior import compile_behavior

    behavior_tps = compile_behavior(model)
    if behavior_tps:
        bundle.testpoints.extend(behavior_tps)
        bundle.notes.append(
            f"行为域：{len(behavior_tps)} 条 TP 已进 IR（执行后端 P1b 待接）")
    # PATH 组：按指令生命周期切的端到端路径 —— 与功能组并列，一条 bin 一条 TP。
    from .framework.paths import compile_paths

    path_tps = compile_paths(model)
    if path_tps:
        bundle.testpoints.extend(path_tps)
        bundle.notes.append(
            f"PATH 组：{len(path_tps)} 条路径 TP 已进 IR"
            f"（执行后端 P1b 待接；进证据视图，不冒充功能覆盖）")
    # 行为域 / PATH 组的 TP 不走 ExecuteStage（它们没有属性 test 的派生值），
    # 所以在这里补一次身份绑定；随后把 TP 聚合成 **case 三集合契约**。
    _bind_identity_and_contracts(bundle, model)
    return bundle


def _bind_identity_and_contracts(bundle: Any, model: Any) -> None:
    """补 TP 身份 + 三集合，并把它们聚合回 Case IR（失败不挡生成）。

    顺序有讲究：**先身份、后契约** —— 三集合按 `case_id` 归并，身份没定就
    归不到任何 case 名下。
    """
    if not bundle.testpoints:
        return
    try:
        from src.layers.l3_decision.case_ir import (
            attach_contracts, group_id_of, parse_declared, scb_id_of,
            sva_id_of, tst_id_of)
    except Exception:                              # noqa: BLE001 身份层不可用
        return
    doc = parse_declared(bundle.case_doc or {}, module=bundle.module_name)
    if doc.empty:
        return
    # ① 身份：**全量**绑定（一条 TP 可被多条 CASE 共享）。
    #    ExecuteStage 已注入的先用；没有的（行为/PATH）按 test > dimension 兜底。
    for tp in bundle.testpoints:
        test = str(getattr(getattr(tp, "execution", None), "test", "") or "")
        ids = list(getattr(tp, "case_ids", None) or [])
        if not ids and getattr(tp, "case_id", ""):
            ids = [str(tp.case_id)]
        if not ids:
            ids = doc.resolve_all(test=test,
                                  dimension=str(getattr(tp, "dimension", "")))
        tp.case_ids = ids
        tp.case_id = ids[0] if ids else ""
        if not getattr(tp, "tst_id", "") and test:
            tp.tst_id = tst_id_of(test)
    # ② 三集合引用（TP 层）：组 = 维度；SVA = 绑到这条 TP 的断言；
    #    SB = 绑到这条 TP 的 scoreboard（显式 tp_bindings；无绑定的按 checks 聚合）
    assertions = assertion_bindings(model)
    scoreboards = [sb.to_dict() for sb in (getattr(model, "scoreboards", None) or [])]
    sva_by_tp = _checker_map_by_tp(assertions, "assertion_id", sva_id_of)
    scb_by_tp = _checker_map_by_tp(scoreboards, "id", scb_id_of, "tp_bindings")
    for tp in bundle.testpoints:
        tp_id = str(getattr(tp, "tp_id", ""))
        group = group_id_of(getattr(tp, "dimension", ""))
        tp.groups = [group] if group else []
        tp.sva = sorted(set(sva_by_tp.get(tp_id, [])))
        tp.scb = sorted(set(list(getattr(tp, "scb", []) or [])
                            + scb_by_tp.get(tp_id, [])))
    # ③ 聚合回 case 契约（含 required_layers / cell / not_applicable）
    attach_contracts(doc, [tp.to_dict() for tp in bundle.testpoints],
                     assertions, scoreboards)
    # ④ 把 case 层面的 SB 回填到 TP（按 checks 聚合出来的绑定也要落到 TP 上，
    #    否则 task_meta 的 scb_ids 会是空的，回归任务自证不了）。
    _backfill_tp_scb(doc, bundle.testpoints)
    bundle.case_doc = doc.to_dict()


def _checker_map_by_tp(items: List[Dict[str, Any]], id_key: str,
                        id_of, bindings_key: str = "tp_ids") -> Dict[str, List[str]]:
    """checker 列表 → `{tp_id: [checker_id…]}`。

    `bindings_key` 两种形状都认：断言用展开后的 `tp_ids`，scoreboard 用原始
    `tp_bindings[{tp_id, role}]`。
    """
    out: Dict[str, List[str]] = {}
    for item in items or []:
        cid = id_of(item.get(id_key))
        if not cid:
            continue
        if bindings_key == "tp_ids":
            tp_ids = [str(t) for t in (item.get("tp_ids") or []) if t]
        else:
            tp_ids = [str((b or {}).get("tp_id")) for b in
                      (item.get(bindings_key) or []) if isinstance(b, dict)]
        for tp_id in tp_ids:
            if tp_id:
                out.setdefault(tp_id, []).append(cid)
    return out


def _backfill_tp_scb(doc: Any, testpoints: List[Any]) -> None:
    by_id = {str(getattr(tp, "tp_id", "")): tp for tp in testpoints}
    for case in doc.cases:
        for item in case.scb:
            for tp_id in item.get("tp_ids") or []:
                tp = by_id.get(str(tp_id))
                if tp is not None and item["id"] not in tp.scb:
                    tp.scb.append(item["id"])
    for tp in testpoints:
        tp.scb = sorted(set(tp.scb or []))


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
    return _with_config(_with_assertions(bundle.to_dict(), model), model)


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
    payload = _with_config(_with_assertions(bundle.to_dict(), models[0]), models[0])
    payload["testpoints_yaml"] = testpoints_yaml(payload)
    payload["methodology"] = bundle.manifest()
    # Case IR 与 TP 同批产出 —— 身份在生成期定下，下游不再各自投影一次。
    payload["case_ir"] = bundle.case_doc or {}
    _attach_case_maps(payload)
    return payload


def _attach_case_maps(payload: Dict[str, Any]) -> None:
    """补 `case_group_map` / `case_checker_map` 与 `case_ir_sha256`（哈希链）。

    两份 map 是**派生索引**（供 case_view / cell_matrix / 回归任务反查），
    不是第二份契约 —— 契约只有 `case_ir`，哈希也只算它。
    """
    case_ir = payload.get("case_ir") or {}
    if not case_ir.get("cases"):
        return
    import hashlib
    import json as _json

    from src.layers.l3_decision.case_ir import checker_map, group_map, parse_declared

    doc = parse_declared(case_ir)
    if doc.empty:
        return
    payload["case_maps"] = {"group_map": group_map(doc),
                            "checker_map": checker_map(doc)}
    payload["case_ir_sha256"] = hashlib.sha256(
        _json.dumps(case_ir, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    methodology = payload.get("methodology")
    if isinstance(methodology, dict):
        methodology["case_ir_sha256"] = payload["case_ir_sha256"]
