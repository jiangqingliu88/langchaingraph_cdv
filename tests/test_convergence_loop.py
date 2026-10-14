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
        from src.tools.lib.collect_real_coverage import _parse_vcover_text

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
        from src.tools.lib.collect_real_coverage import _parse_vcover_text

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
