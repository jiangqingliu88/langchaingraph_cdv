"""回归失败的**归类** —— 设计级（该改 RTL）还是环境级（重跑就行）。

这不是细节：判成设计级 → 决策引擎最高优先级规则把它送去 COMPILE_RETRY，
**整段跳过覆盖率阶段**，那一轮签核必然不过（覆盖率 0%）。实测踩过两次：

  · 第一次是判据太宽（`Error (suppressible)` —— Questa 对无害告警也这么打），
    于是每个正常跑完的仿真都被判成编译失败；
  · 第二次是判据对、**归类错**：某个 case 的 vsim 报 DPI 自动编译库加载失败
    （`vsim-3772`），末尾那句 `Error loading design` 命中了判据，整轮被判成
    "RTL 编译不过"，跑去修一个不存在的编译错误（`file=None`）。

同一条测试里也钉住 `validate_regress` 的报告路径契约 —— 它原先查的是
**收尾阶段**才写的 `<输出根>/report.json`，于是每轮都报 `report.json not found`。
"""
from __future__ import annotations

import json

import pytest

from src.runtime_plane.infrastructure.infrastructure import (
    classify_sim_failures, is_elab_failure_line)
from src.orchestration_plane.l2.governance.quality_guard import (
    Verdict, validate_regress)

#: 实测那份日志的关键几行（DPI 自动编译库加载失败）
DPI_LOAD_FAILURE = """\
# Loading work.apb_uart_bench_tb_top(fast)
# Compiling C:/Users/x/AppData/Local/Temp/jiang@HOST_dpi_28016/win64_gcc-12.2.0/exportwrapper.c
# ** Error: (vsim-3193) Load of "C:/Users/x/AppData/Local/Temp/jiang@HOST_dpi_28016/win64_gcc-12.2.0/vsim_auto_compile.dll" failed: 拒绝访问
# ** Fatal: (vsim-3772) Failed to load DPI auto compile shared library file "...vsim_auto_compile.dll".
# FATAL ERROR while loading design
# Error loading design
"""

#: 真·elaboration 错误（多驱动）—— 这个必须仍然判成设计级
MULTIPLE_DRIVER = """\
# ** Error (suppressive error message) (added by workaround for vopt-1268): ICONNECT
# ** Error: (vopt-1995) Variable "/tb/dut/state" is driven by multiple continuous assignments.
# Error loading design
"""


class TestClassifySimFailures:

    def test_dpi_load_failure_is_environment_not_design(self):
        """DPI 库加载不上是环境故障 —— 不能引着流水线去改 RTL。"""
        design, env = classify_sim_failures(DPI_LOAD_FAILURE)
        assert not design, f"被误判成设计错误：{design}"
        assert env, "环境故障没被识别出来"
        assert any("vsim-3772" in line for line in env)

    def test_multiple_driver_is_still_a_design_failure(self):
        design, env = classify_sim_failures(MULTIPLE_DRIVER)
        assert design and any("vopt-1995" in line for line in design)
        assert not env

    def test_license_failure_is_environment(self):
        design, env = classify_sim_failures(
            "# ** Error: Unable to checkout a license for this feature\n"
            "# Error loading design\n")
        assert not design and env

    def test_both_present_prefers_design(self):
        """两类同时出现（先编译不过、环境也坏了）→ 按设计级处理。

        宁可误报去修 RTL，也不能把真编译错误当成环境抖动放过去 ——
        放过去的话，一轮就这么浪费掉，还看不到覆盖率。
        """
        design, env = classify_sim_failures(MULTIPLE_DRIVER + DPI_LOAD_FAILURE)
        assert any("vopt-1995" in line for line in design)
        assert not env

    def test_clean_log_is_empty(self):
        assert classify_sim_failures("# Errors: 0, Warnings: 0\n") == ([], [])


class TestVoptWarningIsNotACompileFailure:
    """**带 `vopt-NNNN` 的 Warning / Note 不是编译失败** —— 第三次同类事故。

    前两次（见模块头）都是"判据太宽"，这次是"看编号不看严重度"：
    Questa 的警告和提示用的是**同一套 `vopt-NNNN` 编号**，实测两条

        # ** Warning: (vopt-13408) Code coverage will be disabled for some DUs…
        # ** Note: (vopt-143) Recognized 1 FSM in module "apb_master(fast)."

    它们只在**开着覆盖率编译**（`vlog +cover`）时才出现（vopt 要为覆盖率做 FSM
    识别与插桩）。于是"默认开覆盖率"这件事本身触发了误判：整轮回归被判成
    "RTL 编译不过" → 路由去修一个不存在的编译错误 → **覆盖率阶段整段跳过**，
    覆盖率恒为 0%。实测踩过。
    """

    #: 实测那两行（会话中真实产物）
    VOPT_WARNING = "# ** Warning: (vopt-13408) Code coverage will be disabled for some DUs/packages/classes and source files.\n"
    VOPT_NOTE = '# ** Note: (vopt-143) Recognized 1 FSM in module "apb_master(fast)".\n'

    def test_warning_line_is_not_a_failure(self):
        assert is_elab_failure_line(self.VOPT_WARNING.strip()) is False

    def test_note_line_is_not_a_failure(self):
        assert is_elab_failure_line(self.VOPT_NOTE.strip()) is False

    def test_full_log_with_only_warnings_is_clean(self):
        assert classify_sim_failures(self.VOPT_WARNING + self.VOPT_NOTE) == ([], [])

    def test_real_vopt_error_still_counts(self):
        """多驱动那条（`** Error: (vopt-1995)`）一条都不能漏。"""
        assert is_elab_failure_line(
            '# ** Error: (vopt-1995) Variable "/tb/dut/state" is driven by '
            "multiple continuous assignments.") is True

    def test_suppressive_form_still_counts(self):
        """`** Error (suppressive error message) (added by workaround for vopt-1268)`
        —— 编号在句中、不是 `: (vopt-NNNN)` 那种形状，也得认。"""
        assert is_elab_failure_line(
            "# ** Error (suppressive error message) (added by workaround for "
            "vopt-1268): ICONNECT") is True

    def test_assertion_error_is_not_a_compile_failure(self):
        """**断言失败不是编译失败**。

        Questa 把断言也打成 `# ** Error: …`。收进来同样会让整轮跳过覆盖率 ——
        而"某条 case 的断言挂了"本来正是回归该记下来的结果，不是编译问题。
        """
        assert is_elab_failure_line(
            "# ** Error: tb.sv(9): Assertion a_check failed") is False

    def test_vopt_warning_does_not_block_environment_classification(self):
        """vopt 告警 + DPI 加载故障同时出现 → 仍然是**环境**故障。

        原来那句"全篇没有 `vopt-NNNN` 才算环境级"会被一条覆盖率告警带偏，
        把干净的环境抖动判成 RTL 有错。
        """
        log = self.VOPT_WARNING + DPI_LOAD_FAILURE
        design, env = classify_sim_failures(log)
        assert not design, f"环境故障被误判成设计错误：{design}"
        assert any("vsim-3772" in line for line in env)


class TestHangIsNotAFunctionalFailure:
    """仿真挂死/看门狗超时**不算功能失败** —— 那是 bench/激励侧的事。

    把它算进去的代价很具体：决策引擎按 `REFACTOR_RTL` 去改 RTL。实测真跑了一轮
    `design_fix`，改的是没坏的代码（覆盖率缺口补出来的激励随机到对手方不应答的
    事务，driver 永远等下去，看门狗把整场仿真掐掉）。
    """

    #: 实测那份日志的结尾
    WATCHDOG_LOG = """\
# UVM_INFO .../apb_gap_seq.sv(11): uvm_test_top.env.apb_agent_h.sequencer@@_gseq [GAPSEQ] Directed gap stimulation
# UVM_FATAL .../apb_uart_env_sim_end.sv(77): uvm_test_top.env.sim_end_h [SIM_WATCHDOG] watchdog timeout: 仿真 100000 ns 内没有结束（疑似挂死）
"""

    def _run_dir(self, tmp_path, log_text):
        d = tmp_path / "regression_run" / "build_build_dut" / "test_case_x"
        d.mkdir(parents=True)
        (d / "sim_vsim.log").write_text(log_text, encoding="utf-8")
        return tmp_path / "regression_run"

    def test_watchdog_timeout_is_collected(self, tmp_path):
        from src.runtime_plane.infrastructure.infrastructure import collect_hung_tests

        root = self._run_dir(tmp_path, self.WATCHDOG_LOG)
        hung = collect_hung_tests(root)
        assert len(hung) == 1
        assert "SIM_WATCHDOG" in hung[0]

    def test_clean_log_is_not_collected(self, tmp_path):
        from src.runtime_plane.infrastructure.infrastructure import collect_hung_tests

        root = self._run_dir(tmp_path, "# Errors: 0, Warnings: 0\n")
        assert collect_hung_tests(root) == []

    def test_gapseq_timeout_is_also_collected(self, tmp_path):
        """激励自己的超时（比看门狗早）同样归到这一类。"""
        from src.runtime_plane.infrastructure.infrastructure import collect_hung_tests

        root = self._run_dir(
            tmp_path,
            '# UVM_ERROR [GAPSEQ] 定向激励超时：20000 ns 内对手方未应答（bench/激励侧问题）\n')
        assert len(collect_hung_tests(root)) == 1


class TestValidateRegressReportPath:
    """`validate_regress` 要看**回归自己的**报告，不是收尾才写的审计判定。"""

    def _validate(self, root):
        return validate_regress({}, str(root))

    def test_reads_the_regression_frameworks_own_report(self, tmp_path):
        run_dir = tmp_path / "regression_run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text(json.dumps(
            {"total": 25, "stats": {"pass": 25, "fail": 0, "unknown": 0}}),
            encoding="utf-8")
        result = self._validate(tmp_path)
        assert not result.issues, result.issues
        assert result.verdict == Verdict.PASS

    def test_partial_pass_is_an_issue(self, tmp_path):
        run_dir = tmp_path / "regression_run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text(json.dumps(
            {"total": 25, "stats": {"pass": 23, "fail": 2, "unknown": 0}}),
            encoding="utf-8")
        result = self._validate(tmp_path)
        assert any("23/25" in i for i in result.issues)

    def test_ops_phase_is_not_blamed_for_missing_coverage(self, tmp_path):
        """ops 阶段不产覆盖率（那是 coverage 节点的活）—— 不带的输出不该报 issue。"""
        run_dir = tmp_path / "regression_run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text(json.dumps(
            {"total": 3, "stats": {"pass": 3, "fail": 0, "unknown": 0}}),
            encoding="utf-8")
        assert not self._validate(tmp_path).issues

    def test_coverage_present_but_zero_is_an_issue(self, tmp_path):
        """真带了覆盖率数据、而它是 0 —— 那才是真问题。"""
        run_dir = tmp_path / "regression_run"
        run_dir.mkdir()
        (run_dir / "report.json").write_text(json.dumps(
            {"total": 3, "stats": {"pass": 3, "fail": 0, "unknown": 0}}),
            encoding="utf-8")
        result = validate_regress({"coverage": {"overall_pct": 0}}, str(tmp_path))
        assert any("coverage" in i for i in result.issues)

    def test_missing_report_is_reported(self, tmp_path):
        assert any("not found" in i for i in self._validate(tmp_path).issues)
