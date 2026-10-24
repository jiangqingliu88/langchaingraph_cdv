"""工具绑定层 —— 本文件**不需要 Qt**：`bridge/` 不该把界面拖进来。"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ..bridge.binding import (ToolBinding, ToolError, ToolRegistry, UnknownTool,
                              normalize, payload_error, rows_of, scalar_rows)
from ..bridge.catalog import BINDINGS, bindings, by_name, default_registry


@pytest.fixture
def registry():
    return default_registry()


class TestCatalog:
    def test_catalog_has_no_duplicate_names(self):
        names = [b.name for b in BINDINGS]
        assert len(names) == len(set(names))

    def test_every_binding_has_a_dotted_target(self):
        for binding in BINDINGS:
            assert ":" in binding.target, binding.name

    def test_bindings_returns_a_copy(self):
        table = bindings()
        table.clear()
        assert len(BINDINGS) > 0        # 改副本不该影响目录

    def test_by_name_finds_and_misses(self):
        assert by_name("debug.fingerprint_error") is not None
        assert by_name("nope") is None

    def test_the_impure_bindings_are_exactly_the_vetted_ones(self):
        """非纯的那几条必须**逐个说得出来**。

        这条原来写的是「目前全部是纯的，哪天登记了非纯的会提醒改测试」—— 它确实
        提醒了（加 pipeline.start / cancel 时红的）。现在的形态要求：非纯的清单
        被显式写下来，多一条少一条都得先改这里，等于强迫人回答
        「这个新工具凭什么可以因为切个标签页就跑」。

        口径是**「有副作用或有成本」**，不只是「贵」——`evidence.record_human_edit`
        就是加进来之后才发现这条名字该改的：它很快，但它**写盘**。切个标签页顺手
        往证据链里写一条，比跑一次慢查询更糟，因为它是**不可逆**的。
        """
        impure = sorted(b.name for b in BINDINGS if not b.pure)
        assert impure == ["coverage.approve_exclude", "coverage.reject_exclude",
                          "evidence.record_human_edit",
                          # 生成覆盖率报告：**写盘**（报告落在覆盖率库旁边），
                          # 而且要起一个 vcover 子进程。它总是由"点那一格"显式触发。
                          "flow.coverage_report",
                          # ISA 产物落盘：**写盘**，必须显式触发
                          "isa_gen.export",
                          "pipeline.answer_approval", "pipeline.approval_handler",
                          "pipeline.cancel", "pipeline.resume", "pipeline.start"]

    def test_every_non_pure_binding_is_documented(self):
        """非纯的要写清楚为什么 —— 否则下一个人只会看到"它不许调"。"""
        for binding in BINDINGS:
            if not binding.pure:
                assert binding.doc, binding.name


class TestRegistryBasics:
    def test_call_returns_normalized_dict(self, registry):
        result = registry.call(
            "debug.fingerprint_error",
            error_text="ERROR: tb.sv(42): Undefined variable foo")
        assert isinstance(result, dict)
        assert result["fingerprint"]
        assert "classification" in result

    def test_unknown_name_lists_what_is_known(self, registry):
        with pytest.raises(UnknownTool) as info:
            registry.call("debug.nope")
        assert "debug.fingerprint_error" in str(info.value)

    def test_has_and_names(self, registry):
        assert registry.has("casemodel.gaps")
        assert registry.names() == sorted(registry.names())
        assert len(registry) == len(BINDINGS)

    def test_duplicate_registration_of_a_different_binding_is_rejected(self):
        registry = ToolRegistry()
        registry.register(ToolBinding(name="x", target="a.b:c"))
        with pytest.raises(ValueError):
            registry.register(ToolBinding(name="x", target="a.b:d"))

    def test_duplicate_registration_of_the_same_binding_is_fine(self):
        registry = ToolRegistry()
        binding = ToolBinding(name="x", target="a.b:c")
        registry.register(binding)
        registry.register(binding)
        assert len(registry) == 1

    def test_unknown_kind_is_rejected_at_construction(self):
        with pytest.raises(ValueError):
            ToolBinding(name="x", target="a.b:c", kind="magic")

    def test_broken_target_becomes_a_tool_error(self):
        registry = ToolRegistry()
        registry.register(ToolBinding(name="bad", target="no.such.module:fn"))
        with pytest.raises(ToolError):
            registry.call("bad")


class TestImpureGuard:
    """非纯工具不能被「顺手」调用 —— 否则切个标签页就烧一次 LLM/仿真。"""

    @staticmethod
    def _registry():
        registry = ToolRegistry()
        registry.register(ToolBinding(
            name="slow", target="src.tools.common.lib.sim_log:parse_sim_log",
            pure=False))
        return registry

    def test_call_refuses_without_force(self):
        with pytest.raises(ToolError) as info:
            self._registry().call("slow", log_text="")
        assert "显式触发" in str(info.value)

    def test_force_allows_it(self):
        result = self._registry().call("slow", force=True, log_text="")
        assert isinstance(result, dict)


class TestNormalize:
    def test_json_string_is_parsed(self):
        assert normalize('{"a": 1}', "json") == {"a": 1}

    def test_non_json_string_becomes_raw_not_an_exception(self):
        """工具出错时常返回纯文本 —— 那正是要显示出来的时候，不能抛。"""
        result = normalize("boom: something failed", "json")
        assert result["raw"] == "boom: something failed"
        assert "_parse_error" in result

    def test_dict_passes_through(self):
        assert normalize({"a": 1}, "json") == {"a": 1}

    def test_text_kind_stringifies(self):
        assert normalize(12, "text") == "12"

    def test_filesystem_kind_leaves_value_alone(self):
        sentinel = object()
        assert normalize(sentinel, "filesystem") is sentinel

    def test_auto_sniffs_json_looking_strings(self):
        assert normalize('{"a": 1}') == {"a": 1}
        assert normalize("plain text") == "plain text"
        assert normalize("[1, 2]") == [1, 2]


class TestPayloadHelpers:
    def test_payload_error_picks_up_the_message(self):
        assert payload_error({"error": "output_dir not found"}) == "output_dir not found"
        assert payload_error({"logs": []}) is None
        assert payload_error([1, 2]) is None

    def test_payload_error_sees_parse_failures(self):
        assert payload_error({"_parse_error": "bad"}) == "bad"

    def test_rows_of_unwraps_named_list(self):
        assert rows_of({"items": [1, 2]}, key="items") == [1, 2]

    def test_rows_of_treats_a_lone_dict_as_one_row(self):
        assert rows_of({"a": 1, "b": 2, "c": 3}) == [{"a": 1, "b": 2, "c": 3}]

    def test_rows_of_does_not_turn_an_error_into_a_row(self):
        assert rows_of({"error": "nope"}) == []

    def test_scalar_rows_flattens_a_flat_dict(self):
        rows = scalar_rows({"a": 1, "b": [1, 2]})
        assert rows[0] == {"键": "a", "值": "1"}
        assert "[1, 2]" in rows[1]["值"]

    def test_scalar_rows_ignores_non_dicts(self):
        assert scalar_rows([1, 2]) == []


class TestRealToolCalls:
    """真调一次工具 —— 证明绑定表里的路径全都指得着。"""

    def test_sim_log_parse(self, registry):
        result = registry.call("sim.parse_log", log_text="driven: 5\n")
        assert isinstance(result, dict)
        assert result["driven"] == 5

    def test_compile_log_analysis(self, registry):
        result = registry.call("sim.analyze_compile", log_text="** Error: bad\n")
        assert result["status"] == "FAIL"

    def test_missing_output_dir_returns_an_actionable_error(self, registry):
        """目录不存在时工具不抛异常，而是直说 —— 界面要显示的就是这句话。"""
        result = registry.call("debug.collect_sim_log",
                               output_dir="definitely-not-a-real-dir")
        assert "not found" in payload_error(result)

    def test_casemodel_roundtrip(self, registry):
        example = (Path(__file__).resolve().parents[3]
                   / "config" / "casemodel" / "examples" / "cpu_pipeline.yaml")
        if not example.exists():
            pytest.skip("示例模型不在位")
        yaml_text = example.read_text(encoding="utf-8")
        result = registry.call("casemodel.gaps", yaml_text=yaml_text)
        assert result["score"] > 0

    def test_pipeline_readers_are_pure(self, registry):
        """列表页与日志轮询会反复调 —— 不该每次都弹「要不要执行」。"""
        for name in ("pipeline.runs", "pipeline.journal", "pipeline.status",
                     "pipeline.detail"):
            assert registry.get(name).pure, name

    def test_pipeline_starters_require_explicit_trigger(self, registry):
        """启动一次运行会烧 LLM 与 EDA —— 不能因为切了个标签页就发生。"""
        for name in ("pipeline.start", "pipeline.cancel"):
            assert registry.get(name).pure is False, name
            with pytest.raises(ToolError):
                registry.call(name)

    def test_pipeline_readers_return_dicts(self, registry, tmp_path):
        assert isinstance(registry.call("pipeline.runs"), dict)
        assert registry.call("pipeline.journal", run_id="nope")["events"] == []
        assert registry.call("pipeline.status")["run_id"] == ""

    def test_casemodel_uvm_tests_exports_a_paste_ready_fragment(self, registry):
        """把属性取值摊平成 UVM 的 `environment.tests` 片段 —— 产物是一段 YAML，
        直接贴进 env 清单即可（两个工具之间只有文件格式契约）。"""
        example = (Path(__file__).resolve().parents[3]
                   / "config" / "casemodel" / "examples" / "fc_flowcontrol.yaml")
        if not example.exists():
            pytest.skip("示例模型不在位")
        result = registry.call("casemodel.uvm_tests",
                               yaml_text=example.read_text(encoding="utf-8"))
        assert result["count"] > 0
        assert yaml.safe_load(result["tests_yaml"])["tests"]
