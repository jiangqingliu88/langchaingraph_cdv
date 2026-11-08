"""端到端：**声明 → 停下来 → payload 带产物 → 续跑**。

用真的 `n_approval` + 真的检查点（不假造 interrupt payload，像 `test_checkpoint.py`
那样自己写一份）。这一条链路就是这一刀的全部内容：

    manual_nodes.yaml  →  Runtime.manual_nodes  →  n_approval 读它决定要不要问
                       →  _interrupt_approval 的 payload 带 summary + artifacts
                       →  journal 的 run.interrupted（**界面读的就是这份**）
                       →  resume("approve"/"reject") 接着跑

为什么不用真冒烟来验：真跑一次时决策引擎挑哪个动作不由我们控制（实测那几次
都挑了 `GENERATE_DIRECTED_TEST`，而它不需要审批），于是**永远碰不到闸门**。
一条验不到东西的"端到端"不如一条确定性的。
"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration import graph as graph_mod
from src.layers.l2_orchestration import runtime as runtime_mod
from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.layers.l2_orchestration.run_journal import read_journal
from src.layers.l2_orchestration.run_repository import RunRepository
from src.layers.l2_orchestration.run_service import RunRequest, RunService
from src.layers.l2_orchestration.state import PipelineState

ACTION = "GENERATE_DIRECTED_TEST"        # 刻意挑一个**不在兜底名单**里的动作
PROMPT = "决策引擎打算生成定向测试。请看产物再放行。"

#: 旧格式的 bench（`env_name` / `dut:` / 空 `agents:`）—— 让产物清单里有一份
#: schema 不符的，正好也是当初卡住那次运行的那几处
BROKEN_BENCH = "bench:\n  name: x\n  env_name: y\n  agents:\n"

DECLARATION = [{"id": "gate_it", "kind": "approval", "after": "decide",
                "action": ACTION, "prompt": PROMPT,
                "default": "reject", "required": True}]


def _graph_with_real_approval(checkpointer=None, store=None, **kw):
    """design → **真 n_approval** → finalize。

    `n_design` 顺手把产物落到这次运行的目录里 —— `_approval_artifacts` 是从
    `state.output_root` 读的，不造出来它就只有空清单。
    """
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        from pathlib import Path

        root = Path(state.output_root)
        (root / "inputs" / "yaml" / "uvm").mkdir(parents=True, exist_ok=True)
        (root / "spec.json").write_text('{"design_name": "dut"}', encoding="utf-8")
        (root / "inputs" / "yaml" / "uvm" / "bench.yaml").write_text(
            BROKEN_BENCH, encoding="utf-8")
        return {"spec": {"name": "demo"},
                "pending_action": {"action_type": ACTION, "reason": "引擎的理由"}}

    def n_finalize(state):
        return {"result": {"status": "PASS", "approval_outcome": state.approval_outcome}}

    g.add_node("design", n_design)
    g.add_node("approval", graph_mod.n_approval)
    g.add_node("finalize", n_finalize)
    g.add_edge(START, "design")
    g.add_edge("design", "approval")
    g.add_edge("approval", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer, store=store)


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mod, "build_closed_loop_graph",
                        _graph_with_real_approval)
    # 声明是 `Runtime.__init__` 里读的（读的是仓库那份配置）—— 这里换成
    # 测试自己的那一条，免得测试依赖 `config/ide/manual_nodes.yaml` 的内容。
    #
    # **patch 的是 `runtime_mod` 而不是 `graph_mod`**：调用点在
    # `Runtime.__init__`（runtime.py:83），名字在 runtime 模块里解析 ——
    # 从 graph 上 patch 打不着（graph 只是把它 re-export 出来）。
    monkeypatch.setattr(runtime_mod, "_load_manual_nodes", lambda: DECLARATION)
    from src.layers.l2_orchestration.governance import approval as approval_mod
    monkeypatch.setattr(approval_mod, "create_approval_gate", _auto_gate)
    PipelineExecutionService.get_instance()._initialized = True
    service = RunService(output_base=str(tmp_path))
    yield service
    service.shutdown(timeout=5)


def _auto_gate(mode: str = "threshold", channel=None, **kw):
    from src.layers.l2_orchestration.governance.approval import (
        ApprovalDecision, ApprovalGate, ApprovalMode, AutoChannel,
    )
    return ApprovalGate(mode=ApprovalMode.THRESHOLD,
                        channel=AutoChannel(ApprovalDecision.APPROVE))


def _req(tmp_path, **kw):
    kw.setdefault("output_root", str(tmp_path / "run"))
    kw.setdefault("target", 95.0)
    kw.setdefault("max_rounds", 1)
    kw.setdefault("approval", "threshold")
    return RunRequest(spec_text="# 假规格", **kw)


class TestDeclarationGate:
    def test_the_declared_action_pauses_the_run(self, svc, tmp_path):
        """**声明里写了就停。** 这个动作不在兜底名单里 —— 停了就说明读的是声明。"""
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        assert result.get("interrupted") is True
        assert result["pending"]["stage"] == ACTION

    def test_the_payload_carries_the_declared_prompt(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        assert result["pending"]["summary"] == PROMPT

    def test_the_payload_carries_the_artifacts(self, svc, tmp_path):
        """人批准的时候得看得见**自己在批什么文件**。"""
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        artifacts = result["pending"]["artifacts"]
        assert [a["path"] for a in artifacts] == [
            "spec.json", "inputs/yaml/uvm/bench.yaml", "inputs/yaml/regression.yaml",
            "inputs/vplan/data/execution_meta.csv", "coverage/coverage_points.json",
            "inputs/yaml/uvm/env_cov_bins.yaml"]
        bench = [a for a in artifacts if a["path"].endswith("bench.yaml")][0]
        assert bench["errors"] > 0

    def test_the_journal_carries_the_same_payload(self, svc, tmp_path):
        """**界面读的是 journal 这一份**（检查点模式不走 `pending_approval`）。

        所以产物必须出现在 `run.interrupted` 的事件里 —— 只放在别处界面看不到。
        """
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        run_dir = RunRepository(str(tmp_path)).run_dir(run_id)
        events = [e for e in read_journal(run_dir) if e.kind == "run.interrupted"]
        assert events, [e.kind for e in read_journal(run_dir)]
        payload = events[-1].payload
        assert payload["summary"] == PROMPT
        assert any(a["path"].endswith("bench.yaml") and a["errors"] > 0
                   for a in payload["artifacts"])


class TestResume:
    def test_approving_continues_to_the_end(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)

        svc.resume(run_id, "approve")
        result = svc.wait(run_id, timeout=30)
        assert result["approval_outcome"] == "proceed"

    def test_rejecting_is_recorded_and_does_not_proceed(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)

        svc.resume(run_id, "reject")
        result = svc.wait(run_id, timeout=30)
        assert result["approval_outcome"] == "reject"


class TestNoGateWithoutADeclaration:
    """声明里没有的动作**不许停下来** —— 否则每次迭代都变成等人。"""

    def test_an_undeclared_action_runs_straight_through(self, svc, tmp_path,
                                                        monkeypatch):
        monkeypatch.setattr(runtime_mod, "_load_manual_nodes",
                            lambda: [{"id": "other", "after": "decide",
                                      "action": "EXPAND_SEEDS"}])
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        assert result.get("interrupted") is not True
        assert result["approval_outcome"] == "proceed"
