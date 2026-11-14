"""PySide6 三模式入口的离屏验证：只注入 Agent，不调用真实模型/EDA。"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from src.workbench.api import agent_mode_service
from src.workbench.modules.interaction.module import InteractionModule
from src.workbench.spec import ModuleSpec

from .conftest import make_ctx, make_window, shipped_manifest


def _module(ctx):
    spec = ModuleSpec(
        id="interaction.chat",
        title="交互与验证",
        group="project",
        factory="src.workbench.modules.interaction.module:InteractionModule",
    )
    module = InteractionModule(ctx, spec)
    # 禁止测试自行补接 TaskRunner 信号，必须覆盖生产模块的真实接收路径。
    module.create_widget()
    return module


def _drain(ctx, qt_app):
    assert ctx.tasks.wait(10_000)
    qt_app.processEvents()
    qt_app.processEvents()


def test_fresh_process_import_does_not_depend_on_api_load_order():
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    result = subprocess.run(
        [sys.executable, "-c", "from src.workbench.modules.interaction.module import InteractionModule"],
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, "GUI 的全新进程导入循环没有被消解"


def test_creation_has_three_explicit_modes_without_llm(qt_app, ctx, monkeypatch):
    invoked = []
    monkeypatch.setattr(agent_mode_service, "agent_turn", lambda *_a, **_k: invoked.append(1))
    module = _module(ctx)
    assert [module.mode.itemData(i) for i in range(module.mode.count())] == ["chat", "plan", "verify"]
    assert module.mode.isEnabled()
    assert not invoked
    assert not module._jobs
    assert module.approval.isHidden()


def test_send_uses_task_runner_and_preserves_paused_state(qt_app, ctx, tmp_path):
    module = _module(ctx)
    received = []

    def fake_agent(prompt, **kwargs):
        received.append((prompt, kwargs))
        return {
            "status": "paused",
            "summary": "需要审批",
            "session_id": "real-sid",
            "pending": {"kind": "approval", "tool": "run_verify", "reason": "运行前审批"},
        }

    module.agent_caller = fake_agent
    module.workspace.setText(str(tmp_path))
    module.question.setPlainText("检查握手候选方案")
    module.send_turn()
    assert module.send_button.isEnabled() is False
    _drain(ctx, qt_app)
    assert not module._jobs
    assert module.session_id == "real-sid"
    assert module.approval.isHidden() is False
    assert "run_verify" in module.pending_label.text()
    assert "真实状态：paused" in module.state.text()
    assert module.send_button.isEnabled() is True  # 线程完成后才允许下一次提交
    assert received[0][1]["config"] == {"require_exec_approval": True}


def test_backend_exception_and_model_blocked_are_visible(qt_app, ctx):
    module = _module(ctx)

    def broken_backend(*_args, **_kwargs):
        raise RuntimeError("模型连接失败（测试错误）")

    module.agent_caller = broken_backend
    module.question.setPlainText("触发后台错误")
    module.send_turn()
    _drain(ctx, qt_app)
    assert not module._jobs
    assert module.send_button.isEnabled()
    assert "模型连接失败（测试错误）" in module.state.text()
    assert "调用失败" in module.history.toPlainText()
    assert not module.banner.isHidden()

    module.agent_caller = lambda *_args, **_kwargs: {
        "status": "blocked",
        "summary": "模型不可用",
        "error": "LLM_UNAVAILABLE（无输出）",
        "pending": {},
    }
    module.question.setPlainText("触发模型不可用")
    module.send_turn()
    _drain(ctx, qt_app)
    assert "LLM_UNAVAILABLE" in module.history.toPlainText()
    assert "真实状态：blocked" in module.state.text()
    assert not module.banner.isHidden()
    assert not module._jobs
    assert module.send_button.isEnabled()


def test_resume_calls_existing_harness_not_a_second_run(qt_app, ctx, tmp_path, monkeypatch):
    module = _module(ctx)
    seen = {}

    def fake_resume(session_id, **kwargs):
        seen.update(kwargs)
        return {"status": "done", "session_id": session_id, "pending": {}, "summary": "已恢复"}

    monkeypatch.setattr(agent_mode_service, "resume_turn", fake_resume)
    module.session_id = "real-sid"
    module.workspace.setText(str(tmp_path))
    module._last_result = {"status": "paused", "pending": {"kind": "plan", "plan": "候选计划"}}
    module.resume_pending(True)
    _drain(ctx, qt_app)
    assert seen["approve"] is True
    assert seen["answer"] == ""
    assert seen["workspace"] == str(tmp_path)
    assert module._last_result["status"] == "done"


def test_open_validation_reuses_existing_pipeline_window(qt_app, ctx):
    called = []
    manager = SimpleNamespace(open=lambda module_id: called.append(module_id) or True)
    ctx.window = SimpleNamespace(manager=manager)
    module = _module(ctx)
    module.open_verification()
    assert called == ["flow.pipeline"]


def test_invalid_backend_payload_does_not_claim_success(qt_app, ctx):
    module = _module(ctx)
    task_id = ctx.tasks.submit("empty", lambda: None)
    module._jobs.add(task_id)
    _drain(ctx, qt_app)
    assert "调用失败" in module.state.text()
    assert module.approval.isHidden()
    assert module.session_id == ""


def test_real_manifest_window_receives_reply_without_manual_wiring(qt_app, settings, tmp_path):
    manifest, manifest_path = shipped_manifest()
    ctx = make_ctx(manifest, manifest_path, settings)
    window = make_window(qt_app, ctx)
    try:
        window.manager.open("interaction.chat")
        module = window.manager.module("interaction.chat")
        assert module._task_signals_bound is True
        module.agent_caller = lambda *_args, **_kwargs: {
            "status": "finished_no_proposal",
            "summary": "回复已经回到聊天面板",
            "session_id": "real-window-session",
            "pending": {},
        }
        module.question.setPlainText("测试真实消息返回")
        module.send_turn()
        _drain(ctx, qt_app)
        assert not module._jobs
        assert "回复已经回到聊天面板" in module.history.toPlainText()
        assert module.history.toPlainText().count("finished_no_proposal") == 1
        assert module.send_button.isEnabled()
        assert module.session_id == "real-window-session"
    finally:
        window.manager.mark_all_clean()
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_wait_notice_does_not_stop_agent(qt_app, ctx):
    module = _module(ctx)
    release = threading.Event()

    def controlled_agent(*_args, **_kwargs):
        assert release.wait(1.0)
        return {"status": "finished_no_proposal", "summary": "确实返回了"}

    module.agent_caller = controlled_agent
    module.question.setPlainText("等待较慢的调用")
    module.send_turn()
    module.wait_started_at -= 20
    module._show_wait_state()
    assert "已等待" in module.state.text()
    assert module._wait_warning_was_sent
    assert not module.banner.isHidden()
    assert not module.send_button.isEnabled()
    release.set()
    _drain(ctx, qt_app)
    assert "确实返回了" in module.history.toPlainText()
    assert module.send_button.isEnabled()
    assert module._wait_warning_was_sent is False
