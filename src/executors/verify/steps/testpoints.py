"""测试点 IR 的预计算 / 构建 / 落盘（Phase 2.1）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

from src.executors.verify.ir_artifacts import (
    attach_tp_constraints, enrich_case_ir, load_resource_docs, testpoint_files,
    write_contract_build, write_resource_artifacts, write_verification_ir,
)

logger = structlog.get_logger()


class TestpointSteps:
    def _prebuild_testpoints(self, output_dir: Path, case_model: Path,
                             module_name: str) -> Optional[Dict[str, Any]]:
        """env 渲染前的**只算不写**版本：失败返回 None（位图/timing 不生成）。"""
        if case_model is None:
            return None
        payload = self._build_testpoints(output_dir, case_model, module_name)
        if payload.get("error"):
            logger.warning(f"测试点 IR 预计算失败（位图/timing 不生成）: "
                           f"{payload['error']}")
            return None
        return payload

    def _build_testpoints(self, output_dir: Path, case_model: Path,
                          module_name: str) -> Dict[str, Any]:
        """case 模型 → 测试点 IR payload（**只算不写**）。

        `verify` 在 env 渲染**之前**就要它（`tp_seen` 位图/timing 信号要进覆盖率
        接口），而 IR 的落盘要等 `_write_testpoints`。两份共用这一份 payload，
        避免"渲染用的 TP 集合"与"落盘的 TP 集合"各算一遍、可能漂。
        """
        from src.tools.generation.casemodel_tools.api import run_testpoints

        return run_testpoints(
            case_model.read_text(encoding="utf-8", errors="replace"),
            env_name=f"{module_name}_env",
            agents=self._agent_transaction_fields(output_dir) or None,
            module_name=module_name,
            max_tests=200)

    def _write_intent_claims(self, output_dir: Path, case_ir: Dict[str, Any],
                             module_name: str) -> Dict[str, Any]:
        """A：语义映射（Intent）与待证明结论（Claim）—— 只产候选，不改判定。"""
        try:
            from src.layers.l3_decision.claims import write_claims
            from src.layers.l3_decision.intent import load_intents, write_intents

            summary = write_intents(output_dir, case_ir, module=module_name)
            claims = write_claims(output_dir, load_intents(output_dir))
            logger.info(f"Intent：{summary['total']} 条（确认 {summary['confirmed']}"
                        f" / 候选 {summary['candidate']}）→ coverage/intents.json；"
                        f"Claim：{claims['total']} 条 → coverage/claims.json")
            return {"intents": summary, "claims": claims}
        except Exception as e:                         # noqa: BLE001 旁路
            logger.warning(f"Intent/Claim 生成失败（不影响生成）: {e}")
            return {}

    def _prepare_resource_artifacts(self, output_dir: Path, module_name: str,
                                    case_model: Path) -> Dict[str, Any]:
        """渲染前落盘资源模型/场景（env 据此生成 resource checker）。"""
        docs = write_resource_artifacts(output_dir, module_name, case_model)
        if docs.get("available"):
            logger.info(f"资源模型：{docs['resources']} 资源 / "
                        f"{docs['scenarios']} 条交互场景（渲染前落盘）")
        return docs

    def _resource_docs(self, output_dir: Path, module_name: str,
                       case_model: Path) -> Dict[str, Any]:
        """复用渲染前已落盘的资源产物；没有才补写（单独跑这一步时）。"""
        docs = load_resource_docs(output_dir)
        if not docs.get("available"):
            docs = write_resource_artifacts(output_dir, module_name, case_model)
        if docs.get("available"):
            logger.info(f"资源模型：{docs['resources']} 资源 / "
                        f"{docs['scenarios']} 条交互场景")
        return docs

    def _write_stimulus_plan(self, output_dir: Path, payload: Dict[str, Any],
                             module_name: str,
                             resource_scenarios: list = None) -> Dict[str, Any]:
        """落 `coverage/stimulus_plan.json`（generated 是当前唯一可执行后端）。

        player runtime 未实现时 `ensure_backend_executable` 会显式报错，
        不静默换后端。资源场景作为附加段并入 plan（P2）。
        """
        try:
            from src.tools.generation.casemodel_tools.framework.stimulus_plan import (
                DEFAULT_BACKEND, build_and_write)

            plan = build_and_write(
                payload.get("testpoints") or [], output_dir,
                backend=DEFAULT_BACKEND, module=module_name,
                resource_scenarios=resource_scenarios)
            logger.info(f"StimulusPlan：{plan['planned']} 条可激励 / "
                        f"{plan['unsupported']} 条不适用"
                        f"（backend={plan['backend']}；"
                        f"resource_scenarios={len(resource_scenarios or [])}）")
            return plan
        except Exception as e:                         # noqa: BLE001 旁路
            logger.warning(f"StimulusPlan 生成失败: {e}")
            return {}

    def _write_testpoints(self, output_dir: Path, case_model: Path,
                          module_name: str,
                          *, payload: Dict[str, Any] = None) -> List[str]:
        """落 `coverage/testpoints.yaml` + `.json` —— 测试点 IR 的唯一落点。

        **为什么落在 `coverage/`**：它与覆盖报告同性质（都是签核材料），而且
        `inputs/yaml/uvm/` 会被 `find_spec_yaml` 清空（见 `layout.casemodel_path`
        的注释）。放在 coverage 下，证据包 `dump` 会连同覆盖率一起收走。

        `payload` 由 `_build_testpoints` 预计算（env 渲染前要用）；不传则现算。
        """
        try:
            # **与 `_casemodel_test_lines` 的 200 条上限同一口径**：那边截断后
            # 不会生成更多属性 test 类，TP 这边若还列着"有 test 名但没类"的
            # 条目，报告就会出现永远 NOT_RUN 的幽灵测试点。
            if payload is None:
                payload = self._build_testpoints(output_dir, case_model, module_name)
            if payload.get("error"):
                logger.warning(f"测试点 IR 生成失败: {payload['error']}")
                return []
            # **第四集合**：约束归属写进 Case IR 与 TP IR（并重算 YAML 哈希）。
            payload = attach_tp_constraints(payload, output_dir)
            cov_dir = output_dir / "coverage"
            cov_dir.mkdir(parents=True, exist_ok=True)
            # **必须 `newline="\n"`**：Windows 的文本模式会把 `\n` 翻成 `\r\n`，
            # 而 manifest 里的 sha256 算的是 LF 那份 —— 不锁换行符，哈希与实际
            # 落盘文件永远对不上（实测），证据链就成了摆设。
            from src.core.runtime.atomic import atomic_write_json, atomic_write_text

            atomic_write_text(cov_dir / "testpoints.yaml",
                              payload["testpoints_yaml"])
            atomic_write_json(cov_dir / "testpoints.json", payload)
            # P2：资源/交互模型（有 `resources.yaml` 声明才落，不编造资源）。
            # 渲染前通常已落盘（env 要据此生成 checker）；没有才补写。
            _res = self._resource_docs(output_dir, module_name, case_model)
            # ── StimulusPlan IR：generated / player 两个后端的公共前置层 ──
            self._write_stimulus_plan(output_dir, payload, module_name,
                                      _res.get("scenario_docs") or None)
            # **自证**：manifest 说这份 IR 的哈希是 X，落盘字节就得是 X。
            # 哈希对不上时证据链是假的 —— 宁可日志里响一声，也不让它静默过去。
            _want = ((payload.get("methodology") or {}).get("artifacts") or {}) \
                .get("testpoints_yaml", {}).get("sha256", "")
            if _want:
                import hashlib
                _got = hashlib.sha256(
                    (cov_dir / "testpoints.yaml").read_bytes()).hexdigest()
                if _got != _want:
                    logger.warning(
                        f"测试点 IR 哈希与 manifest 不一致：文件 {_got[:12]}… / "
                        f"manifest {_want[:12]}…（落盘编码/换行被改过？）")
            # 框架清单：阶段、计数、输入、IR 哈希 —— 与证据链同一纪律。
            if payload.get("methodology"):
                (cov_dir / "methodology.json").write_text(
                    json.dumps(payload["methodology"], ensure_ascii=False, indent=2),
                    encoding="utf-8")
            # Case IR：CCAT/CASE 身份随 TP 一起落盘（`coverage/case_ir.json`）。
            # 它是**身份来源**，下游（回归任务 / 证据聚合 / 视图）只读不改。
            from src.tools.common.lib.case_meta import write_case_ir

            # **约束归属**：case = groups[] + sva[] + scb[] + constraints[]。
            # 归属按 coverage plan 的策略维度交集算；契约哈希因此覆盖"这条
            # 用例依赖哪条约束"—— 约束换了版本，证据就不再对得上。
            case_ir = enrich_case_ir(output_dir, payload.get("case_ir") or {})
            _ci = write_case_ir(cov_dir, case_ir, payload.get("case_maps") or {})
            # **引用闭合**：读数落 `coverage/case_closure.json`，由 Case Gate 判。
            try:
                from src.executors.verify.ir_artifacts import write_case_closure

                _closure = write_case_closure(output_dir, case_ir, case_model,
                                              module_name)
                if not _closure["ok"]:
                    logger.warning(
                        f"Case IR 引用闭合：{len(_closure['errors'])} 条错误"
                        f"（见 coverage/case_closure.json）")
            except Exception as _ce:                   # noqa: BLE001 旁路
                logger.warning(f"引用闭合检查失败（不影响生成）: {_ce}")
            if _ci.get("path"):
                logger.info(f"Case IR：{_ci['cases']} 条用例 / "
                            f"{_ci['categories']} 个分类（声明 {_ci['declared']}、"
                            f"合成 {_ci['synthesized']}）· 四集合 "
                            f"group={_ci['groups']} sva={_ci['sva']} scb={_ci['scb']} "
                            f"constraints={_ci.get('constraints', 0)}"
                            f" → coverage/case_ir.json")
            # P1：五域统一 IR（case_ir 仍是身份源；IR 只是可校验的统一视图）。
            # D4 域复用 P2 的资源模型 —— 一处编译，两处引用。
            _vir = write_verification_ir(output_dir, case_ir, payload,
                                         resources=_res.get("model") or {})
            if _vir:
                logger.info(f"Unified IR：{_vir['ir_id']} · "
                            f"{_vir['relations']} 条关系 / "
                            f"{_vir['testpoints']} 条 TP → coverage/verification_ir.json")
            # A：语义映射与待证明结论（候选状态，不冒充事实）。
            self._write_intent_claims(output_dir, case_ir, module_name)
            # M1：契约是**构建物** —— 写完 case_ir 立刻编译，ops 前置校验它。
            write_contract_build(output_dir, case_ir)
        except Exception as e:                       # noqa: BLE001 旁路，别拦主流程
            logger.warning(f"测试点 IR 落盘失败: {e}")
            return []
        kinds = "、".join(f"{k}={v}" for k, v in sorted(payload["by_kind"].items()))
        logger.info(f"测试点 IR：{payload['count']} 条（{kinds}；"
                    f"观测型 {payload['observe_only']} 条）→ coverage/testpoints.yaml")
        for note in payload.get("notes") or []:
            logger.info(f"  测试点注意: {note}")
        return testpoint_files(output_dir)
