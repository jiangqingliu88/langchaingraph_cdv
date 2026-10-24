"""方法学框架 —— 契约、注册表、流水线、manifest。

这里钉的是**框架性质**，不是某一条测试点：

  ① 阶段按声明顺序跑，依赖缺失在启动前报错；
  ② 新增 realization kind **不改核心阶段**（注册即可）；
  ③ manifest 记录阶段/计数/输入/IR 哈希；
  ④ `plan` 门面的产物与流水线**逐字一致**（向后兼容）。
"""
from __future__ import annotations

import yaml

from src.tools.generation.casemodel_tools import plan
from src.tools.generation.casemodel_tools.framework import (KIND_OBSERVE, REALIZATIONS,
                                                 MethodologyPipeline,
                                                 Realization, RealizationStrategy,
                                                 Stage, validate_bundled_kinds)
from src.tools.generation.casemodel_tools.repository import load_models_from_text
from src.tools.generation.casemodel_tools.tests.conftest import FC

FC_TEXT = FC.read_text(encoding="utf-8")


def _model_with_custom_kind(text: str) -> object:
    doc = yaml.safe_load(text)
    for dim in doc.get("dimensions") or []:
        if dim.get("id") == "D_ratio":
            dim["realization"] = {"kind": "magic"}
            break
    return load_models_from_text(yaml.safe_dump(doc, allow_unicode=True),
                                 source="<test>")[0]


class TestContracts:
    def test_default_stage_order(self):
        assert MethodologyPipeline().stage_names() == [
            "decompose", "trace", "realize", "execute"]

    def test_missing_dependency_fails_before_running(self):
        class NeedsNothing(Stage):
            name = "needs_nothing"
            consumes = ("not_produced",)
            produces = "x"

            def run(self, ctx):  # pragma: no cover - 不该被调用
                raise AssertionError("依赖检查应在阶段运行之前")

        pipe = MethodologyPipeline([NeedsNothing()])
        try:
            pipe.run(_model_with_custom_kind(FC_TEXT))
        except RuntimeError as exc:
            assert "依赖缺失" in str(exc)
        else:
            raise AssertionError("缺依赖没有在启动前报错")

    def test_duplicate_stage_names_are_refused(self):
        from src.tools.generation.casemodel_tools.framework import DecomposeStage

        try:
            MethodologyPipeline([DecomposeStage(), DecomposeStage()])
        except ValueError as exc:
            assert "重复" in str(exc)
        else:
            raise AssertionError("重复阶段名没有被拒绝")

    def test_builtin_kinds_are_all_registered(self):
        assert validate_bundled_kinds() == []


class TestExtensibility:
    def test_a_new_realization_kind_needs_no_core_change(self):
        """注册一个 `magic` 策略 —— 核心阶段一行都不用改。"""
        class Magic(RealizationStrategy):
            kind = "magic"

            def resolve(self, req):
                return Realization(kind="magic",
                                   extras={"path": f"dut.{req.dim.key}"})

        REALIZATIONS.register("magic", Magic())
        try:
            bundle = MethodologyPipeline().run(
                _model_with_custom_kind(FC_TEXT), env_name="fc_env")
            ratio = [tp for tp in bundle.testpoints if tp.dimension == "D_ratio"]
            assert ratio and all(tp.realization.kind == "magic" for tp in ratio)
            assert all(tp.realization.extras["path"] == "dut.D_ratio" for tp in ratio)
            assert not any(tp.observe_only for tp in ratio)
        finally:
            REALIZATIONS.unregister("magic")

    def test_an_unknown_kind_falls_back_to_observe_with_a_note(self):
        doc = yaml.safe_load(FC_TEXT)
        for dim in doc.get("dimensions") or []:
            if dim.get("id") == "D_ratio":
                dim["realization"] = {"kind": "teleport"}
        model = load_models_from_text(yaml.safe_dump(doc, allow_unicode=True),
                                      source="<test>")[0]
        bundle = MethodologyPipeline().run(model, env_name="fc_env")
        ratio = [tp for tp in bundle.testpoints if tp.dimension == "D_ratio"]
        assert all(tp.realization.kind == KIND_OBSERVE for tp in ratio)
        assert any("teleport" in n for n in bundle.notes)

    def test_a_stage_can_be_inserted_after_another(self):
        class Mark(Stage):
            name = "mark"
            consumes = ("testpoints",)
            produces = "testpoints"

            def run(self, ctx):
                ctx.notes.append("mark-stage-ran")

        pipe = MethodologyPipeline().insert(Mark(), after="trace")
        assert pipe.stage_names() == ["decompose", "trace", "mark", "realize", "execute"]
        bundle = pipe.run(load_models_from_text(FC_TEXT, source="<test>")[0],
                          env_name="fc_env")
        assert "mark-stage-ran" in bundle.notes

    def test_insert_after_unknown_stage_is_an_error(self):
        try:
            MethodologyPipeline().insert(_Marker(), after="nope")
        except KeyError as exc:
            assert "nope" in str(exc)
        else:
            raise AssertionError("插到不存在的阶段之后没有被拒绝")


class _Marker(Stage):
    name = "marker"
    produces = "marker"

    def run(self, ctx):  # pragma: no cover
        pass


class TestConstraintCompilerRegistry:
    def test_a_new_compiler_can_be_registered(self):
        from src.tools.generation.casemodel_tools.framework.constraints import (
            CONSTRAINT_COMPILERS, ConstraintRequest, compile_assignments)

        class Noop:
            name = "noop"

            def compile(self, req):
                return [{"trans": "a", "field": "f", "values": [0], "mode": "cycle"}]

        CONSTRAINT_COMPILERS.register("noop", Noop())
        try:
            req = ConstraintRequest(theme_key="T", method="D", dims=[], ports=[])
            assert compile_assignments(req, compiler="noop")[0]["field"] == "f"
        finally:
            CONSTRAINT_COMPILERS.unregister("noop")

    def test_an_unknown_compiler_is_an_error_not_silent_empty(self):
        from src.tools.generation.casemodel_tools.framework.constraints import (
            ConstraintRequest, compile_assignments)

        req = ConstraintRequest(theme_key="T", method="D", dims=[], ports=[])
        try:
            compile_assignments(req, compiler="nope")
        except KeyError as exc:
            assert "nope" in str(exc)
        else:
            raise AssertionError("未知编译器没有被拒绝")


class TestManifest:
    def test_manifest_records_stages_counts_and_hash(self):
        bundle = MethodologyPipeline().run(
            load_models_from_text(FC_TEXT, source="<test>")[0], env_name="fc_env")
        m = bundle.manifest()
        assert [s["name"] for s in m["stages"]] == [
            "decompose", "trace", "realize", "execute"]
        assert m["summary"]["count"] == bundle.count
        assert m["summary"]["by_kind"] == bundle.by_kind()
        assert len(m["artifacts"]["testpoints_yaml"]["sha256"]) == 64
        assert m["framework"] == "signoff-methodology"
        assert m["inputs"]["env_name"] == "fc_env"

    def test_manifest_hash_is_stable_for_the_same_input(self):
        model = load_models_from_text(FC_TEXT, source="<test>")[0]
        a = MethodologyPipeline().run(model, env_name="fc_env").manifest()
        b = MethodologyPipeline().run(model, env_name="fc_env").manifest()
        assert a["artifacts"] == b["artifacts"]

    def test_manifest_hash_matches_the_bytes_we_write(self):
        """manifest 的哈希必须等于**实际落盘的 testpoints.yaml**。

        两处各写一份序列化就会出现"哈希 ≠ 文件"—— 那会让证据链失去意义。
        """
        import hashlib

        bundle = MethodologyPipeline().run(
            load_models_from_text(FC_TEXT, source="<test>")[0], env_name="fc_env")
        payload = bundle.to_dict()
        written = plan.testpoints_yaml(payload).encode("utf-8")
        digest = hashlib.sha256(written).hexdigest()
        assert bundle.manifest()["artifacts"]["testpoints_yaml"]["sha256"] == digest
        assert plan.testpoints_yaml(payload) == bundle.testpoints_yaml()


class TestBackwardCompatibility:
    def test_plan_facade_matches_the_pipeline(self):
        model = load_models_from_text(FC_TEXT, source="<test>")[0]
        bundle = MethodologyPipeline().run(model, env_name="fc_env",
                                           module_name="fc")
        payload = plan.build_testpoints(model, env_name="fc_env", module_name="fc")
        assert payload == bundle.to_dict()

    def test_facade_payload_carries_the_manifest(self):
        payload = plan.run_testpoints(FC_TEXT, env_name="fc_env")
        assert payload["methodology"]["summary"]["count"] == payload["count"]
        assert payload["testpoints_yaml"].startswith("# ===")
