"""运行目录读取器 —— agent 产出 / 决策轨迹 / 运行清单。

三件事要钉住：
  · agent 产出**按日志里的 `agent` 字段过滤**（不 import 领域代码就能分类）；
  · 决策轨迹从 `decide` / `governor` 阶段事件的 `payload.delta` 里挖
    （`decision` 事件根本没人发，不能拿它当数据源）；
  · 日志里的**半行不该让整份日志读不出来**（追加写 + 进程被杀是常态）。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.app.services.flow import (run_agent_outputs, run_decision_trace,
                                  run_manifest_info)

EVENTS = [
    {"seq": 1, "kind": "stage.started", "stage": "design", "agent": "design", "round": 0},
    {"seq": 2, "kind": "stage.finished", "stage": "design", "agent": "design",
     "title": "规格与设计", "round": 0, "status": "ok", "duration_s": 12.5,
     "payload": {"delta": {"design_arch": {"module_name": "apb_uart"}}}},
    {"seq": 3, "kind": "stage.finished", "stage": "decide", "agent": "coverage",
     "title": "决策", "round": 1, "status": "ok", "duration_s": 0.3,
     "payload": {"delta": {"pending_action": {
         "action_type": "GENERATE_DIRECTED_TEST", "reason": "功能覆盖 62%",
         "priority": 2, "params": {"dimension": "D_baud"}}}}},
    {"seq": 4, "kind": "stage.finished", "stage": "governor", "agent": "",
     "title": "驾驭", "round": 1, "status": "ok", "duration_s": 0.1,
     "payload": {"delta": {"governance_outcome": "proceed"}}},
    {"seq": 5, "kind": "stage.failed", "stage": "decide", "agent": "coverage",
     "title": "决策", "round": 2, "status": "failed", "duration_s": 1.0,
     "payload": {"delta": {"pending_action": {
         "action_type": "REFACTOR_RTL", "reason": "回归失败", "priority": 0}}}},
    {"seq": 6, "kind": "stage.finished", "stage": "governor", "agent": "",
     "title": "驾驭", "round": 2, "status": "ok", "duration_s": 0.2,
     "payload": {"delta": {"governance_outcome": "abort"}}},
]


def _run(tmp_path: Path, *, events=True, manifest=True, chain=True) -> Path:
    root = tmp_path / "apb_uart"
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "rtl").mkdir(exist_ok=True)
    (root / "coverage").mkdir(exist_ok=True)
    (root / "rtl" / "apb_uart.sv").write_text("module m; endmodule\n", encoding="utf-8")
    (root / "coverage" / "cg.sv").write_text("// cg\n", encoding="utf-8")
    if events:
        body = "\n".join(json.dumps(e, ensure_ascii=False) for e in EVENTS)
        # 末尾故意留半行 —— 追加写被杀时的真实样子
        (root / "docs" / "run_events.jsonl").write_text(body + "\n{\"seq\": 7,", encoding="utf-8")
    if manifest:
        (root / "docs" / "manifest.json").write_text(json.dumps({
            "architecture": "closed_loop_7agents", "run_id": "apb_uart",
            "iterations": 4, "final_coverage": 93.0, "target": 95.0,
            "generator": "vagent dump", "manifest_hash": "abc123",
            "evidence_hash": "def456", "rtl_hashes": {"apb_uart.sv": "9f2c"},
        }, ensure_ascii=False), encoding="utf-8")
    if chain:
        (root / "docs" / "file_change_chain.json").write_text(json.dumps(
            {"changes": [
                {"seq": 1, "agent": "design", "file": "rtl/apb_uart.sv", "reason": "生成 RTL"},
                {"seq": 2, "agent": "model", "file": "model/ref.py", "reason": "参考模型"}]},
            ensure_ascii=False), encoding="utf-8")
    return root


class TestAgentOutputs:
    def test_stages_filtered_by_agent(self, tmp_path):
        r = run_agent_outputs(str(_run(tmp_path)), "design")
        assert [s["stage"] for s in r["stages"]] == ["design"]
        assert r["stages"][0]["title"] == "规格与设计"
        assert r["stages"][0]["duration_s"] == 12.5

    def test_another_agent_gets_its_own_stages(self, tmp_path):
        """decide 阶段归 coverage —— 按日志里的 agent 字段分，不是按阶段名猜。"""
        r = run_agent_outputs(str(_run(tmp_path)), "coverage")
        assert [s["stage"] for s in r["stages"]] == ["decide", "decide"]
        assert r["stages"][1]["status"] == "failed"

    def test_artifacts_from_role_dirs(self, tmp_path):
        r = run_agent_outputs(str(_run(tmp_path)), "design")
        assert [a["dir"] for a in r["artifacts"]] == ["rtl"]
        assert r["artifacts"][0]["files"][0]["name"] == "apb_uart.sv"

    def test_role_without_artifact_dirs_says_so(self, tmp_path):
        """debug 就地改文件、没有产物目录 —— 如实说"没有痕迹"。"""
        r = run_agent_outputs(str(_run(tmp_path, events=False)), "debug")
        assert r["artifacts"] == []
        assert any("没有 debug 的痕迹" in n for n in r["notes"])

    def test_counts(self, tmp_path):
        r = run_agent_outputs(str(_run(tmp_path)), "design")
        assert r["counts"] == {"stages": 1, "files": 1}

    def test_unknown_role_returns_empty_not_error(self, tmp_path):
        r = run_agent_outputs(str(_run(tmp_path)), "nope")
        assert "error" not in r
        assert r["counts"]["stages"] == 0

    def test_empty_role_is_an_error(self, tmp_path):
        assert "error" in run_agent_outputs(str(_run(tmp_path)), "")


class TestDecisionTrace:
    def test_rounds_merged_from_decide_and_governor(self, tmp_path):
        r = run_decision_trace(str(_run(tmp_path)))
        assert r["available"] is True
        assert [row["round"] for row in r["rounds"]] == [1, 2]

    def test_action_fields_extracted(self, tmp_path):
        row = run_decision_trace(str(_run(tmp_path)))["rounds"][0]
        assert row["action"] == "GENERATE_DIRECTED_TEST"
        assert row["reason"] == "功能覆盖 62%"
        assert row["priority"] == "2"
        assert row["params"] == "dimension=D_baud"
        assert row["governance"] == "proceed"

    def test_failed_decide_still_shows(self, tmp_path):
        row = run_decision_trace(str(_run(tmp_path)))["rounds"][1]
        assert row["action"] == "REFACTOR_RTL"
        assert row["governance"] == "abort"

    def test_no_journal_says_why(self, tmp_path):
        r = run_decision_trace(str(_run(tmp_path, events=False)))
        assert r["available"] is False
        assert "运行日志" in r["note"]

    def test_half_written_line_does_not_kill_the_journal(self, tmp_path):
        """最后一行是半截 JSON —— 前面的完整事件必须照常读出来。"""
        r = run_decision_trace(str(_run(tmp_path)))
        assert len(r["rounds"]) == 2


class TestManifestInfo:
    def test_manifest_rows_and_hashes(self, tmp_path):
        r = run_manifest_info(str(_run(tmp_path)))
        assert r["manifest"]["available"] is True
        assert r["manifest"]["manifest_hash"] == "abc123"
        assert r["manifest"]["evidence_hash"] == "def456"
        keys = [row["key"] for row in r["manifest"]["rows"]]
        assert "架构" in keys and "RTL 文件哈希" in keys

    def test_change_chain_entries(self, tmp_path):
        r = run_manifest_info(str(_run(tmp_path)))
        assert r["change_chain"]["entries"] == 2
        assert r["change_chain"]["rows"][0]["agent"] == "design"
        assert r["change_chain"]["rows"][0]["file"] == "rtl/apb_uart.sv"

    def test_missing_files_are_notes_not_errors(self, tmp_path):
        r = run_manifest_info(str(_run(tmp_path, manifest=False, chain=False)))
        assert "error" not in r
        assert r["manifest"]["available"] is False
        assert len(r["notes"]) == 2


class TestFailureIsLoud:
    def test_all_three_share_the_same_guard(self, tmp_path):
        for fn in (run_agent_outputs, run_decision_trace, run_manifest_info):
            for bad in ("", "does/not/exist"):
                result = fn(bad, "design") if fn is run_agent_outputs else fn(bad)
                assert "error" in result, (fn.__name__, bad)

    def test_file_instead_of_directory(self, tmp_path):
        f = tmp_path / "x.txt"
        f.write_text("hi", encoding="utf-8")
        assert "error" in run_manifest_info(str(f))

    def test_never_raises(self):
        for fn in (run_decision_trace, run_manifest_info):
            for bad in ("", "nope", "\x00"):
                assert isinstance(fn(bad), dict)
