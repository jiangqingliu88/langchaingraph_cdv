"""规则草案 —— 让规则库"从失败里长"，而不是只靠人手写。

规则库长大要三步：发现（指纹归类，已有）→ 记录（命中统计，已有）→ **归纳成规则**
（这一步原来没有）。于是规则只能靠人回头读日志再手写 —— 而 `is_elab_failure_line` /
`port_not_in_txn` 这两条真实规则恰恰是从事故里长出来的，说明这个动作在发生，
只是没有落点。

**只起草，不自动生效**：一条校验规则会改变"什么算错"，那是判断不是统计 ——
与人审批豁免、RTL 回滚同一个口径：机器提议、人提交。
"""
from __future__ import annotations

from src.layers.l4_memory.rule_draft import (STAGE_TITLES, collect_drafts,
                                            draft_from_failure, drafts_from_triage,
                                            rule_skeleton, write_drafts)

TRIAGE = [{"fingerprint": "393bb5128dea", "note": "# UVM_ERROR ...apb_gap_seq.sv(32)..."}]


class TestDraft:

    def test_rule_id_comes_from_the_category(self):
        d = draft_from_failure("abc123", category="bench hang", run_id="r1")
        assert d["rule_id"] == "learned_bench_hang"
        assert d["run_id"] == "r1" and d["fingerprint"] == "abc123"

    def test_without_category_the_fingerprint_names_it(self):
        """取不到归类就用指纹前缀 —— 名字难看但唯一，好过撞掉别人的草案。"""
        assert draft_from_failure("393bb5128dea")["rule_id"] == "learned_393bb512"

    def test_unknown_stage_falls_back_to_regress(self):
        assert draft_from_failure("a", stage="乱写")["stage"] == "regress"
        assert "regress" in STAGE_TITLES

    def test_skeleton_is_paste_ready(self):
        code = rule_skeleton(draft_from_failure("a", category="x"))
        # 规则函数按 `semantic_check` 的惯例带前导下划线（`_port_not_in_txn` 那种）
        assert '@rule(' in code and 'def _learned_x(' in code
        assert "NotImplementedError" in code          # 判据留给人写，骨架给全

    def test_skeleton_marks_the_judgement_as_missing(self):
        """骨架里必须有一处"判据得人写" —— 生成一个空返回的规则却不说明，人就以为它好了。"""
        assert "TODO" in rule_skeleton(draft_from_failure("a", category="x"))


class TestTriageToDrafts:

    def test_triage_entries_become_drafts(self):
        drafts = drafts_from_triage(TRIAGE, run_id="run_x")
        assert len(drafts) == 1 and drafts[0]["fingerprint"] == "393bb5128dea"
        assert drafts[0]["stage"] == "regress"        # 挂死该拦在回归时

    def test_entry_without_fingerprint_is_skipped(self):
        assert drafts_from_triage([{"note": "没有指纹"}], run_id="r") == []


class TestWriteAndRead:

    def test_write_then_read(self, tmp_path):
        assert write_drafts(tmp_path, drafts_from_triage(TRIAGE, run_id="r1")) == 1
        got = collect_drafts(tmp_path)
        assert len(got) == 1 and got[0]["rule_id"] == "learned_bench_hang"

    def test_same_fingerprint_is_written_once(self, tmp_path):
        """同一个错跑十次只该有一条草案。"""
        write_drafts(tmp_path, drafts_from_triage(TRIAGE, run_id="r1"))
        assert write_drafts(tmp_path, drafts_from_triage(TRIAGE, run_id="r2")) == 0
        assert len(collect_drafts(tmp_path)) == 1

    def test_markdown_is_written_for_humans(self, tmp_path):
        write_drafts(tmp_path, drafts_from_triage(TRIAGE, run_id="r1"))
        md = (tmp_path / "docs" / "rule_drafts.md").read_text(encoding="utf-8")
        assert "@rule(" in md and "该拦在哪" in md

    def test_broken_file_does_not_raise(self, tmp_path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "rule_drafts.jsonl").write_text("{坏行\n", encoding="utf-8")
        assert collect_drafts(tmp_path) == []

    def test_write_failure_never_raises(self, tmp_path):
        """起草是**旁路**，不该拖垮运行。"""
        assert write_drafts(tmp_path / "no" / "such" / "d", TRIAGE[:1]) >= 0
