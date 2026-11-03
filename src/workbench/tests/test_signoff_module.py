"""签核判定模块。

模块的输入是**一次运行目录**（经 `pipeline.detail` 拿 `dir`，再交给 `flow.signoff`）。
测试打桩的是 `run_tool` 这一层 —— 于是 `load()` 的**真实路径**（拿目录 → 调工具 →
填表）被完整覆盖，而不是被测试自己重写一遍。

用 tmp 目录造 `report.json` + `docs/evidence_chain.json`，断言两张表按真实结构
填充、颜色跟着通过/不通过走。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

MODULE_ID = "flow.signoff"


def _shipped_spec():
    from .conftest import shipped_manifest
    manifest, manifest_path = shipped_manifest()
    spec = next(s for s in manifest.modules if s.id == MODULE_ID)
    return spec, manifest, manifest_path


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "report.json").write_text(json.dumps({
        "verdict": "NEEDS_FIX", "pass_rate": "5/6", "coverage": 93.0,
        "signoff_status": "CONDITIONAL",
        "gates": {"rtl_present": True, "rtl_files": ["apb_uart.sv"],
                  "rtl_real": True, "regression_passed": False,
                  "coverage_collected": True, "model_real": False,
                  "model_placeholder_reason": "模板占位"},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "docs" / "evidence_chain.json").write_text(json.dumps({
        "layers": {
            "requirement_layer": {"description": "MD 规格→需求树", "passed": 2, "total": 2,
                                  "checks": {"req_spec_completeness": True,
                                             "req_test_mapping": True}, "evidence": {}},
            "verification_layer": {"description": "需求→UVM 用例", "passed": 1, "total": 4,
                                   "checks": {"case_coverage_P0": True,
                                              "case_coverage_P1": False,
                                              "case_coverage_P2": False,
                                              "case_coverage_P3": True}, "evidence": {}},
        },
        "checks_passed": 3, "checks_total": 6,
        "signoff_ready": False, "overall_status": "FAIL",
    }, ensure_ascii=False), encoding="utf-8")

    # 证据包 v2 + 审批/种子：签核页的“合同级证据”一节
    (root / "signoff_evidence").mkdir()
    (root / "signoff_evidence" / "manifest.json").write_text(json.dumps({
        "schema": "signoff_evidence_v2",
        "package_hash": "a" * 64, "manifest_hash": "b" * 64,
        "files": [{"path": "manifest.json"},
                  {"path": "case_view/gates.json", "source": "coverage/gates.json"}],
        "coverage": {"plan_pct": 95.23, "single_test_pct": 68.57,
                     "code_plan_pct": 75.8, "code_single_pct": 70.9},
        "tp_matrix": {"counts": {"HIT": 37, "MISS": 0}},
        "seed_diversity": {"verdict": "DIVERSE", "seeds": [1, 2],
                           "stable_bins": 12, "variable_bins": 57},
        "sim_reward": {"total": 0.8125, "weakest": "coverage",
                       "weights": {"compile": 0.25, "regression": 0.35,
                                   "coverage": 0.4},
                       "weight_issues": []},
        "knowledge_graph": {"path": "coverage/knowledge_graph.json",
                            "sha256": "d" * 64,
                            "summary": {"nodes": 9, "edges": 8},
                            "gaps": 2},
        "verdict": {"hard_ok": True,
                    "raw_caveats": [{"code": "TP_MISSED"}],
                    "accepted_codes": [], "effective_codes": ["TP_MISSED"],
                    "verdict": "PASS_WITH_CAVEAT"},
        "reference_models": {"available": False},
        "lineage": {"name": "v1"},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "approvals.jsonl").write_text(json.dumps({
        "action": "approve", "approver": "human:test",
        "approval_hash": "c" * 64,
    }) + "\n", encoding="utf-8")
    (root / "signoff_evidence" / "replay").mkdir()
    (root / "signoff_evidence" / "replay" / "recipe.json").write_text(json.dumps({
        "schema": "signoff_replay_recipe_v2",
        "tier_a": {"requires_eda": False, "command": "python replay/replay.py"},
        "tier_b": {"requires_eda": True, "eda_tools": ["vsim", "vcover"]},
    }, ensure_ascii=False), encoding="utf-8")
    (root / "coverage").mkdir(exist_ok=True)
    # Case 证据（三集合）—— 签核页第 4 块
    (root / "coverage" / "gates.json").write_text(json.dumps({
        "schema": "case_gates_v1", "verdict": "BLOCKED",
        "counts": {"blocker": 2, "warning": 1, "info": 0, "total": 3},
    }), encoding="utf-8")
    (root / "coverage" / "cell_matrix.json").write_text(json.dumps({
        "schema": "cell_matrix_v1",
        "counts": {"green": 3, "yellow": 2, "red": 1, "na": 0, "total": 6},
    }), encoding="utf-8")
    (root / "coverage" / "case_ir.json").write_text(json.dumps({
        "schema": "case_ir_v1",
        "counts": {"cases": 4, "groups": 5, "sva": 2, "scb": 1},
    }), encoding="utf-8")
    (root / "coverage" / "evd.json").write_text(json.dumps({
        "schema": "evd_v1", "counts": {"total": 12},
    }), encoding="utf-8")
    (root / "coverage" / "case_cov" / "p1").mkdir(parents=True)
    (root / "coverage" / "case_cov" / "p1" / "t1.json").write_text(
        json.dumps({"schema": "case_cov_v1", "case_id": "CASE-D"}), encoding="utf-8")
    (root / "coverage" / "stimulus_plan.json").write_text(json.dumps({
        "schema": "stimulus_plan_v1", "backend": "generated",
        "sha256": "e" * 64,
        "stats": {"planned": 26, "unsupported": 37},
    }, ensure_ascii=False), encoding="utf-8")
    return root


def _patch_tools(module, run_dir) -> None:
    """把 `run_tool` 打桩成 `pipeline.detail` + `flow.signoff` 两个真工具的行为。

    `run_dir=None` 模拟「目录不存在」——`pipeline.detail` 返回一条 error，
    `load()` 应当走 `report_payload_error` 那条路（弹横幅、清表）。
    """
    from src.tools.flow.flow_tools import run_signoff

    def fake_run_tool(name=None, *, quiet=False, force=False, **kwargs):
        tool = name or (module.spec.tool.name if module.spec.tool else None)
        if tool == "pipeline.detail":
            if run_dir is None:
                return {"error": "运行目录不存在"}
            return {"dir": str(run_dir)}
        if tool == "flow.signoff":
            return run_signoff(str(run_dir))
        if tool == "evidence.check_package":
            return {
                "available": True,
                "verify": {"ok": True, "package_hash": "a" * 64},
                "replay": {"ok": True, "recorded_verdict": "PASS_WITH_CAVEAT",
                           "recomputed_verdict": "PASS_WITH_CAVEAT"},
                "recipe": {"schema": "signoff_replay_recipe_v2"},
                "recipe_issues": [],
            }
        raise AssertionError(f"没打桩的工具：{tool}")

    module.run_tool = fake_run_tool


@pytest.fixture
def module(qt_app, settings):
    from .conftest import make_ctx
    from ..modules.flow.signoff import SignoffModule

    spec, manifest, manifest_path = _shipped_spec()
    ctx = make_ctx(manifest, manifest_path, settings)
    mod = SignoffModule(ctx, spec)
    widget = mod.create_widget()
    yield mod
    widget.deleteLater()
    qt_app.processEvents()


@pytest.fixture
def loaded(module, tmp_path):
    _patch_tools(module, _run_dir(tmp_path))
    module.load("run-1")
    return module


def _row_color(model, row: int):
    return model.data(model.index(row, 0), Qt.ItemDataRole.ForegroundRole)


class TestRendering:
    def test_gates_table_filled(self, loaded):
        assert loaded.gate_model.rowCount() == 5
        assert loaded.gate_model.rows[0]["title"] == "① RTL 存在"
        assert loaded.gate_model.rows[0]["result"] == "通过"

    def test_failed_gate_shows_not_passed(self, loaded):
        rows = {r["title"]: r for r in loaded.gate_model.rows}
        assert rows["③ 回归全过"]["result"] == "不通过"
        assert rows["⑤ 参考模型非占位"]["result"] == "不通过"

    def test_gate_detail_is_shown(self, loaded):
        rows = {r["title"]: r for r in loaded.gate_model.rows}
        assert "apb_uart.sv" in rows["① RTL 存在"]["detail"]
        assert "占位" in rows["⑤ 参考模型非占位"]["detail"]

    def test_chain_table_filled(self, loaded):
        assert loaded.chain_model.rowCount() == 2
        assert loaded.chain_model.rows[0]["title"] == "需求层"
        assert loaded.chain_model.rows[0]["progress"] == "2/2"
        assert loaded.chain_model.rows[1]["progress"] == "1/4"

    def test_checks_rendered_with_marks(self, loaded):
        checks = loaded.chain_model.rows[1]["checks"]
        assert "P0 用例覆盖✓" in checks
        assert "P1 用例覆盖✗" in checks

    def test_header_summary_and_counts(self, loaded):
        assert "暂不可签核" in loaded.verdict_label.text()
        assert "NEEDS_FIX" in loaded.count_label.text()
        assert "5/6" in loaded.count_label.text()
        assert "93%" in loaded.count_label.text()


class TestCaseEvidenceInSignoff:
    """Case 证据（三集合）是**签核产出**：要能在签核页上看见它进没进包。"""

    def test_case_section_summarises_gate_and_cells(self, loaded):
        text = loaded.case_label.text()
        assert "BLOCKED" in text                      # gates.json 的 verdict
        assert "blocker 2" in text
        assert "绿 3" in text and "红 1" in text       # cell_matrix counts
        assert "用例 4" in text                       # case_ir counts
        assert "EVD 12" in text
        assert "case_cov 1 份" in text

    def test_case_artifacts_table_marks_packaged(self, loaded):
        rows = {r["path"]: r for r in loaded.case_model.rows}
        assert rows["coverage/gates.json"]["state"] == "是"
        assert rows["coverage/gates.json"]["in_package"] == "是"   # manifest 里登记过
        assert rows["coverage/evd.json"]["in_package"] == "否"     # 还没进包

    def test_without_case_artifacts_says_so(self, module, tmp_path):
        root = tmp_path / "nocase_20260101_000000"
        root.mkdir(parents=True)
        _patch_tools(module, root)
        module.load(root.name)
        assert "没有三集合产物" in module.case_label.text()
        assert module.case_model.rowCount() == 0


class TestEvidencePackage:
    """合同级证据包 v2 也要能在界面上看见 —— 不能只埋在 JSON 里。"""

    def test_evidence_panel_filled(self, loaded):
        text = loaded.evidence_label.text()
        assert "signoff_evidence_v2" in text
        assert "PASS_WITH_CAVEAT" in text
        assert "TP_MISSED" in text
        assert "95.23" in text and "68.57" in text
        assert "代码 计划 75.8" in text and "70.9" in text
        assert "DIVERSE" in text
        assert "0.8125" in text and "coverage" in text   # 粗连续奖励 + 最弱层
        assert "compile" in text and "0.25" in text      # 奖励权重
        assert "9 节点 / 8 边" in text                   # 运行时知识图规模
        assert "signoff_replay_recipe_v2" in text        # recipe v2
        assert "vsim" in text and "vcover" in text       # Tier B 依赖
        assert "26 可激励 / 37 不适用" in text           # StimulusPlan
        assert "missing" in text.lower()          # 没有 freeze.json
        assert "approve" in text

    def test_replay_command_is_available_for_copy(self, loaded):
        assert "replay.py" in loaded.replay_cmd
        assert loaded.evidence_dir.endswith("signoff_evidence")

    def test_evidence_package_can_be_checked_from_gui(self, loaded, monkeypatch):
        from PySide6.QtWidgets import QMessageBox

        seen = {}
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda parent, title, text: seen.update(title=title, text=text)))
        actions = [a.text() for a in loaded.create_actions()]
        assert "校验证据包" in actions

        loaded._check_evidence()
        assert seen["title"] == "证据包校验"
        assert "完整性：✓" in seen["text"]
        assert "Tier A：✓" in seen["text"]
        assert "signoff_replay_recipe_v2" in seen["text"]


class TestColors:
    def test_passed_rows_green_failed_red(self, loaded):
        from ..ui import theme
        assert _row_color(loaded.gate_model, 0).name() == theme.current().ok.lower()
        assert _row_color(loaded.gate_model, 2).name() == theme.current().error.lower()

    def test_layer_row_colored_by_full_pass(self, loaded):
        from ..ui import theme
        assert _row_color(loaded.chain_model, 0).name() == theme.current().ok.lower()
        assert _row_color(loaded.chain_model, 1).name() == theme.current().error.lower()


class TestMissingRunData:
    def test_run_without_signoff_files_says_so(self, module, tmp_path):
        empty = tmp_path / "empty_run"
        empty.mkdir()
        _patch_tools(module, empty)
        module.load("run-2")
        assert module.gate_model.rowCount() == 1
        assert "report.json" in module.gate_model.rows[0]["title"]
        assert "evidence_chain.json" in module.chain_model.rows[0]["title"]

    def test_bad_dir_shows_banner_not_crash(self, module):
        _patch_tools(module, None)
        module.load("run-x")
        assert module.banner.is_showing
        assert module.gate_model.rowCount() == 0

    def test_refresh_before_selection_is_a_noop(self, module):
        module.load("")               # 还没选运行 —— 不该崩、不该弹错
        assert module.gate_model.rowCount() == 0


class TestWiring:
    def test_binding_is_registered_and_pure(self):
        from ..bridge.catalog import by_name
        binding = by_name("flow.signoff")
        assert binding is not None
        assert binding.kind == "json"
        assert binding.pure is True

    def test_module_subscribes_to_run_selection(self):
        spec, _manifest, _path = _shipped_spec()
        assert "run.selected" in spec.params.get("subscribe", [])
        assert spec.group == "flow"

    def test_helpful_before_any_selection(self, module):
        assert "还没选中运行" in module.verdict_label.text()

    def test_on_refresh_ignores_empty_and_same_run(self, module):
        _patch_tools(module, None)
        module.on_refresh("")            # 空 topic 载荷 → 不动
        module.on_refresh(None)
        assert module.run_id == ""
