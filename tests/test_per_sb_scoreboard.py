"""逐条 SB（scoreboard）收口 —— 生成侧发 `[SCB <id>]`，采集侧按它判。

一条 SB 的证据原本只有 env 的聚合行 `[SCB_DUT]`：签核只能说"整轮比过了"，
说不出**哪一条 SB 比过**。这条路把它打通，同时守住三个"不"：

    不猜    —— 归属来自模型声明的 `rules`，名字对不上的不发
    不冒充  —— 没有逐条行就退回聚合，`evidence: log` 的 SB 仍判未执行
    不假通过 —— 回归判据锚定 `[SCB_DUT]`/`Scoreboard:`，逐条行的 `mismatched=0`
               不能单独满足它（否则"某条 SB 干净、聚合脏"会被判通过）
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

EXAMPLES = Path("src/tools/generation/uvm_tools/tool_uvm/examples/apb")
ENV_TEMPLATE = Path(
    "src/tools/generation/uvm_tools/tool_uvm/templates/environment_templates"
    "/env_cov.sv.j2")


# ────────────────────────────────────────────────────────────────
# 判据不能被逐条行骗过
# ────────────────────────────────────────────────────────────────

class TestThePassCriterionIsAnchored:
    """`grep -qE "mismatched=0"` 是子串匹配 —— 逐条行会让它假通过。"""

    def _pattern(self):
        from src.layers.l2_orchestration.regression_tools.backend_profiles import (
            QUESTA_TEMPLATE)
        m = re.search(r'grep -qE "([^"]*mismatched=0[^"]*)" sim_vsim\.log',
                      QUESTA_TEMPLATE)
        assert m, "判据链里找不到 grep 锚点"
        return re.compile(m.group(1))

    def test_per_sb_clean_line_does_not_satisfy_it(self):
        pat = self._pattern()
        assert pat.search("[SCB SB-A] total=3 matched=3 mismatched=0") is None

    def test_aggregate_and_scoreboard_lines_do(self):
        pat = self._pattern()
        assert pat.search("UVM_INFO ... [SCB_DUT] total=9 matched=9 mismatched=0")
        assert pat.search("Scoreboard: total=20 matched=20 mismatched=0")

    def test_a_dirty_aggregate_is_not_rescued_by_a_clean_subset(self):
        pat = self._pattern()
        log = ("[SCB SB-A] total=3 matched=3 mismatched=0\n"
               "[SCB_DUT] total=9 matched=8 mismatched=1")
        assert pat.search(log) is None

    def test_the_comment_lines_stay_honest(self):
        """模板里写了"有 X 的那支不写 mismatched=0" —— 改了分支要一起改注释。"""
        text = ENV_TEMPLATE.read_text(encoding="utf-8")
        assert "有 X 的那支**不写 `mismatched=0`**" in text

    def test_error_criterion_catches_both_questa_formats(self):
        """旧格式 `UVM_ERROR : 3` 与新格式 `UVM_ERROR file(line)` 都要拦。

        只认旧格式会造成假通过：实测新版日志里 139 条逐条 `UVM_ERROR` 全被漏掉。
        """
        from src.layers.l2_orchestration.regression_tools.backend_profiles import (
            QUESTA_TEMPLATE)
        m = re.search(r'! grep -qE "([^"]+)"', QUESTA_TEMPLATE)
        assert m, "判据链里找不到 UVM_ERROR 锚点"
        pat = re.compile(m.group(1))
        assert not pat.search("UVM_ERROR :    0")
        assert not pat.search("Errors: 0")
        assert pat.search("UVM_ERROR :    3")
        assert pat.search("UVM_ERROR D:/x/y.sv(181) @ 1 ns")
        assert pat.search("UVM_FATAL D:/x/y.sv(9) @ 1 ns")


# ────────────────────────────────────────────────────────────────
# 生成侧：SB → 规则归属
# ────────────────────────────────────────────────────────────────

class TestScoreboardRuleOwnership:
    def test_only_matching_declared_rules_are_kept(self):
        from src.executors.verify.dut_checker import _per_sb_rules

        rules = [{"name": "a", "expr": "1"}, {"name": "b", "expr": "1"}]
        sbs = [
            {"id": "SB-ONE", "evidence": "auto", "rules": ["a", "typo"]},
            {"id": "SB-AGG", "evidence": "aggregate", "rules": ["b"]},
            {"id": "SB-EMPTY", "rules": ["typo"]},
        ]
        assert _per_sb_rules(sbs, rules) == [{"id": "SB-ONE", "rules": ["a"]}]

    def test_ids_are_normalised_the_same_way_as_case_ir(self):
        from src.executors.verify.dut_checker import _per_sb_rules

        got = _per_sb_rules([{"id": "NPU-DUT", "rules": ["r"]}],
                            [{"name": "r", "expr": "1"}])
        assert got == [{"id": "SB-NPU-DUT", "rules": ["r"]}]

    def test_model_carries_rules_through_the_loader(self):
        from src.layers.l3_decision.casemodel.repository.loader import (
            load_model_from_text)

        model = load_model_from_text(
            Path("specs/npu_sched/casemodel.yaml").read_text(encoding="utf-8"))
        sb = model.scoreboards[0]
        assert sb.rules and set(sb.rules) <= {
            a.name for a in model.assertions}
        assert sb.to_dict()["rules"] == sb.rules


# ────────────────────────────────────────────────────────────────
# 渲染出来的 env：逐条行 + 每规则计数
# ────────────────────────────────────────────────────────────────

DUT_IF = {
    "name": "apb_slave_cov_if", "type": "apb_slave_cov_if",
    "instance": "u_apb_slave_cov_if", "dut_module": "apb_slave_dut",
    "clock": "pclk", "reset": "presetn",
    "file": "coverage/apb_slave_cov_if.sv",
    "signals": ["paddr"],
    "coverpoints": [{"signal": "paddr", "sv_name": "cp_paddr",
                     "field": "paddr", "width": 8, "expr": ""}],
}
DUT_BINS = {"paddr": [{"name": "cp_zero", "value": "0", "illegal": False}]}
DUT_CHECKER = {
    "clock": "pclk", "reset": "presetn", "skipped": [],
    "rules": [
        {"name": "paddr_low", "expr": "cov_vif.paddr <= 8'd127", "message": "低半区"},
        {"name": "paddr_wait", "expr": "!cov_vif.paddr[0] || cov_vif.paddr[1]",
         "message": "等待约束"},
    ],
    "scoreboards": [{"id": "SB-APB", "rules": ["paddr_low", "paddr_wait"]}],
}


@pytest.fixture()
def rendered_env(tmp_path):
    ydir = tmp_path / "inputs" / "yaml" / "uvm"
    ydir.mkdir(parents=True)
    for src in EXAMPLES.glob("*.yaml"):
        shutil.copy(src, ydir / src.name)
    (ydir / "env_cov_bins.yaml").write_text(json.dumps({
        "cov_bins": [], "dut_if": DUT_IF, "dut_bins": DUT_BINS,
        "dut_checker": DUT_CHECKER,
    }, ensure_ascii=False), encoding="utf-8")
    from src.tools.generation.uvm_tools.tool_jinja_render.main import run

    assert json.loads(run(str(tmp_path)))["status"] == "ok"
    env = list((tmp_path / "env").glob("*_coverage.sv"))
    assert len(env) == 1
    return env[0].read_text(encoding="utf-8")


class TestTheRenderedCheckerCountsPerScoreboard:
    def test_each_rule_gets_its_own_evaluation_counters(self, rendered_env):
        assert "int unsigned chk_n_paddr_low = 0;" in rendered_env
        assert "int unsigned chk_x_paddr_low = 0;" in rendered_env
        assert "chk_n_paddr_low++;" in rendered_env
        assert "chk_x_paddr_wait++;" in rendered_env

    def test_the_per_sb_line_is_emitted(self, rendered_env):
        assert '"[SCB SB-APB] total=%0d matched=%0d mismatched=%0d"' in rendered_env
        assert ("sb_n_1 += chk_n_paddr_low;" in rendered_env
                and "sb_bad_1 += chk_bad_paddr_wait;" in rendered_env)

    def test_the_x_branch_never_prints_mismatched_zero(self, rendered_env):
        x_branch = rendered_env.split("（求值为 X 的拍）")[0].rsplit("`uvm_info", 1)[-1]
        assert "unverified=" in x_branch
        assert "mismatched=0" not in x_branch

    def test_the_aggregate_line_stays(self, rendered_env):
        assert '"[SCB_DUT] total=%0d matched=%0d mismatched=0"' in rendered_env


# ────────────────────────────────────────────────────────────────
# 采集侧：逐条事实按自己的行，不拿聚合冒充
# ────────────────────────────────────────────────────────────────

class TestCollectedFactsPreferThePerSbLine:
    def _facts(self, scb_items, by_id, summary):
        from src.layers.l3_decision.evidence.case_cov_impl import _raw_facts_for

        found = _raw_facts_for([], {"scb": scb_items},
                               {"case_id": "C", "scb_summary": summary,
                                "log_facts": {"scb_by_id": by_id}})
        return {f["subject"]["id"]: f["value"]
                for f in found if f["type"] == "scb_result"}

    def test_own_line_wins_aggregate_is_the_fallback(self):
        values = self._facts(
            [{"id": "SB-A", "evidence": "auto"}, {"id": "SB-B", "evidence": "auto"}],
            {"SB-A": {"total": 4, "matched": 4, "mismatched": 0}},
            {"total": 10, "matched": 10, "mismatched": 0})
        assert values["SB-A"] == {"exec": 4, "matched": 4, "mismatched": 0}
        assert values["SB-B"] == {"exec": 10, "matched": 10, "mismatched": 0}

    def test_log_mode_without_its_own_line_is_not_proven(self):
        values = self._facts(
            [{"id": "SB-LOG", "evidence": "log"}], {},
            {"total": 10, "matched": 10, "mismatched": 0})
        assert values["SB-LOG"]["matched"] is None
        from src.layers.l3_decision.contract.case_judge import build_raw_facts

        assert build_raw_facts("C", scb=[{"id": "SB-LOG", "exec": 0,
                                          "matched": None,
                                          "mismatched": None}])


class TestEvidenceLevelIsNotGuessed:
    """**归属不猜**：没有自己那行时如实标 aggregate（log 模式则未执行）。"""

    AGG = {"total": 9, "matched": 9, "mismatched": 0}

    def _level(self, item, by_id=None):
        from src.layers.l3_decision.evidence.case_cov_impl import _scb_evidence

        got = _scb_evidence([item], {"scb_summary": self.AGG,
                                     "log_facts": {"scb_by_id": by_id or {}}})
        return got[0]

    def test_no_own_line_stays_aggregate(self):
        got = self._level({"id": "SB-X", "evidence": "auto"})
        assert got["evidence_level"] == "aggregate"
        assert got["status"] == "PROVEN"

    def test_log_mode_without_line_is_not_executed(self):
        got = self._level({"id": "SB-LOG", "evidence": "log"})
        assert got["evidence_level"] == "none"
        assert got["status"] == "NOT_EXECUTED"

    def test_own_line_switches_to_per_scb(self):
        got = self._level({"id": "SB-X", "evidence": "auto"},
                          {"SB-X": {"total": 4, "matched": 4, "mismatched": 0}})
        assert got["evidence_level"] == "per_scb" and got["exec"] == 4
