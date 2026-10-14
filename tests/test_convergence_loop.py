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


class TestAnActionProvenIneffectiveIsActuallyAvoided:
    """**算出来了、写出来了、就是没人据此做决定** —— 这条缺的是"据此"。

    `l5_evolution.growth.is_action_proven_ineffective()` 早就写好了，L5 的模块头
    也写明用途是"历史证明无效的动作，**决策层降级/避开**"，但它**零调用者**：同一份
    数据被打印进决策理由（`[经验: 该动作历史 79 次尝试，改善率 4%]`），然后照选不误。

    实测：闭环六轮每轮都选 `GENERATE_DIRECTED_TEST`（当时 83 次尝试 / 改善率 3.6% /
    平均 Δ+1.1%），覆盖率每轮钉在 56.2 不动。
    """

    def _alt(self, action, monkeypatch, proven):
        from src.layers.l3_decision.brain.decision_brain import DecisionBrain

        monkeypatch.setattr("src.layers.l5_evolution.growth.is_action_proven_ineffective",
                            lambda *a, **k: proven)
        return DecisionBrain._ineffective_alternative(action)

    def test_a_proven_bad_action_gets_swapped(self, monkeypatch):
        assert self._alt("GENERATE_DIRECTED_TEST", monkeypatch, True) == "EXPAND_SEEDS"

    def test_a_fine_action_is_left_alone(self, monkeypatch):
        assert self._alt("GENERATE_DIRECTED_TEST", monkeypatch, False) is None

    def test_the_alternative_is_never_itself(self, monkeypatch):
        """扩种无效时**不返回它自己**（否则等于原地打转），也没有替代就照原样走。"""
        assert self._alt("EXPAND_SEEDS", monkeypatch, True) is None

    def test_both_paths_consult_it(self):
        """RL 覆盖路径与规则路径**都要过这道闸门** —— 只堵一条，另一条照样把
        无效动作选出来。"""
        src = Path("src/layers/l3_decision/brain/decision_brain.py").read_text(
            encoding="utf-8")
        assert src.count("_ineffective_alternative(") >= 3, \
            "定义 1 处 + 两条路径各 1 处：少一处就是有条路绕过它"

    def test_the_real_store_backs_the_judgement(self):
        """这条不是构造出来的：真实经验库里那个动作**确实**越界了。

        真实值随跑的次数变，所以只钉"接口在、字段在"，不钉具体数字 ——
        钉死数字会在下一次跑之后变成假失败。
        """
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
        from src.tools.uvm_tools.tool_find_spec_yaml.main import (_seed_lines,
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
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _seed_offset

        assert _seed_offset(tmp_path) == 0

    def test_every_seed_line_call_site_passes_the_offset(self):
        """**一处漏了就是一条测试永远跑老种子** —— 这个仓库的经典坑（改了三个漏一个）。

        用负向断言排掉**函数定义**那一行（它的形参里也有 `offset`，按
        `[^)]*` 抓会连签名一起抓进来 —— 第一版就是这么误报的）。
        """
        import re

        src = Path("src/tools/uvm_tools/tool_find_spec_yaml/main.py").read_text(
            encoding="utf-8")
        calls = re.findall(r"_seed_lines\((?!name: str)[^)]*\)", src)
        assert calls, "一条调用都没匹配到 —— 正则又写歪了"
        missing = [c for c in calls if "seed_offset" not in c]
        assert not missing, f"这些调用没带种子偏移：{missing}"

    def test_the_generated_yaml_carries_the_shifted_seed(self, tmp_path):
        """整条链：写偏移 → 生成 regression.yaml → 里面是顺移后的 SEED。"""
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _seed_lines

        (tmp_path / "coverage").mkdir()
        (tmp_path / "coverage" / "seed_expand.json").write_text(
            '{"offset": 500}', encoding="utf-8")
        from src.tools.uvm_tools.tool_find_spec_yaml.main import _seed_offset

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
