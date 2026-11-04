"""闭环的**收敛语义** —— 什么算"这一轮失败了"，什么只是"还没到"。

这三件事混在一起过，实测的直接后果是**闭环把自己的方向盘掐停了**：

    每轮决策都选 `GENERATE_DIRECTED_TEST`
      → 这一轮覆盖率没涨（平台期）        → 计一次"动作失败"
      → `audit` 判 NEEDS_FIX（未达标）   → 又计一次"执行失败"
      → 连续 3 次 → 熔断 → 升级人工 → **闭环停在 32.5%，max_rounds 还没用完**

而这三者本该分清：

  · **动作失败** = 这一步真出错了（抛异常 / 编译不过）—— 该熔断
  · **平台期**   = 这一轮没长进 —— 归因信号（该拿去学"哪个动作有效"），不是失败
  · **未达标**   = 审计如实报 NEEDS_FIX —— 那恰恰是闭环**要**的输入

顺带钉住两处"数字口径"：门槛不能写死（要用本次 run 的 target），覆盖率不能把
**没采到的指标**混进分母。
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestTheCoverageNumberOnlyCountsWhatWasCollected:
    """`overall_pct` **只在报告里真出现过的指标**上求平均。

    原来过滤的是"值 > 0"：于是"这次压根没采的指标"（编译没开 `-cover l` 就没有
    Lines、没采 toggle 就没有 Toggles，都是 0）与"采了但确实低"的指标被一视同仁 ——
    前者被排除出分母、后者拉低平均。数字于是成了"碰巧采到的那些指标的均值"，
    而闭环拿它当收敛目标（还会去补一个**量不到**的洞）。
    """

    CODE = """\
=== Instance: /tb/dut
=== Design Unit: work.dut
=================================================================================
    Enabled Coverage              Bins      Hits    Misses  Coverage
    ----------------              ----      ----    ------  --------
    Branches                      100        50        50   50.00%
    Statements                    100        60        40   60.00%
    Conditions                    100        10        90   10.00%
"""

    def _parse(self):
        from src.tools.common.lib.collect_real_coverage import _parse_vcover_text

        return _parse_vcover_text(self.CODE, "dut")

    def test_it_names_what_was_and_was_not_collected(self):
        r = self._parse()
        assert r["metrics_present"] == ["branch", "condition", "statement"]
        assert r["metrics_absent"] == ["fsm", "line", "toggle"]

    def test_the_average_covers_the_present_metrics(self):
        assert self._parse()["overall_pct"] == 40.0        # (50+60+10)/3

    def test_a_zero_but_collected_metric_still_counts(self):
        """**采到了但是 0%** 必须进分母 —— 它与"没采"是两件事。

        原来按 `> 0` 过滤，正好把这种情况排除掉了：一个真 0% 的指标从分母里消失，
        数字因此虚高，而人以为"采了 0"和"没采"是一回事。
        """
        code = self.CODE.replace("Conditions                    100        10        90   10.00%",
                                 "Conditions                    100         0       100    0.00%")
        from src.tools.common.lib.collect_real_coverage import _parse_vcover_text

        r = _parse_vcover_text(code, "dut")
        assert "condition" in r["metrics_present"]
        assert r["overall_pct"] == pytest.approx((50 + 60 + 0) / 3, abs=0.05)


class TestTheDecisionOnlyPicksActionsTheObservationSupports:
    """**空 gaps 的定向补测**：执行了、没补到、覆盖率不动 —— 然后被当失败熔断。

    `_pick_by_weight` 里早就有"只在观测确实支持该动作时才采纳"的守卫，但
    **RL 那条覆盖路径没有**。RL 学的是"状态 → 选哪个动作"，它判不了"此刻做不做得成"。
    """

    def _obs(self, **kw):
        return SimpleNamespace(**{"gaps": [], "failed_tests": [],
                                  "dead_code_modules": [], **kw})

    def _ok(self, action, obs):
        from src.layers.l3_decision.brain.decision_brain import DecisionBrain

        return DecisionBrain._supported_by_observation(action, obs)

    def test_directed_test_needs_gaps(self):
        assert self._ok("GENERATE_DIRECTED_TEST", self._obs()) is False
        assert self._ok("GENERATE_DIRECTED_TEST",
                        self._obs(gaps=[{"reason": "unstimulated"}])) is True

    def test_relax_constraint_needs_a_constraint_shaped_gap(self):
        assert self._ok("RELAX_CONSTRAINT",
                        self._obs(gaps=[{"reason": "unstimulated"}])) is False
        assert self._ok("RELAX_CONSTRAINT",
                        self._obs(gaps=[{"reason": "constraint"}])) is True

    def test_refactor_needs_evidence_of_a_real_problem(self):
        assert self._ok("REFACTOR_RTL", self._obs()) is False
        assert self._ok("REFACTOR_RTL",
                        self._obs(failed_tests=["t1"])) is True

    def test_actions_without_preconditions_are_always_allowed(self):
        assert self._ok("EXPAND_SEEDS", self._obs()) is True
        assert self._ok("某个没见过的动作", self._obs()) is True

    def test_the_rl_path_consults_the_guard(self):
        """源级守卫：RL 覆盖规则那条分支必须过 `_supported_by_observation`。

        按"分支的 `Action(...)` 构造点"定位 —— 那个 `reason` 里带着
        `RL 覆盖规则`。**别按字符串第一次出现定位**：文件里先有一段讲同一件事的
        注释，取到它会得到一个不相干的切片（写这条测试时先踩了一次）。
        """
        src = Path("src/layers/l3_decision/brain/decision_brain.py").read_text(
            encoding="utf-8")
        branch = src.index('f"RL 覆盖规则：')          # 分支里 Action 的 reason
        assert "_supported_by_observation(action_type, obs)" in src[:branch], \
            "RL 覆盖路径没查'观测支不支持' —— 空 gaps 的定向补测会再次被选中"


class TestTheAuditGateUsesThisRunsTarget:
    """门槛用 `ctx["target"]`，不是写死的 95。

    写死 95 的后果：目标 80 的项目，跑出 85% 也永远判 NEEDS_FIX —— 数字看着有门槛，
    门槛却和实际目标无关。目标**没给**时也不假装有门槛（如实说判不了）。
    """

    def _run(self, tmp_path, target, overall):
        from src.executors.audit.main import AuditExecutor

        # ⚠️ 目录名必须以 `_YYYYMMDD_HHMMSS` 结尾：`make_output_root` 只认这种
        # "已经建好的 run 目录"，否则它会**再套一层**带时间戳的新目录 ——
        # 于是审计读到的是个空目录（rtl_present=false），而这不是代码的问题。
        run = tmp_path / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True, exist_ok=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n",
                                            encoding="utf-8")
        task = {"output_dir": str(run),
                "ctx": {"regression": {"passed": 3, "failed": 0, "total": 3},
                        # 口径默认是 **functional** —— 所以要给 `functional_pct`，
                        # 只给 `overall_pct`（代码覆盖率）的话门槛会读到"缺失→0"
                        # 而判 NEEDS_FIX（那是**对**的行为，见下面那条测试）
                        "coverage": {"functional_pct": overall,
                                     "overall_pct": overall},
                        "target": target,
                        "model": {"placeholder": False}}}
        return asyncio.run(AuditExecutor().execute_task(task))

    def test_a_met_target_is_ready(self, tmp_path):
        res = self._run(tmp_path, 80.0, 85.0)
        assert res.data["report"]["gates"]["target"] == 80.0
        assert res.data["report"]["verdict"] == "READY"

    def test_a_missed_target_is_needs_fix(self, tmp_path):
        res = self._run(tmp_path, 80.0, 32.5)
        assert res.data["report"]["verdict"] == "NEEDS_FIX"

    def test_a_high_number_below_a_high_target_is_not_ready(self, tmp_path):
        """85% 在 95 的老口径下也是 NEEDS_FIX —— 但换成 target=80 就该 READY。
        这条钉的是"门槛真的跟着 target 走"。"""
        assert self._run(tmp_path / "a", 80.0, 85.0).data["report"]["verdict"] == "READY"
        assert self._run(tmp_path / "b", 95.0, 85.0).data["report"]["verdict"] == "NEEDS_FIX"

    def test_no_target_does_not_silently_pass(self, tmp_path):
        res = self._run(tmp_path, 0, 99.0)
        assert res.data["report"]["verdict"] == "NEEDS_FIX"
        assert res.data["report"]["gates"]["target"] == 0.0

    def test_a_missing_metric_does_not_fall_back_to_the_other_one(self, tmp_path):
        """只给代码覆盖率、口径却是 functional → **判不达标**，不是"换个数看看"。

        换口径的后果是目标在无声中变掉：报告里写着 95% 达标，而它其实是另一个
        口径的数 —— 读的人没有任何线索。
        """
        from src.executors.audit.main import AuditExecutor

        run = tmp_path / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        task = {"output_dir": str(run),
                "ctx": {"regression": {"passed": 3, "failed": 0, "total": 3},
                        "coverage": {"overall_pct": 99.0},       # 只有代码覆盖率
                        "target": 80.0, "model": {"placeholder": False}}}
        rep = asyncio.run(AuditExecutor().execute_task(task)).data["report"]
        assert rep["coverage_metric"] == "functional"
        assert rep["coverage"] == 0.0
        assert rep["verdict"] == "NEEDS_FIX"


class TestUncollectedMetricsStayOutOfTheDenominator:
    """**没测 ≠ 没覆盖** —— 没采到的指标不许进分母。

    覆盖地图（`coverage_map`）无条件按 `toggle_details` 造 toggle bin，而那份明细
    是从 ucdb 里**声明过的信号**读的、与"这次编译有没有采 toggle"无关。于是没采
    toggle 的 run 里这些 bin 全是 miss，把 `coverage = Σcovered/Σbins` 压低 ——
    而 `converged` 正是拿它比目标的（`lifecycle.py`：`effective_coverage >= target`），
    于是**收敛永远达不到**（实测 47.3%，而功能覆盖率同期 56.2%）。

    这与 `_parse_vcover_text` 那边"按 > 0 过滤"是同一类病的两处：都是把
    "没测"当成了"没覆盖"。
    """

    def _map(self, absent):
        from src.layers.l2_orchestration.coverage_map import CoverageMap

        cov = {"functional_pct": 50.0, "branch_bins": 100, "branch_misses": 50,
               "metrics_absent": absent}
        toggle = [{"signal": "sig", "high": 3, "low": 0, "misses": 40, "total": 40}]
        return CoverageMap().build(cov, toggle, {"bin_total": 10, "bin_hits": 5})

    def test_toggle_bins_are_dropped_when_toggle_was_not_collected(self):
        with_toggle = self._map([])                                  # 采了 → 计入
        without = self._map(["fsm", "line", "toggle"])               # 没采 → 不计
        assert without["total"] < with_toggle["total"]
        assert all(b["type"] != "toggle" for b in without["bins"])
        assert without["coverage"] > with_toggle["coverage"], \
            "没采到的 toggle 被算成 miss 时，分母虚大、比值虚低"

    def test_a_collected_toggle_still_counts(self):
        with_toggle = self._map([])
        assert any(b["type"] == "toggle" for b in with_toggle["bins"])


class TestTheLoopSteersByAConfiguredMetric:
    """闭环盯哪个覆盖率是**配置项**，不是写死的代码覆盖率。

    写死代码覆盖率的后果实测过：闭环的动作（按覆盖点 gap 生成定向激励）主要动
    **功能覆盖率**，而收敛信号盯代码覆盖率 —— "补了但数字不动"连续六轮，
    `convergence_forecast` 报 `rounds_to_target: Infinity`，而功能覆盖率同期 64.81%。
    **闭环在盯一个它的动作推不动的数。**
    """

    COV = {"overall_pct": 32.5, "functional_pct": 64.81}

    def test_the_default_metric_is_functional(self):
        from src.layers.l2_orchestration.planning import get_coverage_metric

        assert get_coverage_metric() == "functional"

    def test_the_picker_returns_the_configured_metric(self):
        from src.layers.l2_orchestration.planning import pick_coverage_value

        assert pick_coverage_value(self.COV, "functional")["value"] == 64.81
        assert pick_coverage_value(self.COV, "code")["value"] == 32.5
        assert pick_coverage_value(self.COV)["metric"] == "functional"

    def test_a_missing_metric_is_reported_not_silently_swapped(self):
        """缺就**说缺** —— 悄悄换另一个口径会让目标在无声中换掉，
        而"数字变了"和"口径变了"在报告里长得一样。"""
        from src.layers.l2_orchestration.planning import pick_coverage_value

        got = pick_coverage_value({"overall_pct": 32.5}, "functional")
        assert got["present"] is False and got["value"] == 0.0
        assert got["key"] == "functional_pct"

    def test_the_loop_and_the_audit_share_one_source(self):
        """闭环的收敛信号与审计的达标门槛**必须同源** —— 否则会出现
        "闭环在追功能覆盖率、审计在判代码覆盖率"这种错位。"""
        for p in ("src/layers/l2_orchestration/nodes/agent/run.py",
                  "src/executors/audit/main.py"):
            src = Path(p).read_text(encoding="utf-8")
            assert "pick_coverage_value(" in src, f"{p} 没走统一口径"


class TestTheSignoffReportShowsBothNumbers:
    """报告里**两个覆盖率都要有**，并标出哪个是判定口径。

    只留一个数的话，读的人分不清"32.5%"是代码还是功能 —— 而在同一份 run 里
    这两个数可以差一倍（32.5% vs 64.81%），"差在哪"正是要回答的问题。
    """

    def _report(self, tmp_path):
        from src.executors.audit.main import AuditExecutor

        run = tmp_path / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        task = {"output_dir": str(run),
                "ctx": {"regression": {"passed": 3, "failed": 0, "total": 3},
                        "coverage": {"functional_pct": 64.81, "overall_pct": 32.5},
                        "target": 95.0, "model": {"placeholder": False}}}
        return asyncio.run(AuditExecutor().execute_task(task)).data["report"]

    def test_it_names_the_metric_and_keeps_both(self, tmp_path):
        rep = self._report(tmp_path)
        assert rep["coverage_metric"] == "functional"
        assert rep["coverage"] == 64.81
        assert rep["coverage_detail"]["code_overall_pct"] == 32.5
        assert rep["coverage_detail"]["functional_pct"] == 64.81
        assert rep["summary"]["code_coverage"] == 32.5

    def test_the_gate_is_on_the_same_number_it_reports(self, tmp_path):
        rep = self._report(tmp_path)
        assert rep["gates"]["coverage_ok"] is False          # 64.81 < 95
        assert rep["gates"]["target"] == 95.0


class TestTheModelRulesFeedBothTheAssertionAndTheChecker:
    """**一份规则、两个执行点** —— SVA（bind 进 DUT）与 env 检查组件（UVM 收口）。

    用户口径：真 pass = **SCB 报 `mismatched=0`** + 断言不报错。断言那半是 SVA；
    `mismatched=0` 那半得有人在 env 里逐拍求值、数出来、打印出来。两处必须用
    **同一组规则**（各写一份必然漂，而漂了没人看得出来）。
    """

    DECLS = [
        {"name": "a_implies_b", "expr": "x == 2'd1 |-> y == 1'b0",
         "message": "x 为 1 时 y 必须为 0", "signals": [{"name": "x"}, {"name": "y"}]},
        {"name": "plain", "expr": "z <= 6'd32", "message": "水位不越界",
         "signals": [{"name": "z"}]},
        {"name": "temporal", "expr": "x |-> ##2 y", "message": "跨拍",
         "signals": [{"name": "x"}, {"name": "y"}]},
        {"name": "needs_absent", "expr": "w |-> y == 0", "message": "引用了接口没有的信号",
         "signals": [{"name": "w"}, {"name": "y"}]},
    ]

    def _rules(self, available):
        from src.layers.l3_decision.casemodel.coverage import checker_rules

        return checker_rules(self.DECLS, available)

    def test_an_implication_becomes_a_per_cycle_boolean(self):
        """`a |-> b` 在"每拍求值一次"里等价于 `!(a) || (b)` ——
        直接写进 `if` 里不是合法表达式。"""
        got = {r["name"]: r["expr"] for r in self._rules(["x", "y", "z"])["rules"]}
        assert got["a_implies_b"] == "!(cov_vif.x == 2'd1) || (cov_vif.y == 1'b0)"

    def test_a_plain_expression_passes_through(self):
        got = {r["name"]: r["expr"] for r in self._rules(["x", "y", "z"])["rules"]}
        assert got["plain"] == "(cov_vif.z <= 6'd32)"

    def test_every_signal_is_qualified_through_the_virtual_interface(self):
        """**每个信号都要加 `cov_vif.`** —— 这段表达式活在 env 覆盖率组件那个
        class 里，裸名字在那里**不可见**（DUT 信号只能经虚接口句柄看见）。

        不加限定的后果不是警告，是**编译不过**：实测整轮端到端 30 条
        `Undefined variable: 'queue_level'` → `env_pkg` 作废 → `test_pkg`
        找不到 env_pkg → `tb_top` 找不到 test_pkg → `vopt-13130` →
        回归 0/7、覆盖率恒 0%。

        **而它只在真编译时暴露**：生成侧、schema 校验、单测全都看不见 ——
        所以这条断言得钉在生成侧，不能指望"跑一遍就知道了"。
        """
        import re

        got = self._rules(["x", "y", "z"])["rules"]
        assert got, "规则一条都没出来"
        for r in got:
            # 表达式里出现的每个 `x`/`y`/`z`（作为标识符）都必须带 `cov_vif.` 前缀；
            # 数字字面量（`2'd1` / `6'd32`）不算标识符，`` 天然放过它们。
            for sig in ("x", "y", "z"):
                bare = re.search(rf"(?<!cov_vif\.){sig}", r["expr"])
                assert bare is None, (
                    f"规则 {r['name']} 里有裸信号名 {sig!r}：{r['expr']!r} —— "
                    f"env 组件那个 class 里看不见它，会编译不过")

    def test_a_signal_name_that_is_a_prefix_of_another_is_still_qualified(self):
        """`valid` 与 `valid_ready` 这种前缀关系不许误伤（`` 边界）。"""
        from src.layers.l3_decision.casemodel.coverage import checker_rules

        got = checker_rules(
            [{"name": "r", "expr": "valid && valid_ready", "message": "m",
              "signals": [{"name": "valid"}, {"name": "valid_ready"}]}],
            ["valid", "valid_ready"])["rules"]
        assert got[0]["expr"] == "(cov_vif.valid && cov_vif.valid_ready)"

    def test_temporal_rules_are_skipped_not_faked(self):
        """带 `##` 的跨拍性质，逐拍 `if` 表达不出来 —— **跳过并说明**，
        不假装检查过（"没查"不该算过）。"""
        skipped = " ".join(self._rules(["x", "y", "z"])["skipped"])
        assert "temporal" in skipped and "时序" in skipped

    def test_rules_referencing_missing_signals_are_skipped_with_a_reason(self):
        skipped = " ".join(self._rules(["x", "y", "z"])["skipped"])
        assert "needs_absent" in skipped and "w" in skipped

    def test_the_model_rules_really_produce_a_checker(self):
        """真模型（`specs/npu_sched/casemodel.yaml`）能产出可逐拍检查的规则 ——
        不是构造出来的样例。"""
        import yaml as _yaml

        from src.layers.l3_decision.casemodel.coverage import checker_rules

        cm = _yaml.safe_load(Path("specs/npu_sched/casemodel.yaml").read_text(
            encoding="utf-8"))
        got = checker_rules(cm.get("assertions"), [
            "queue_level", "instr_type", "instr_dtype", "dep_type", "issue_unit",
            "issue_decision", "cluster_id", "instr_opcode", "instr_seq",
            "pipeline_state", "op_priority", "barrier_type"])
        assert len(got["rules"]) >= 3
        # `issue_valid` 不在覆盖率接口上 → 那条如实进 skipped（不硬编一个信号）
        assert any("issue_valid" in s for s in got["skipped"])


class TestAnActionProvenIneffectiveIsActuallyAvoided:
    """**算出来了、写出来了、就是没人据此做决定**。

    `l5_evolution.growth.is_action_proven_ineffective()` 早就写好，L5 的模块头也
    写明用途是"历史证明无效的动作，**决策层降级/避开**"。而规则引擎里那个降级
    （`_with_experience`）是**有 fallback 才生效**的 —— 而唯一的调用点没给 fallback，
    于是判断被算出来、写进 reason（`[经验: 该动作历史 83 次尝试，改善率 4%]`）、
    然后**照选不误**：闭环六轮每轮都选它，覆盖率每轮钉在 56.2。

    修法是**用它那一个机制**（而不是在别处另写一份 —— 另写的那份顺手 import 了
    `l5_evolution`，被层向测试拦下）。
    """

    class _Provider:
        def __init__(self, bad): self.bad = bad
        def note(self, a): return f" [经验: {a} 历史 {a in self.bad}]"
        def ineffective(self, a): return a in self.bad

    def _engine(self, bad):
        from src.layers.l3_decision.decision_engine import CoverageDrivenDecisionEngine

        return CoverageDrivenDecisionEngine(target=95.0,
                                            experience=self._Provider(bad))

    def _act(self, action_type):
        from src.layers.l3_decision.decision_engine import Action

        return Action(action_type=action_type, reason="原始理由")

    def test_a_proven_bad_action_is_demoted(self):
        e = self._engine({"GENERATE_DIRECTED_TEST"})
        got = e.with_experience(self._act("GENERATE_DIRECTED_TEST"),
                                e.expand_seeds_action())
        assert got.action_type == "EXPAND_SEEDS"
        assert "历史证明无效" in got.reason

    def test_a_fine_action_is_left_alone(self):
        e = self._engine(set())
        got = e.with_experience(self._act("GENERATE_DIRECTED_TEST"),
                                e.expand_seeds_action())
        assert got.action_type == "GENERATE_DIRECTED_TEST"

    def test_the_generate_branch_actually_passes_the_fallback(self):
        """**没有 fallback 这道降级就不生效** —— 这正是它六轮空转的原因。

        按"未激励缺口"那条分支的**专属文案**定位（文件里有好几处
        `GENERATE_DIRECTED_TEST`，按第一次出现取会取到别的分支）。
        """
        src = Path("src/layers/l3_decision/decision_engine.py").read_text(
            encoding="utf-8")
        i = src.index("处未激励缺口，生成定向测试")
        assert "expand_seeds_action()" in src[i:i + 400], \
            "定向测试那条分支又没给 fallback —— 经验判断会被算出来却没人用"

    def test_both_brain_paths_go_through_the_same_mechanism(self):
        """RL 覆盖路径与规则路径**共用**规则引擎那一个机制（不各写一份）。"""
        src = Path("src/layers/l3_decision/brain/decision_brain.py").read_text(
            encoding="utf-8")
        assert src.count("with_experience(") >= 2, \
            "两条路径都要过闸门：只堵一条，另一条照样把无效动作选出来"

    def test_the_brain_does_not_reach_up_to_the_evolution_layer(self):
        """L3 不得 import L5 —— 经验查询走**注入**（层向测试也拦这条，
        但那条测试在 `tests/test_layer_direction.py`，这里就近再钉一次）。"""
        import re

        src = Path("src/layers/l3_decision/brain/decision_brain.py").read_text(
            encoding="utf-8")
        # 只禁**真 import**，不禁注释里提到这个名字（注释里提到"别这么干"是好事）
        bad = re.findall(r"^\s*(?:from|import)\s+\S*l5_evolution", src, re.M)
        assert not bad, f"决策层越级 import 了进化层：{bad}"

    def test_the_real_store_backs_the_judgement(self):
        """真实经验库里那个动作**确实**越界了（值随跑的次数变，只钉接口形状）。"""
        from src.layers.l5_evolution.growth import get_action_experience

        exp = get_action_experience("GENERATE_DIRECTED_TEST")
        if exp is None:
            pytest.skip("经验库里还没有这个动作的记录")
        assert {"trials", "improve_rate"} <= set(exp)


class TestExpandSeedsActuallyReachesTheSimulator:
    """扩种动作必须**真的换掉随机流** —— 否则它是个静默空转。

    实测：`n_apply_expand_seeds` 只写 `state.seed`，而那个字段**只被当覆盖 agent
    的输入**用（`{"seed": state.seed}`），回归的 `SEED` 一直是写死的 `12345` +
    case 模型声明的 `base`。于是账上记着"扩了种"、仿真跑的是同一批激励 ——
    **闭环六轮覆盖率每轮钉在 56.2，而每轮 ucdb 的 sha256 各不相同**
    （数据在采，采的是同一批）。
    """

    def _st(self, tmp_path, rnd):
        from src.layers.l3_decision.decision_engine import Action

        class _St:
            output_root = str(tmp_path)
            round_num = rnd

            def action(self):
                return Action(action_type="EXPAND_SEEDS",
                              params={"count": 1000}, reason="覆盖率停滞")
        return _St()

    def test_the_offset_accumulates_across_rounds(self, tmp_path):
        from src.layers.l2_orchestration.nodes.pure.apply import n_apply_expand_seeds

        got = [asyncio.run(n_apply_expand_seeds(self._st(tmp_path, r), {}))["seed"]
               for r in (1, 2, 3)]
        assert got == [1000, 2000, 3000], "偏移要**累加**（单调），不是每轮覆盖同一个值"

    def test_the_regression_reader_shifts_the_base_seed(self, tmp_path):
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import (_seed_lines,
                                                                  _seed_offset)

        (tmp_path / "coverage").mkdir()
        (tmp_path / "coverage" / "seed_expand.json").write_text(
            '{"round": 2, "offset": 2000}', encoding="utf-8")
        plan = {"npu_type_test": {"base": 2001, "count": 15, "explore": 3}}

        before = _seed_lines("npu_type_test", plan)
        after = _seed_lines("npu_type_test", plan, _seed_offset(tmp_path))
        assert before[-1] == "    variables: {SEED: 2001}"
        assert after[-1] == "    variables: {SEED: 4001}"
        # **count 不动**：要的是"没跑过的种子"，不是"多跑几遍同一条"
        assert before[0] == after[0] == "    count: 18"

    def test_no_offset_file_means_no_shift(self, tmp_path):
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _seed_offset

        assert _seed_offset(tmp_path) == 0

    def test_every_seed_line_call_site_passes_the_offset(self):
        """**一处漏了就是一条测试永远跑老种子** —— 这个仓库的经典坑（改了三个漏一个）。

        用负向断言排掉**函数定义**那一行（它的形参里也有 `offset`，按
        `[^)]*` 抓会连签名一起抓进来 —— 第一版就是这么误报的）。
        """
        import re

        src = Path("src/tools/generation/uvm_tools/tool_find_spec_yaml/generators/regression_gen.py").read_text(
            encoding="utf-8")
        calls = re.findall(r"_seed_lines\((?!name: str)[^)]*\)", src)
        assert calls, "一条调用都没匹配到 —— 正则又写歪了"
        missing = [c for c in calls if "seed_offset" not in c]
        assert not missing, f"这些调用没带种子偏移：{missing}"

    def test_the_generated_yaml_carries_the_shifted_seed(self, tmp_path):
        """整条链：写偏移 → 生成 regression.yaml → 里面是顺移后的 SEED。"""
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _seed_lines

        (tmp_path / "coverage").mkdir()
        (tmp_path / "coverage" / "seed_expand.json").write_text(
            '{"offset": 500}', encoding="utf-8")
        from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import _seed_offset

        lines = _seed_lines("t", {"t": {"base": 100, "count": 2}}, _seed_offset(tmp_path))
        assert "SEED: 600" in "".join(lines)


class TestTheBreakerCountsExecutionFailuresNotDispleasingVerdicts:
    """熔断计**动作执行失败**，不计"结论不合意"。

    实测：`audit` 连挂 3 轮（每轮都只是"未达标"）→ `GENERATE_DIRECTED_TEST` 熔断
    → 升级人工 → 闭环停在 32.5%，而 `max_rounds` 还有余量。闭环用自己的方向盘
    把自己掐停了。
    """

    def test_the_runtime_excludes_the_reporter_from_the_breaker(self):
        src = Path("src/layers/l2_orchestration/runtime.py").read_text(encoding="utf-8")
        assert '_countable = role != "audit"' in src

    def test_the_action_breaker_does_not_count_a_coverage_plateau(self):
        src = Path("src/layers/l2_orchestration/nodes/agent/run.py").read_text(
            encoding="utf-8")
        assert "success=(final_coverage > rt.prev_coverage)" not in src, \
            "又把'覆盖率没涨'记成动作失败了 —— 平台期是正常的，它该进归因、不该熔断"
        # 归因（覆盖率增量）仍要记 —— 那是"哪个动作有效"的学习信号
        assert "record_round(" in src


class TestTheSignoffDistinguishesGreenFromActuallyWorking:
    """签核三态：`READY` / `PASS_WITH_CAVEAT` / `NEEDS_FIX`。

    ## 为什么需要中间那一个

    硬门禁（RTL 真实 / 回归全过 / 覆盖率收上来了 / 模型不是占位）问的是
    "**能不能签**"。它们全过了，不代表**量到的东西是真的**：

        ucdb 落库了，4360 个 bin 一个没命中
        env/cons/ 生成了，11 条策略的 apply() 落在 default 分支什么都不做
        覆盖率数字好看，而 DUT 探针（cg_dut）零命中

    这些都是"绿但没真生效"。以前 audit 全当没看见、`READY` 照发 ——
    签完才发现约束从来没起过作用。所以加一档：**能签，但报告里要写清保留了哪些缺口**。

    ## 一条纪律：只有显式的 `False` 才算缺口

    `None` 是"判不了"（这一轮没跑覆盖率 / 没生成约束模型），而"判不了"到处都是 ——
    把它也算进来的话几乎每个 run 都会挂上 caveat，三态就贬值成"反正总有一条"，
    没人再去看那几行。所以只有 **明确的 False** 才升格。
    """

    def _run(self, tmp_path, sv=None, assoc=None):
        from src.executors.audit.main import AuditExecutor

        run = tmp_path / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True, exist_ok=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        ctx = {"regression": {"passed": 3, "failed": 0, "total": 3},
               "coverage": {"functional_pct": 90.0, "overall_pct": 90.0},
               "target": 80.0, "model": {"placeholder": False}}
        if sv is not None:
            ctx["semantic_validations"] = sv
        if assoc is not None:
            # 关联报告是**文件**（verify 写在 `coverage/`），不是 ctx 键 ——
            # 为一个旁路产物加一条穿过 24 个节点的 ctx 键不划算，audit 自己读盘。
            d = run / "coverage"
            d.mkdir(parents=True, exist_ok=True)
            (d / "association_report.json").write_text(
                json.dumps(assoc), encoding="utf-8")
        return asyncio.run(AuditExecutor().execute_task(
            {"output_dir": str(run), "ctx": ctx})).data["report"]

    def test_the_constraint_caveat_survives_a_skipped_coverage_stage(self, tmp_path):
        """**回归失败 → 闭环跳过 coverage** 时，约束没激活这件事仍要出现在签核报告里。

        `semantic_validations` 是**覆盖率阶段**拼进 `coverage_result.json` 的，
        而回归失败时那个阶段根本不跑（"功能回归 N 失败 → 跳过 coverage，
        进入 debug 修复"）—— 于是它恒为 `{}`。**实测跑出来的就是这个**：
        签核报告里对"`env/cons/` 生成了但 11 条策略全是空壳"一个字都没有。

        而 `constraint_status.json` 是 verify 写的、不依赖覆盖率阶段。audit 直接读它。
        硬门禁本来就不过时判定仍是 NEEDS_FIX，但 caveat 会如实进报告 ——
        **签核的人得看得见"约束从来没生效过"**。
        """
        import json

        from src.executors.audit.main import AuditExecutor

        run = tmp_path / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n",
                                            encoding="utf-8")
        (run / "coverage").mkdir()
        (run / "coverage" / "constraint_status.json").write_text(json.dumps({
            "constraint_generated": True, "constraint_policy_applied": False,
            "unbacked_policy_count": 11}), encoding="utf-8")

        rep = asyncio.run(AuditExecutor().execute_task({
            "output_dir": str(run),
            "ctx": {"regression": {"passed": 0, "failed": 7, "total": 7},
                    "coverage": {}, "target": 80.0, "model": {"placeholder": False}},
        })).data["report"]
        # 硬门禁没过 → NEEDS_FIX（caveat 不让它变 PASS_WITH_CAVEAT）
        assert rep["verdict"] == "NEEDS_FIX"
        # 但**约束没生效这件事必须写进报告** —— 否则签核的人看不到
        assert any("约束未激活" in c for c in rep["caveats"]), rep["caveats"]

    def test_a_clean_run_is_ready_with_no_caveats(self, tmp_path):
        r = self._run(tmp_path, sv={"constraint_policy_applied": True,
                                    "ucdb_nonzero_bins": True,
                                    "cg_dut_hit_gt_zero": True})
        assert r["verdict"] == "READY"
        assert r["caveats"] == []
        assert r["signoff_status"] == "APPROVED"

    def test_an_inactive_constraint_is_pass_with_caveat(self, tmp_path):
        """**本轮要的那一条**：硬门禁全过，但约束没在约束东西。"""
        r = self._run(tmp_path, sv={"constraint_policy_applied": False,
                                    "ucdb_nonzero_bins": True})
        assert r["verdict"] == "PASS_WITH_CAVEAT"
        assert r["signoff_status"] == "CONDITIONAL"
        assert any("约束未激活" in c for c in r["caveats"])
        assert r["summary"]["caveat_count"] == 1

    def test_a_zerohit_ucdb_is_a_caveat_and_so_is_a_dead_probe(self, tmp_path):
        r = self._run(tmp_path, sv={"ucdb_nonzero_bins": False,
                                    "cg_dut_hit_gt_zero": False})
        assert r["verdict"] == "PASS_WITH_CAVEAT"
        assert len(r["caveats"]) == 2

    def test_a_broken_hard_edge_in_the_association_is_a_caveat(self, tmp_path):
        r = self._run(tmp_path, assoc={"hard_edge_broken": 2})
        assert r["verdict"] == "PASS_WITH_CAVEAT"
        assert any("硬边断了 2 条" in c for c in r["caveats"])

    def test_unknown_is_not_a_caveat(self, tmp_path):
        """`None` = 判不了 —— **不是**缺口。否则每个 run 都挂着 caveat，就没人看了。"""
        r = self._run(tmp_path, sv={"ucdb_nonzero_bins": None,
                                    "constraint_policy_applied": None,
                                    "seed_diversity_verified": None})
        assert r["verdict"] == "READY"
        assert r["caveats"] == []

    def test_no_semantic_block_at_all_is_still_ready(self, tmp_path):
        """整块缺失（老 run / 没跑到覆盖率）→ 不判 —— 与"判了、没过"必须分开。"""
        r = self._run(tmp_path)
        assert r["verdict"] == "READY"
        assert r["caveats"] == []

    def test_a_failed_hard_gate_beats_any_caveat(self, tmp_path):
        """硬门禁没过就是 NEEDS_FIX —— caveat 是"能签但要写明"，不是"绕过门禁"。"""
        r = self._run(tmp_path / "x", sv={"constraint_policy_applied": False})
        # 先造一个硬失败：目标 95 而覆盖率 90
        from src.executors.audit.main import AuditExecutor

        run = tmp_path / "y" / "output_dut_20260101_000000"
        (run / "rtl").mkdir(parents=True)
        (run / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
        bad = asyncio.run(AuditExecutor().execute_task({
            "output_dir": str(run),
            "ctx": {"regression": {"passed": 3, "failed": 0, "total": 3},
                    "coverage": {"functional_pct": 90.0, "overall_pct": 90.0},
                    "target": 95.0, "model": {"placeholder": False},
                    "semantic_validations": {"constraint_policy_applied": False}},
        })).data["report"]
        assert bad["verdict"] == "NEEDS_FIX"
        assert bad["signoff_status"] == "REJECTED", \
            "NEEDS_FIX 原来标成 CONDITIONAL —— 读起来像'可以签、带条件'，实际是'不能签'"
