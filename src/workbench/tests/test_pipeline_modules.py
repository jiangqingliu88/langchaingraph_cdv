"""三个流程视图 —— 运行历史 / 验证流程 / 证据产物。

这套测试用一个**假图**跑真的闭环（见 tests/test_run_streaming.py 里同样的做法）：
真图要 LLM 与 EDA，而这里要验证的是"界面能不能跟着一次运行跑起来"。
假图仍然是真的 `StateGraph(PipelineState)`，所以状态、reducer、日志格式全是真的。
"""
from __future__ import annotations

import time

import pytest

from ...layers.l2_orchestration import graph as graph_mod
from ...layers.l2_orchestration.state import PipelineState

MODULES = ("vms.pipeline", "vms.runs", "vms.evidence")


# ═══════════════════════════════════════════════════════════════
# 假图
# ═══════════════════════════════════════════════════════════════

def _fake_graph(checkpointer=None, store=None, *, fail: bool = False):
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        return {"spec": {"name": "demo"},
                "phases": [{"name": "design", "status": "passed", "time": 1}]}

    def n_ops(state):
        if fail:
            raise RuntimeError("仿真炸了")
        return {"regression": {"passed": 3}}

    def n_coverage(state):
        return {"coverage": {"line": 0.9}, "functional_coverage": 82.0,
                "effective_coverage": 88.0, "round_num": 1}

    def n_finalize(state):
        return {"result": {"status": "PASS", "converged": True,
                           "final_coverage": 91.0, "effective_coverage": 88.0,
                           "iterations": 1,
                           "phases": [{"name": "design", "status": "passed"}]}}

    for name, fn in (("design", n_design), ("ops", n_ops),
                     ("coverage", n_coverage), ("finalize", n_finalize)):
        g.add_node(name, fn)
    g.add_edge(START, "design")
    g.add_edge("design", "ops")
    g.add_edge("ops", "coverage")
    g.add_edge("coverage", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


# ═══════════════════════════════════════════════════════════════
# 夹具
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def service(tmp_path, monkeypatch):
    """把运行服务钉在 tmp_path 上 —— 测试不碰开发机上真实的 output/。"""
    from ...layers.l2_orchestration import run_service as rs
    from ...layers.l2_orchestration.execution import PipelineExecutionService

    PipelineExecutionService.get_instance()._initialized = True
    monkeypatch.setattr(graph_mod, "build_closed_loop_graph", lambda **kw: _fake_graph(**kw))
    svc = rs.RunService(output_base=str(tmp_path))
    monkeypatch.setattr(rs, "_service", svc)
    yield svc
    svc.shutdown(timeout=5)


@pytest.fixture
def window(qt_app, settings, service, tmp_path):
    """装着真清单的真窗口（含三个流程模块）。"""
    from .conftest import make_ctx, make_window, shipped_manifest

    manifest, manifest_path = shipped_manifest()
    win = make_window(qt_app, make_ctx(manifest, manifest_path, settings))
    yield win
    win.manager.mark_all_clean()
    win.close()
    win.deleteLater()
    qt_app.processEvents()


def module_of(window, module_id: str):
    module = window.manager.module(module_id)
    assert module is not None, f"{module_id} 没建出来：{window.manager.failures()}"
    return module


def _wait_until(pred, timeout: float = 20.0) -> bool:
    """轮询等待 —— 运行在别的线程上，用固定 sleep 猜时机会 flaky。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


def _run_once(service, tmp_path, **kw):
    from ...layers.l2_orchestration.run_service import RunRequest
    request = RunRequest(spec_text="# 假规格", output_root=str(tmp_path / "run"),
                         target=95.0, max_rounds=1, **kw)
    run_id = service.start(request)
    service.wait(run_id, timeout=20)
    return run_id


# ═══════════════════════════════════════════════════════════════
# 清单接线
# ═══════════════════════════════════════════════════════════════

class TestManifestWiring:
    def test_three_modules_are_declared_and_built(self, window):
        for module_id in MODULES:
            assert window.manager.module(module_id) is not None, module_id
        assert window.manager.failures() == {}

    def test_they_land_in_the_expected_panes(self, window):
        def area_of(module_id: str) -> str:
            host = window.panes.pane_of(module_id)
            return next(a for a in ("center", "left", "right", "bottom")
                        if window.panes.pane(a) is host)

        assert area_of("vms.runs") == "left"
        assert area_of("vms.pipeline") == "center"
        assert area_of("vms.evidence") == "right"

    def test_evidence_subscribes_to_run_selection(self, window):
        """清单里的 `params.subscribe` 要真的接上总线。"""
        assert window.ctx.bus.subscribers("run.selected") >= 1

    def test_every_tool_the_modules_need_is_bound(self, window):
        from ..bridge.catalog import default_registry
        registry = default_registry()
        for name in ("pipeline.start", "pipeline.cancel", "pipeline.runs",
                     "pipeline.journal", "pipeline.status", "pipeline.detail",
                     "pipeline.approval_handler", "pipeline.answer_approval",
                     "pipeline.pending_approval", "pipeline.resume"):
            assert registry.has(name), name


# ═══════════════════════════════════════════════════════════════
# 运行历史（左）
# ═══════════════════════════════════════════════════════════════

class TestRunsModule:
    def test_empty_by_default(self, window):
        module = module_of(window, "vms.runs")
        module.refresh()
        assert module.tree.topLevelItemCount() == 0
        assert "0 次运行" in module.count_label.text()

    def test_lists_a_finished_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.runs")
        module.refresh()
        assert module.tree.topLevelItemCount() == 1
        assert run_id in module.tree.topLevelItem(0).text(0)

    def test_stages_hang_under_the_run(self, window, service, tmp_path):
        _run_once(service, tmp_path)
        module = module_of(window, "vms.runs")
        module.refresh()
        labels = [module.tree.topLevelItem(0).child(i).text(0).strip()
                  for i in range(module.tree.topLevelItem(0).childCount())]
        assert "编译与仿真回归" in labels

    def test_selecting_broadcasts_run_selected(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        seen = []
        window.ctx.bus.subscribe("run.selected", seen.append)
        module = module_of(window, "vms.runs")
        module.refresh()
        assert module.selected_run_id() == run_id
        assert seen and seen[-1] == run_id

    def test_follow_latest_picks_the_newest(self, window, service, tmp_path):
        _run_once(service, tmp_path)
        second = _run_once(service, tmp_path)
        module = module_of(window, "vms.runs")
        module.btn_latest.setChecked(True)
        module.refresh()
        assert module.selected_run_id() == second


# ═══════════════════════════════════════════════════════════════
# 验证流程（中）
# ═══════════════════════════════════════════════════════════════

class TestPipelineModule:
    def test_follows_a_selected_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        assert module.run_id == run_id
        assert module.timeline.topLevelItemCount() >= 1

    def test_poll_is_incremental(self, window, service, tmp_path):
        """轮询只取新增 —— 否则每 500ms 把整份日志重读一遍并重复追加。"""
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        first = len(module._events)
        module.poll()
        assert len(module._events) == first
        assert first > 0

    def test_timeline_groups_by_round(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        groups = [module.timeline.topLevelItem(i).text(0)
                  for i in range(module.timeline.topLevelItemCount())]
        assert groups and all(g.startswith("轮次") for g in groups)

    def test_selecting_a_stage_shows_its_payload(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        stage_item = module.timeline.topLevelItem(0).child(0)
        stage_item.setSelected(True)
        assert "kind" in module.detail.toPlainText()

    def test_the_log_view_shows_the_event_stream(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        text = module.log_view.toPlainText()
        assert "编译与仿真回归" in text

    def test_start_and_cancel_are_reachable_from_the_module(self, window, tmp_path):
        """按钮的处理器真的会把运行启起来 —— 不是只有 bridge 那一层能调。"""
        module = module_of(window, "vms.pipeline")
        module.spec_edit.setText("")
        module.start_run()
        assert module.run_id
        # 刚 start() 那一瞬间日志还没落盘（工人在另一条线程上），所以等它出现
        assert _wait_until(lambda: module.run_id in [
            r["run_id"] for r in window.ctx.call_tool("pipeline.runs")["runs"]])
        window.ctx.call_tool("pipeline.cancel", force=True, run_id=module.run_id)
        time.sleep(0.2)
        module.poll()

    def test_preset_fills_the_controls(self, window):
        module = module_of(window, "vms.pipeline")
        index = module.preset_box.findData(
            next(p for p in module._presets() if p["id"] == "smoke"))
        module.preset_box.setCurrentIndex(index)
        assert module.rounds_spin.value() == 1
        assert module.target_spin.value() == 60.0
        assert module.approval_box.currentData() == "auto"

    def test_state_label_reflects_a_finished_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        module.poll()
        assert "已完成" in module.state_label.text()

    def test_failure_is_visible_not_silent(self, window, service, tmp_path,
                                           monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                            lambda **kw: _fake_graph(fail=True, **kw))
        from ...layers.l2_orchestration.run_service import RunRequest
        run_id = service.start(RunRequest(spec_text="x",
                                          output_root=str(tmp_path / "bad"),
                                          target=95.0, max_rounds=1))
        with pytest.raises(Exception):
            service.wait(run_id, timeout=20)
        module = module_of(window, "vms.pipeline")
        module.on_refresh(run_id)
        assert "失败" in module.state_label.text()
        assert "失败" in module.log_view.toPlainText()


# ═══════════════════════════════════════════════════════════════
# 审批
# ═══════════════════════════════════════════════════════════════

class TestApprovalDialog:
    def test_confirm_approval_maps_buttons(self, window, monkeypatch):
        """默认实现弹模态框；这里换掉它，验证的是**答案的映射**。"""
        module = module_of(window, "vms.pipeline")
        monkeypatch.setattr(module, "confirm_approval", lambda req: "reject")

        class _Request:
            stage, summary, token = "REFACTOR_RTL", "时序改了", "ap-1"

        sent = []
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: sent.append(kw) or {"answered": True})
        module.on_approval_requested(_Request())
        assert sent and sent[0]["decision"] == "reject"

    def test_a_late_answer_is_reported_not_swallowed(self, window, monkeypatch):
        """超时已经降级为 SKIP —— 用户再点一下不能静默当作没发生。"""
        module = module_of(window, "vms.pipeline")
        monkeypatch.setattr(module, "confirm_approval", lambda req: "approve")
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: {"answered": False})
        logged = []
        monkeypatch.setattr(module, "log",
                            lambda text, level="info": logged.append(text))

        class _Request:
            stage, summary, token = "REFACTOR_RTL", "x", "ap-2"

        module.on_approval_requested(_Request())
        assert any("无人等待" in line for line in logged)

    def test_handler_is_installed_on_the_service(self, window, service):
        """模块构造时就把"有人要审批了"接上了 —— 运行线程靠它找到界面。"""
        assert service._approval_handler is not None

    def test_service_uses_event_channel_when_someone_listens(self, window, service):
        """`window` 这个参数是本条测试的**实质部分**：装上 handler 的是模块，
        不建窗口就没有人听，服务自然回落到终端通道。"""
        assert service._channel_for() is not None

    def test_no_handler_means_the_terminal_channel(self, tmp_path, monkeypatch):
        """无头 CLI 的行为必须不变：没人听就走 create_approval_gate 的默认通道。"""
        from ...layers.l2_orchestration import run_service as rs
        fresh = rs.RunService(output_base=str(tmp_path))
        assert fresh._channel_for() is None
        fresh.shutdown(timeout=2)


class TestApprovalBar:
    """检查点模式的审批 —— 运行停在检查点上，按钮按下去是**重入**。"""

    @staticmethod
    def _shown(module) -> bool:
        """审批条显示了没有。

        **不能用 `isVisible()`**：窗口没 show 的时候它恒为 False，而测试不 show
        窗口。`isVisibleTo(父控件)` 问的是"相对父控件它是不是可见的"，正是这里
        要验的东西（同一个坑本仓库在窗格那边踩过一次）。
        """
        return module.approval_bar.isVisibleTo(module.content)

    def test_hidden_when_nothing_is_pending(self, window, service, tmp_path):
        _run_once(service, tmp_path)
        module = module_of(window, "vms.pipeline")
        module.poll()
        assert self._shown(module) is False

    def test_shows_when_the_run_is_paused(self, window, service, tmp_path,
                                          monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph", _gated_graph)
        module = _pause_a_run(window, service, tmp_path)
        assert self._shown(module) is True
        assert "REFACTOR_RTL" in module.approval_label.text()
        assert "等待审批" in module.state_label.text()

    def test_the_bar_is_not_modal(self, window, service, tmp_path, monkeypatch):
        """做成条而不是弹框：检查点模式下**没有谁被挂住**，弹模态是假装它在等，
        顺手还把界面锁了 —— 而"先去干别的、想好了再来批"正是接检查点换来的。"""
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph", _gated_graph)
        module = _pause_a_run(window, service, tmp_path)
        assert module.approval_bar.isWindow() is False
        assert module.approval_bar.parent() is not None

    def test_pressing_a_button_resumes_the_run(self, window, service, tmp_path,
                                               monkeypatch):
        """按钮 → 重入 → 跑完，这条链子要真的通。"""
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph", _gated_graph)
        module = _pause_a_run(window, service, tmp_path)
        run_id = module.run_id

        module.answer_approval("approve")
        service.wait(run_id, timeout=30)
        assert _wait_until(lambda: _poll_until_done(module))
        assert "已完成" in module.state_label.text()
        assert self._shown(module) is False

    def test_rejecting_from_the_bar_lands_the_decision(self, window, service,
                                                       tmp_path, monkeypatch):
        monkeypatch.setattr(graph_mod, "build_closed_loop_graph", _gated_graph)
        module = _pause_a_run(window, service, tmp_path)
        run_id = module.run_id

        module.answer_approval("reject")
        service.wait(run_id, timeout=30)
        from ...layers.l2_orchestration.run_journal import read_journal
        from ...layers.l2_orchestration.run_repository import RunRepository
        run_dir = RunRepository(str(tmp_path)).run_dir(run_id)
        decided = [e for e in read_journal(run_dir) if e.kind == "run.resumed"]
        assert decided and decided[0].payload["decision"] == "reject"


def _gated_graph(checkpointer=None, store=None, **kw):
    """design → approval(interrupt) → finalize —— 检查点模式的暂停/重入。"""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        return {"spec": {"n": 1},
                "phases": [{"name": "design", "status": "passed"}]}

    def n_approval(state, config):
        from langgraph.types import interrupt
        answer = interrupt({"kind": "approval", "stage": "REFACTOR_RTL",
                            "risk_level": "high", "reason": "时序改了",
                            "token": "ap-1"})
        return {"approval_outcome": str(answer),
                "phases": [{"name": "approval", "status": str(answer)}]}

    def n_finalize(state):
        return {"result": {"status": "PASS", "converged": True,
                           "final_coverage": 93.0, "iterations": 1,
                           "phases": []}}

    g.add_node("design", n_design)
    g.add_node("approval", n_approval)
    g.add_node("finalize", n_finalize)
    g.add_edge(START, "design")
    g.add_edge("design", "approval")
    g.add_edge("approval", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


def _pause_a_run(window, service, tmp_path):
    """起一次会暂停的运行，并让界面跟上它。返回 pipeline 模块。"""
    run_id = _run_once(service, tmp_path, approval="interactive")
    module = module_of(window, "vms.pipeline")
    module.on_refresh(run_id)
    module.poll()
    return module


def _poll_until_done(module) -> bool:
    module.poll()
    return "已完成" in module.state_label.text()


# ═══════════════════════════════════════════════════════════════
# 证据 / 产物（右）
# ═══════════════════════════════════════════════════════════════

class TestEvidenceModule:
    def test_shows_the_journal_file(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.evidence")
        module.load(run_id)
        names = _tree_text(module.tree)
        assert "run_events.jsonl" in names
        assert run_id in module.title_label.text()

    def test_coverage_rows_come_from_the_journal(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.evidence")
        module.load(run_id)
        rows = module.coverage_model.rows          # 是个 property，不是方法
        assert rows and rows[0]["功能覆盖率"] == "82.0%"

    def test_follows_run_selection(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "vms.evidence")
        window.ctx.bus.publish("run.selected", run_id)
        assert module.run_id == run_id

    def test_a_missing_directory_says_so(self, window):
        module = module_of(window, "vms.evidence")
        module._fill_files("definitely-not-here")
        assert "找不到产物目录" in _tree_text(module.tree)

    def test_preview_refuses_binary_files(self, window, tmp_path):
        (tmp_path / "wave.vcd").write_bytes(b"\x00\x01\x02")
        module = module_of(window, "vms.evidence")
        module._fill_files(str(tmp_path))
        item = module.tree.topLevelItem(0)
        item.setSelected(True)
        assert "二进制" in module.preview.toPlainText()

    def test_preview_shows_text_files(self, window, tmp_path):
        (tmp_path / "manifest.json").write_text('{"a": 1}', encoding="utf-8")
        module = module_of(window, "vms.evidence")
        module._fill_files(str(tmp_path))
        module.tree.topLevelItem(0).setSelected(True)
        assert '"a": 1' in module.preview.toPlainText()


def _tree_text(tree) -> str:
    out = []

    def walk(item):
        out.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return "\n".join(out)
