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

MODULES = ("flow.pipeline", "flow.runs", "flow.evidence")


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
    # center 模块懒加载（工作区默认空）—— 本文件测的是它们，替用户"点"一遍
    for module_id in MODULES:
        win.manager.open(module_id)
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
        area_of = window.manager.pane_of

        assert area_of("flow.runs") == "left"
        assert area_of("flow.pipeline") == "center"
        assert area_of("flow.evidence") == "right"

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
        module = module_of(window, "flow.runs")
        module.refresh()
        assert module.tree.topLevelItemCount() == 0
        assert "0 次运行" in module.count_label.text()

    def test_lists_a_finished_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.runs")
        module.refresh()
        assert module.tree.topLevelItemCount() == 1
        assert run_id in module.tree.topLevelItem(0).text(0)

    def test_stages_hang_under_the_run(self, window, service, tmp_path):
        _run_once(service, tmp_path)
        module = module_of(window, "flow.runs")
        module.refresh()
        labels = [module.tree.topLevelItem(0).child(i).text(0).strip()
                  for i in range(module.tree.topLevelItem(0).childCount())]
        assert "编译与仿真回归" in labels

    def test_selecting_broadcasts_run_selected(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        seen = []
        window.ctx.bus.subscribe("run.selected", seen.append)
        module = module_of(window, "flow.runs")
        module.refresh()
        assert module.selected_run_id() == run_id
        # payload 走契约形状（dict，见 topics.RunSelected）；run_id_of 兼容旧字符串
        from src.workbench.bus import run_id_of
        assert seen and run_id_of(seen[-1]) == run_id
        assert seen[-1]["run_id"] == run_id

    def test_follow_latest_picks_the_newest(self, window, service, tmp_path):
        _run_once(service, tmp_path)
        second = _run_once(service, tmp_path)
        module = module_of(window, "flow.runs")
        module.btn_latest.setChecked(True)
        module.refresh()
        assert module.selected_run_id() == second


# ═══════════════════════════════════════════════════════════════
# 验证流程（中）
# ═══════════════════════════════════════════════════════════════

class TestPipelineModule:
    def test_follows_a_selected_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        assert module.run_id == run_id
        assert module.timeline.topLevelItemCount() >= 1

    def test_poll_is_incremental(self, window, service, tmp_path):
        """轮询只取新增 —— 否则每 500ms 把整份日志重读一遍并重复追加。"""
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        first = len(module._events)
        module.poll()
        assert len(module._events) == first
        assert first > 0

    def test_timeline_groups_by_round(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        groups = [module.timeline.topLevelItem(i).text(0)
                  for i in range(module.timeline.topLevelItemCount())]
        assert groups and all(g.startswith("轮次") for g in groups)

    def test_selecting_a_stage_shows_its_payload(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        stage_item = module.timeline.topLevelItem(0).child(0)
        stage_item.setSelected(True)
        assert "kind" in module.detail.toPlainText()

    def test_the_log_view_shows_the_event_stream(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        text = module.log_view.toPlainText()
        assert "编译与仿真回归" in text

    def test_start_and_cancel_are_reachable_from_the_module(self, window, tmp_path):
        """按钮的处理器真的会把运行启起来 —— 不是只有 bridge 那一层能调。"""
        module = module_of(window, "flow.pipeline")
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
        module = module_of(window, "flow.pipeline")
        index = module.preset_box.findData(
            next(p for p in module._presets() if p["id"] == "smoke"))
        module.preset_box.setCurrentIndex(index)
        assert module.rounds_spin.value() == 1
        assert module.target_spin.value() == 60.0
        assert module.approval_box.currentData() == "auto"

    def test_state_label_reflects_a_finished_run(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.pipeline")
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
        module = module_of(window, "flow.pipeline")
        module.on_refresh(run_id)
        assert "失败" in module.state_label.text()
        assert "失败" in module.log_view.toPlainText()


# ═══════════════════════════════════════════════════════════════
# 审批
class TestStartAnnouncesTheRun:
    """点「启动」之后，**别的页要跟着切过去**。

    此前 `pipeline.start` 只管自己：新运行的 run_id 从不广播，而全工作台只有
    `运行历史` 会发 `run.selected`（还得等用户点一下）。于是启动之后，订阅了
    `run.selected` 的那些页 —— 流程视图 / 证据 / 签核判定 / 决策轨迹 / 运行清单 /
    七条 agent 产出 —— 全都还停在**上一次**运行上。表现就是"点了启动，别的页不刷新"。
    """

    def test_start_run_publishes_run_selected(self, window, monkeypatch):
        module = module_of(window, "flow.pipeline")
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: {"run_id": "run-fresh"})
        seen = []
        window.ctx.bus.subscribe("run.selected", seen.append)

        module.start_run()

        from src.workbench.bus import run_id_of
        assert [run_id_of(p) for p in seen] == ["run-fresh"],             f"新运行没有广播出去：{seen}"

    def test_the_broadcast_does_not_loop_back(self, window, monkeypatch):
        """自己也订阅着这个话题 —— 守卫（run_id 没变就不重载）必须挡住回声。"""
        module = module_of(window, "flow.pipeline")
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: {"run_id": "run-fresh"})
        calls = []
        monkeypatch.setattr(module, "follow", lambda rid: calls.append(rid))

        module.start_run()

        assert calls == [], "广播绕回了自己，会重复加载同一个运行"


# ═══════════════════════════════════════════════════════════════
# 审批
# ═══════════════════════════════════════════════════════════════

class TestApprovalDialog:
    def test_confirm_approval_maps_buttons(self, window, monkeypatch):
        """默认实现弹模态框；这里换掉它，验证的是**答案的映射**。"""
        module = module_of(window, "flow.pipeline")
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
        module = module_of(window, "flow.pipeline")
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
        module = module_of(window, "flow.pipeline")
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


class TestApprovalArtifacts:
    """审批条要说出"你在批准**什么文件**"。

    在此之前审批条上只有一句引擎理由（"功能覆盖 62%"）—— 人根本不知道自己要批的
    是哪几份产物。而卡住运行的恰恰是这些中间 YAML（实测一次 `bench.yaml` 的 schema
    不符让整次运行挂在 verify）。

    payload 里的产物清单是**裁剪过**的（只有 path/group/exists/errors/warnings）：
    它要进检查点和运行日志，带 sha256 与逐条诊断会把它们撑肥。所以这里只回答
    「哪几份有问题、几处」，详情去「产物审查」页看。
    """

    @staticmethod
    def _status(payload: Dict[str, Any]) -> Dict[str, Any]:
        """伪造界面读的那一份 —— 与 journal 的 `run.interrupted` 同形。"""
        return {"last": {"payload": payload}}

    def test_the_broken_artifacts_are_named(self, window):
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "summary": "看覆盖率缺口再决定", "token": "ap-3",
            "artifacts": [
                {"path": "inputs/yaml/uvm/bench.yaml", "group": "验证·UVM",
                 "exists": True, "errors": 4, "warnings": 0},
                {"path": "inputs/yaml/uvm/env.yaml", "group": "验证·UVM",
                 "exists": True, "errors": 2, "warnings": 0},
                {"path": "spec.json", "group": "设计",
                 "exists": True, "errors": 0, "warnings": 0},
            ]}))
        text = module.approval_label.text()
        assert "bench.yaml ✗4 处" in text
        assert "env.yaml ✗2 处" in text
        assert "spec.json" not in text          # 好的那份不占版面

    def test_the_declared_prompt_wins_over_the_engine_reason(self, window):
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "summary": "看覆盖率缺口再决定",
            "reason": "功能覆盖 62%", "token": "ap-3"}))
        assert "看覆盖率缺口再决定" in module.approval_label.text()

    def test_a_clean_run_says_so(self, window):
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "token": "ap-1",
            "artifacts": [{"path": "a.yaml", "exists": True, "errors": 0,
                           "warnings": 0}]}))
        assert "schema 都过" in module.approval_label.text()

    def test_missing_artifacts_are_counted_not_hidden(self, window):
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "token": "ap-1",
            "artifacts": [{"path": "a.yaml", "exists": False, "errors": 0,
                           "warnings": 0},
                          {"path": "b.yaml", "exists": True, "errors": 0,
                           "warnings": 0}]}))
        assert "1 份还没生成" in module.approval_label.text()

    def test_a_payload_without_artifacts_still_renders(self, window):
        """老 payload（没有 artifacts 键）不能让审批条空白 —— 它还得说判什么。"""
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "reason": "时序改了", "token": "ap-1"}))
        text = module.approval_label.text()
        assert "REFACTOR_RTL" in text and "时序改了" in text

    @pytest.mark.parametrize("value", [None, [], "不是列表", {}])
    def test_a_malformed_artifact_value_does_not_crash(self, window, value):
        module = module_of(window, "flow.pipeline")
        module._sync_approval_bar("waiting", self._status({
            "stage": "REFACTOR_RTL", "token": "ap-1", "artifacts": value}))
        assert "REFACTOR_RTL" in module.approval_label.text()


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
    module = module_of(window, "flow.pipeline")
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
        module = module_of(window, "flow.evidence")
        module.load(run_id)
        names = _tree_text(module.tree)
        assert "run_events.jsonl" in names
        assert run_id in module.title_label.text()

    def test_coverage_rows_come_from_the_journal(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.evidence")
        module.load(run_id)
        rows = module.coverage_model.rows          # 是个 property，不是方法
        assert rows and rows[0]["功能覆盖率"] == "82.0%"

    def test_follows_run_selection(self, window, service, tmp_path):
        run_id = _run_once(service, tmp_path)
        module = module_of(window, "flow.evidence")
        window.ctx.bus.publish("run.selected", run_id)
        assert module.run_id == run_id

    def test_a_missing_directory_says_so(self, window):
        module = module_of(window, "flow.evidence")
        module._fill_files("definitely-not-here")
        assert "找不到产物目录" in _tree_text(module.tree)

    def test_preview_refuses_binary_files(self, window, tmp_path):
        (tmp_path / "wave.vcd").write_bytes(b"\x00\x01\x02")
        module = module_of(window, "flow.evidence")
        module._fill_files(str(tmp_path))
        item = module.tree.topLevelItem(0)
        item.setSelected(True)
        assert "二进制" in module.preview.toPlainText()

    def test_preview_shows_text_files(self, window, tmp_path):
        (tmp_path / "manifest.json").write_text('{"a": 1}', encoding="utf-8")
        module = module_of(window, "flow.evidence")
        module._fill_files(str(tmp_path))
        module.tree.topLevelItem(0).setSelected(True)
        assert '"a": 1' in module.preview.toPlainText()


# ═══════════════════════════════════════════════════════════════
# 仿真业务（工具栏下拉 → 这次运行）
# ═══════════════════════════════════════════════════════════════

class TestSimModeReachesTheRun:
    """「仿真业务」是**这次运行的输入**，不是只写了个文件。

    链子长：工具栏下拉 → `.signoffai/sim_modes.json`（项目级记忆）→
    `pipeline.start(sim_modes=…)` → `RunRequest` → 回归框架的 `MODE_OPTS`。
    这里钉的是中间那一跳 —— 前面写好了、最后一步没接上，表现就是
    "下拉换了，回归还是照旧跑"，而且什么都不报。
    """

    def _capture(self, window, monkeypatch):
        module = module_of(window, "flow.pipeline")
        seen = {}

        def _fake(name, *a, **kw):
            seen.update(kw)
            return {"run_id": "run-sim"}

        monkeypatch.setattr(module, "run_tool", _fake)
        return module, seen

    def test_start_run_sends_the_stored_mode(self, window, monkeypatch, tmp_path):
        from .. import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "sim_modes.json")
        ui.save("wave")
        module, seen = self._capture(window, monkeypatch)

        module.start_run()

        assert seen.get("sim_modes") == ["wave"]

    def test_no_mode_is_sent_as_an_empty_list(self, window, monkeypatch, tmp_path):
        """选了「无」要传**空表** —— 传下去的是默认值就变成覆盖率了，那不是人的意思。"""
        from .. import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "sim_modes.json")
        ui.save(ui.NONE_MODE)
        module, seen = self._capture(window, monkeypatch)

        module.start_run()

        assert seen.get("sim_modes") == []


class TestSimModePicker:
    """工具栏上那个下拉本身 —— 条目来自工具层的表，默认覆盖率。"""

    def test_lives_on_the_window_toolbar(self, window):
        assert window.sim_mode_box is not None
        data = [window.sim_mode_box.itemData(i)
                for i in range(window.sim_mode_box.count())]
        from .. import sim_modes as ui
        assert data == [i["mode"] for i in ui.mode_items()]
        assert "cov" in data          # 覆盖率在列表里（默认也是它）

    def test_picking_remembers(self, window, monkeypatch, tmp_path):
        """选中就落盘 —— 不落盘的话下次开工作台又回到覆盖率（静默丢选择）。"""
        from .. import sim_modes as ui

        store = tmp_path / "sim_modes.json"
        monkeypatch.setattr(ui, "STORE", store)
        index = window.sim_mode_box.findData("wave")
        window.sim_mode_box.setCurrentIndex(index)

        assert ui.load() == "wave"

    def test_switching_mode_does_not_touch_a_running_run(self, window, monkeypatch,
                                                        tmp_path):
        """换下拉**不该**去改已经在跑的那一轮 —— 它是运行的输入，要记账。

        这条是"刻意不做的事"，钉住它免得以后有人顺手加个"立即生效"。
        """
        from .. import sim_modes as ui

        monkeypatch.setattr(ui, "STORE", tmp_path / "sim_modes.json")
        module = module_of(window, "flow.pipeline")
        module.run_id = "run-already-going"
        calls = []
        monkeypatch.setattr(module, "run_tool",
                            lambda *a, **kw: calls.append(kw) or {})
        window.sim_mode_box.setCurrentIndex(window.sim_mode_box.findData("wave"))
        assert calls == []


def _tree_text(tree) -> str:
    out = []

    def walk(item):
        out.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return "\n".join(out)
