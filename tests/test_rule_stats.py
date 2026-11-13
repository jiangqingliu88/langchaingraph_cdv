"""校验规则的命中统计 —— 让规则库**能淘汰**，否则它不是资产是负债。

规则现在带 id 但只打印：没有累计的地方，于是"从来没命中的规则"和"真在干活的规则"
在源码里长得一模一样 —— 没人敢删、也没人知道该调哪条阈值。这一组钉住那本账。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.knowledge.rule_stats import RuleStats, record_rule_hits, registered_rules


@dataclass
class _Issue:
    rule: str
    severity: str
    kind: str = "agent"
    target: str = "apb"


def _stats(tmp_path) -> RuleStats:
    return RuleStats(str(tmp_path / "rule_stats.db"))


class TestRecordAndStats:

    def test_hits_accumulate_across_runs(self, tmp_path):
        s = _stats(tmp_path)
        s.record([_Issue("port_not_in_txn", "warning")], run_id="run_a")
        s.record([_Issue("port_not_in_txn", "warning")], run_id="run_b")
        row = s.stats()["rules"][0]
        assert row["rule"] == "port_not_in_txn" and row["hits"] == 2
        assert row["first_run"] == "run_a" and row["last_run"] == "run_b"

    def test_different_severity_is_a_different_row(self, tmp_path):
        """同一条规则不同严重度分开记 —— 阈值调过之后是两回事。"""
        s = _stats(tmp_path)
        s.record([_Issue("r", "error"), _Issue("r", "warning")])
        assert len(s.stats()["rules"]) == 2

    def test_hits_ordered_by_count(self, tmp_path):
        s = _stats(tmp_path)
        s.record([_Issue("rare", "warning")])
        s.record([_Issue("common", "error")] * 3)
        assert [r["rule"] for r in s.stats()["rules"]] == ["common", "rare"]

    def test_issue_without_id_is_not_recorded(self, tmp_path):
        """没 id 的不记 —— 记了也没法淘汰，只会把账搞脏。"""
        assert record_rule_hits([_Issue("", "warning")],
                                db_path=str(tmp_path / "s.db")) == 0

    def test_stats_lists_the_registrys_never_hit_rules(self, tmp_path):
        """**从注册起一次都没命中的**要单独列出来 —— 那才是该删/该调的候选。"""
        s = _stats(tmp_path)
        s.record([_Issue("port_not_in_txn", "warning")])
        never = {r["rule"] for r in s.stats()["never_hit"]}
        all_rules = {r["rule"] for r in registered_rules()}
        assert "port_not_in_txn" not in never          # 命中过
        assert never and never <= all_rules            # 其余都是登记在册的规则

    def test_registry_is_read_from_the_real_source(self):
        """规则全集从注册表现取 —— 不另抄一份名单（抄了就是第二份真相）。"""
        assert len(registered_rules()) >= 8            # semantic_check 至少 8 条

    def test_recording_failure_never_raises(self, tmp_path):
        """统计是**旁路**，不该拖垮生成流程 —— 目录不可写也只是记不上。"""
        assert record_rule_hits([_Issue("x", "warning")],
                                db_path=str(tmp_path / "no" / "such" / "d" / "s.db")) >= 0
