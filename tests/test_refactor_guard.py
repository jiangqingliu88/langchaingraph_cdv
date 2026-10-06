"""改 RTL 的**事务性**保证 —— 改前快照、改后按影响面重跑、破坏了就回滚。

为什么需要（实测）：闭环为了修一个 bug 去改 RTL，而**改完没有任何比对** ——
守卫（`GuardianAgent`）要的"黄金基线"只在收敛时才存，这闭环从没收敛过，于是
每一次改都被「无黄金基线，跳过守卫」放行；改完直接进下一轮，轮次用尽时直接
进 audit。也就是说"改一个 bug 把三个好用例改挂"这件事，原来没人会发现。

不变式只有一条：**改动前通过的用例，改动后必须仍然通过。**
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.layers.l1_infrastructure.refactor_guard import RefactorGuard

DESIGN = "apb_uart"


#: 用例名 → 它的 scenario tag。**真实的 tag 是概念**（APB / UART / FIFO），
#: 不是"用例名的最后一段" —— fixture 里要照实写，否则测不到真正的选择逻辑。
_TAGS = {"apb_uart_APB_basic": "APB", "apb_uart_UART_basic": "UART",
         "apb_uart_UART_only": "UART", "apb_uart_FIFO_basic": "FIFO",
         "apb_uart_RESET_basic": "reset"}


def _run_dir(tmp_path, rtl_files: dict, passing: list):
    """搭一个最小运行目录：rtl/ + 上一轮回归报告 + 回归配置（带 tags）。"""
    rtl = tmp_path / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    for name, text in rtl_files.items():
        (rtl / name).write_text(text, encoding="utf-8")

    reg = tmp_path / "regression_run"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "report.json").write_text(json.dumps(
        {"total": len(passing),
         "tasks": [{"name": f"test_{t}", "status": "pass"} for t in passing]}),
        encoding="utf-8")

    yml = tmp_path / "inputs" / "yaml"
    yml.mkdir(parents=True, exist_ok=True)
    lines = ["tests:"]
    for t in sorted(set(list(passing) + list(_TAGS))):
        lines.append(f"  - name: test_{t}")
        lines.append(f'    tags: ["p0", "{_TAGS.get(t, "misc")}"]')
    (yml / "regression.yaml").write_text("\n".join(lines), encoding="utf-8")
    return tmp_path


class TestSnapshot:

    def test_captures_content_and_passing_set(self, tmp_path):
        root = _run_dir(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// tx"},
                        ["apb_uart_APB_basic", "apb_uart_UART_basic"])
        snap = RefactorGuard(root, design_name=DESIGN).snapshot()
        assert set(snap.files) == {"apb_uart.sv", "uart_tx.sv"}
        assert snap.passing == ["apb_uart_APB_basic", "apb_uart_UART_basic"]

    def test_no_report_means_no_baseline(self, tmp_path):
        (tmp_path / "rtl").mkdir()
        (tmp_path / "rtl" / "a.sv").write_text("// a", encoding="utf-8")
        assert RefactorGuard(tmp_path, design_name=DESIGN).snapshot().passing == []


class TestScope:
    """能局部就局部，认不出来就全量 —— 漏跑的代价比多跑大得多。"""

    def _guard(self, tmp_path, rtl, passing):
        root = _run_dir(tmp_path, rtl, passing)
        g = RefactorGuard(root, design_name=DESIGN)
        return g, g.snapshot()

    def test_top_level_change_forces_full(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// v1", "uart_tx.sv": "// tx"},
                              ["apb_uart_APB_basic"])
        (g.rtl_dir / "apb_uart.sv").write_text("// v2", encoding="utf-8")
        scope = g.scope(snap)
        assert scope["mode"] == "full"
        assert "顶层" in scope["why"]

    def test_leaf_ip_change_selects_only_its_tag(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// tx"},
                              ["apb_uart_APB_basic", "apb_uart_UART_only"])
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        scope = g.scope(snap)
        assert scope["mode"] == "subset"
        assert scope["tags"] == "uart"

    def test_unknown_file_falls_back_to_full(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top", "zzz_thing.sv": "// x"},
                              ["apb_uart_APB_basic"])
        (g.rtl_dir / "zzz_thing.sv").write_text("// y", encoding="utf-8")
        assert g.scope(snap)["mode"] == "full"

    def test_no_change_needs_no_rerun(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top"}, ["apb_uart_APB_basic"])
        assert g.scope(snap)["mode"] == "none"

    def test_new_file_counts_as_change(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top"}, ["apb_uart_APB_basic"])
        (g.rtl_dir / "uart_new.sv").write_text("// new", encoding="utf-8")
        assert g.changed_files(snap) == ["uart_new.sv"]


class TestVerifyAndRollback:
    """比对的是"原先通过的用例"—— 修没修好那个 bug 是下一轮的事，这里只管别改坏。"""

    def _setup(self, tmp_path, passing, after_passing, change="// top v2"):
        root = _run_dir(tmp_path, {"apb_uart.sv": "// top"}, passing)
        g = RefactorGuard(root, design_name=DESIGN)
        snap = g.snapshot()
        # **必须真的改一下 RTL** —— 没改动时 `scope` 是 `none`，压根不会重跑
        (g.rtl_dir / "apb_uart.sv").write_text(change, encoding="utf-8")

        def fake_regression(**kwargs):
            # 重跑会把 regression_run 重写 —— 模拟新报告（含 seed 后缀以贴近真实）
            (root / "regression_run" / "report.json").write_text(json.dumps(
                {"total": len(after_passing),
                 "tasks": [{"name": f"test_{t}", "status": "pass"} for t in after_passing]}),
                encoding="utf-8")
            return {"status": "PASS", "passed": len(after_passing), "failed": 0}

        return g, snap, fake_regression

    def test_no_regression_when_everything_still_passes(self, tmp_path):
        passing = ["apb_uart_APB_basic", "apb_uart_UART_basic"]
        g, snap, run = self._setup(tmp_path, passing, passing)
        out = g.verify(snap, run_regression=run)
        assert out["ran"] is True
        assert out["regressed"] == []

    def test_regression_detected_when_a_passing_case_disappears(self, tmp_path):
        g, snap, run = self._setup(
            tmp_path,
            ["apb_uart_APB_basic", "apb_uart_UART_basic", "apb_uart_FIFO_basic"],
            ["apb_uart_APB_basic"])                      # 两个原本通过的没了
        out = g.verify(snap, run_regression=run)
        assert out["regressed"] == ["apb_uart_FIFO_basic", "apb_uart_UART_basic"]

    def test_missing_baseline_is_reported_not_treated_as_pass(self, tmp_path):
        root = _run_dir(tmp_path, {"apb_uart.sv": "// top"}, [])
        g = RefactorGuard(root, design_name=DESIGN)
        snap = g.snapshot()
        (g.rtl_dir / "apb_uart.sv").write_text("// v2", encoding="utf-8")
        out = g.verify(snap, run_regression=lambda **kw: {"status": "PASS"})
        assert out["ran"] is False
        assert "无法比对" in out["error"]

    def test_rerun_failure_does_not_claim_success(self, tmp_path):
        g, snap, _ = self._setup(tmp_path, ["apb_uart_APB_basic"], ["apb_uart_APB_basic"])

        def boom(**kwargs):
            raise RuntimeError("EDA 挂了")

        out = g.verify(snap, run_regression=boom)
        assert out["ran"] is False
        assert "重跑失败" in out["error"]

    def test_rollback_restores_modified_and_deleted_files(self, tmp_path):
        root = _run_dir(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// tx"},
                        ["apb_uart_APB_basic"])
        g = RefactorGuard(root, design_name=DESIGN)
        snap = g.snapshot()
        (g.rtl_dir / "apb_uart.sv").write_text("// 改坏了", encoding="utf-8")
        (g.rtl_dir / "uart_tx.sv").unlink()

        restored = g.rollback(snap)
        assert restored == ["apb_uart.sv", "uart_tx.sv"]
        assert (g.rtl_dir / "apb_uart.sv").read_text(encoding="utf-8") == "// top"
        assert (g.rtl_dir / "uart_tx.sv").read_text(encoding="utf-8") == "// tx"


# ════════════════════════════════════════════════════════════
# 验证计划：根因 → 跑多少 + 补什么验证
# ════════════════════════════════════════════════════════════

class TestVerificationPlanDrivesScope:
    """第三维（验证方式）是这三轴里唯一**驱动行为**的一轴 —— 它决定跑多少。

    依据是各类 bug 的**破坏面**：CDC 谁都在用 → 全量；协议/复位有现成定向用例
    → 必须带上；编译类只需编译门禁；死代码要人判。
    """

    def _guard(self, tmp_path):
        root = _run_dir(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// tx"},
                        ["apb_uart_APB_basic"])
        g = RefactorGuard(root, design_name=DESIGN)
        return g, g.snapshot()

    def test_cdc_forces_full_regression(self, tmp_path):
        from src.layers.l3_decision.decision_engine import FIX_CDC, verification_plan
        g, snap = self._guard(tmp_path)
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        scope = g.scope(snap, plan=verification_plan(FIX_CDC))
        assert scope["mode"] == "full"            # 局部改动也没用 —— CDC 强制全量
        assert "CDC" in scope["why"]

    def test_reset_pulls_in_its_own_tag(self, tmp_path):
        from src.layers.l3_decision.decision_engine import FIX_RESET, verification_plan
        g, snap = self._guard(tmp_path)
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        scope = g.scope(snap, plan=verification_plan(FIX_RESET))
        assert scope["mode"] == "subset" and "reset" in scope["tags"]

    def test_plan_tag_absent_from_regression_falls_back_to_full(self, tmp_path):
        """计划要的 tag 回归里没有 —— 退回全量，不假装跑过了。"""
        from src.layers.l3_decision.decision_engine import FIX_PROTOCOL, verification_plan
        g, snap = self._guard(tmp_path)
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        scope = g.scope(snap, plan=verification_plan(FIX_PROTOCOL))
        assert scope["mode"] == "full"            # fixture 里没有 handshake tag
        assert "退回全量" in scope["why"]

    def test_compile_class_does_not_run_the_full_regression(self, tmp_path):
        from src.layers.l3_decision.decision_engine import FIX_COMPILE, verification_plan
        g, snap = self._guard(tmp_path)
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        out = g.verify(snap, plan=verification_plan(FIX_COMPILE),
                       run_regression=lambda **kw: pytest.fail("不该跑回归"))
        assert out["ran"] is False
        assert "编译" in out["error"]

    def test_deadcode_class_hands_over_to_a_human(self, tmp_path):
        from src.layers.l3_decision.decision_engine import FIX_DEADCODE, verification_plan
        g, snap = self._guard(tmp_path)
        (g.rtl_dir / "uart_tx.sv").write_text("// tx v2", encoding="utf-8")
        out = g.verify(snap, plan=verification_plan(FIX_DEADCODE),
                       run_regression=lambda **kw: pytest.fail("不该跑回归"))
        assert out["ran"] is False and "人工" in out["error"]


class TestFixKindIsReadFromTheDiff:
    """修复手段是**改完才知道的**，从 diff 判、当记录用（不当决策依据）。"""

    def _guard(self, tmp_path, files):
        root = _run_dir(tmp_path, files, ["apb_uart_APB_basic"])
        g = RefactorGuard(root, design_name=DESIGN)
        return g, g.snapshot()

    def test_single_condition_change_is_logic(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// x"})
        (g.rtl_dir / "uart_tx.sv").write_text("assign tx = busy & valid;", encoding="utf-8")
        assert g.classify_fix_kind(["uart_tx.sv"], snap) == "logic"

    def test_added_synchronizer_is_sync_reset(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// x"})
        (g.rtl_dir / "uart_tx.sv").write_text(
            "always_ff @(posedge clk) begin\n  sync_q1 <= async_in;\n"
            "  sync_q2 <= sync_q1;\n  // 两级同步器\nend\n", encoding="utf-8")
        assert g.classify_fix_kind(["uart_tx.sv"], snap) == "sync_reset"

    def test_top_level_only_change_is_integration(self, tmp_path):
        g, snap = self._guard(tmp_path, {"apb_uart.sv": "// top", "uart_tx.sv": "// x"})
        (g.rtl_dir / "apb_uart.sv").write_text("// 改顶层连线", encoding="utf-8")
        assert g.classify_fix_kind(["apb_uart.sv"], snap) == "integration"


class TestEveryActionNameHasARoute:
    """**动作全集里的每个名字，图上都得有落点。**

    少一个不会在导入期报错，而是在跑到那一步时抛 `ValueError: 未映射的动作` ——
    也就是"改了决策层、忘了改路由"，只在真实闭环跑到那个分支时才炸。
    这条把两个模块钉在一起：`ALL_ACTIONS` 里加名字，这里立刻红。
    """

    @staticmethod
    def _action(action_type: str):
        from src.layers.l3_decision.decision_engine import Action
        return Action(action_type)

    def test_all_actions_route_without_raising(self):
        from src.layers.l2_orchestration.graph import r_action
        from src.layers.l3_decision.decision_engine import ALL_ACTIONS

        class _State:
            """`r_action` 只用 `state.action()`。"""

            def __init__(self, at):
                self._at = at

            def action(self):
                return TestEveryActionNameHasARoute._action(self._at)

        for name in ALL_ACTIONS:
            assert r_action(_State(name)) == name, f"{name} 没被路由（或名字被改）"

    def test_legacy_names_still_route(self):
        """RL 策略文件与历史轨迹里存的是老名字 —— 也得能路由。"""
        from src.layers.l2_orchestration.graph import r_action

        class _State:
            def __init__(self, at):
                self._at = at

            def action(self):
                return TestEveryActionNameHasARoute._action(self._at)

        assert r_action(_State("REFACTOR_RTL")) == "FIX_FUNCTIONAL_bug"
        assert r_action(_State("COMPILE_RETRY")) == "FIX_COMPILE_bug"
        assert r_action(_State("UPDATE_MODEL")) == "FIX_MODEL_bug"


class TestDesignFixReportsNoChange:
    """改设计这条路上，**"没改动任何 RTL"要如实失败**。

    实测：一轮 `design_fix` 报 PASS 90、只用了 9.5 秒，而 RTL 与改前逐字节相同
    （守卫那边的 `changed: []` 是准的）—— 文件写了、内容没变，对"修 bug"等于
    什么都没做，却占掉了这一轮的修复额度，界面上还是一片绿。
    """

    def test_fingerprint_and_diff_agree_with_the_guard(self, tmp_path):
        from src.agents.design.main import DesignAgent

        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "top.sv").write_text("// v1", encoding="utf-8")
        before = DesignAgent._rtl_fingerprint(tmp_path)

        # 没改 → 空；改了 → 有；删了 → 也算改动
        assert DesignAgent._rtl_diff(before, DesignAgent._rtl_fingerprint(tmp_path)) == []
        (rtl / "top.sv").write_text("// v2", encoding="utf-8")
        assert DesignAgent._rtl_diff(before, DesignAgent._rtl_fingerprint(tmp_path)) == ["top.sv"]
        (rtl / "new.sv").write_text("// new", encoding="utf-8")
        (rtl / "top.sv").unlink()
        changed = DesignAgent._rtl_diff(before, DesignAgent._rtl_fingerprint(tmp_path))
        assert changed == ["new.sv", "top.sv"]

    def test_rerun_with_identical_output_counts_as_no_change(self, tmp_path):
        """LLM 原样重写一遍（内容相同）—— 字节一样就不算改动。"""
        from src.agents.design.main import DesignAgent

        rtl = tmp_path / "rtl"
        rtl.mkdir()
        (rtl / "top.sv").write_text("// same", encoding="utf-8")
        before = DesignAgent._rtl_fingerprint(tmp_path)
        (rtl / "top.sv").write_text("// same", encoding="utf-8")   # 重写同样内容
        assert DesignAgent._rtl_diff(before, DesignAgent._rtl_fingerprint(tmp_path)) == []
