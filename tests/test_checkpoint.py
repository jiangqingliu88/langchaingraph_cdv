"""检查点与重入 —— 一次运行可以**停下**，然后在别处接着跑。

这是 P3 的核心承诺，也是它和"阻塞等答案"最本质的区别：

    通道模式   审批把运行**挂住**，占着线程等人点。进程没了，这次运行就没了。
    检查点模式 审批让运行**结束**这次 astream，状态落在
               `docs/checkpoints.sqlite`。人什么时候答都行 —— 换一个进程、换一天，
               拿同一个 run_id 接着跑。

所以本文件最要紧的一条是 `test_resume_works_in_a_fresh_service`：
**换一个服务实例**（等价于换了进程）仍然能续上。只测同进程内重入的话，
验的其实还是内存里的东西，等于没验。
"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration import graph as graph_mod
from src.layers.l2_orchestration.execution import PipelineExecutionService
from src.layers.l2_orchestration.execution_helpers import CHECKPOINT_FILE, _state_of
from src.layers.l2_orchestration.run_service import RunRequest, RunService
from src.layers.l2_orchestration.run_journal import (
    KIND_RUN_FINISHED, KIND_RUN_INTERRUPTED, KIND_RUN_RESUMED, RunEvent,
    read_journal,
)
from src.layers.l2_orchestration.state import PipelineState


# ═══════════════════════════════════════════════════════════════
# 假图：一个会 interrupt 的审批节点
# ═══════════════════════════════════════════════════════════════

def _graph_with_gate(checkpointer=None, store=None, **kw):
    """design → approval(interrupt) → finalize。

    approval 节点的行为随运行时切换，正好覆盖两条路径：
      · `rt.interrupt_mode` 为真（有检查点）→ `interrupt()`，停下来
      · 否则 → 走审批通道（这里用一个固定的 CallbackChannel 代替人去点）
    """
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(PipelineState)

    def n_design(state):
        return {"spec": {"name": "demo"},
                "phases": [{"name": "design", "status": "passed"}]}

    def n_approval(state, config):
        from langgraph.types import interrupt
        rt = config["configurable"]["rt"]
        action = {"action_type": "REFACTOR_RTL", "reason": "时序改了"}
        if rt.interrupt_mode:
            answer = interrupt({"kind": "approval", "stage": "REFACTOR_RTL",
                                "risk_level": "high", "reason": "时序改了",
                                "token": "ap-1"})
            outcome = {"approve": "proceed", "reject": "reject",
                       "skip": "skip"}.get(str(answer), "skip")
        else:
            _d = rt.approval_gate.ask("REFACTOR_RTL", "时序改了", risk_level="high")
            outcome = {"approve": "proceed", "reject": "reject",
                       "skip": "skip"}.get(_d.decision.value, "skip")
        return {"approval_outcome": outcome,
                "phases": [{"name": "approval", "status": outcome}]}

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


@pytest.fixture
def svc(tmp_path, monkeypatch):
    monkeypatch.setattr(graph_mod, "build_closed_loop_graph", _graph_with_gate)
    # 审批门控在服务层内部构造 —— 这里把工厂换掉，让**通道模式**（无检查点那条
    # 回退路径）不至于卡在 input() 上。检查点模式下通道根本不会被问到，
    # 所以这个替换只影响降级路径，不影响 interrupt 路径的验收。
    from src.layers.l2_orchestration.governance import approval as approval_mod
    monkeypatch.setattr(approval_mod, "create_approval_gate", _auto_gate)
    PipelineExecutionService.get_instance()._initialized = True
    service = RunService(output_base=str(tmp_path))
    yield service
    service.shutdown(timeout=5)


def _auto_gate(mode: str = "threshold", channel=None, **kw):
    """一律"通过"的门控 —— 替掉会去读 stdin 的默认通道。"""
    from src.layers.l2_orchestration.governance.approval import (
        ApprovalDecision, ApprovalGate, ApprovalMode, AutoChannel,
    )
    return ApprovalGate(mode=ApprovalMode.THRESHOLD,
                        channel=AutoChannel(ApprovalDecision.APPROVE))


def _req(tmp_path, **kw):
    kw.setdefault("output_root", str(tmp_path / "run"))
    kw.setdefault("target", 95.0)
    kw.setdefault("max_rounds", 1)
    # 审批走"仅高危"= THRESHOLD，REFACTOR_RTL 是 high → 一定会问
    kw.setdefault("approval", "threshold")
    return RunRequest(spec_text="# 假规格", **kw)


# ═══════════════════════════════════════════════════════════════
# 中断
# ═══════════════════════════════════════════════════════════════

class TestInterrupt:
    def test_a_high_risk_action_pauses_the_run(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        assert result.get("interrupted") is True
        assert result["pending"]["stage"] == "REFACTOR_RTL"

    def test_the_journal_says_waiting_not_finished(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        kinds = [e.kind for e in read_journal(_run_dir(tmp_path, run_id))]
        assert KIND_RUN_INTERRUPTED in kinds
        assert KIND_RUN_FINISHED not in kinds

    def test_an_interrupt_is_not_terminal(self):
        """"暂停"与"完事"必须分得开 —— 界面靠这个决定显示审批条还是终态。"""
        event = RunEvent(seq=1, ts="t", kind=KIND_RUN_INTERRUPTED)
        assert event.is_terminal is False
        assert event.is_failure is False

    def test_the_checkpoint_file_lands_in_docs(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        assert (_run_dir(tmp_path, run_id) / "docs" / CHECKPOINT_FILE).is_file()

    def test_the_run_state_is_waiting(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        assert svc.summary(run_id)["state"] == "waiting"

    def test_the_pending_approval_is_readable(self, svc, tmp_path):
        """快照里挂着的那个 interrupt 要能取出来 —— 界面靠它显示"卡在哪"。"""
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        pending = svc.summary(run_id)["last"]["payload"]
        assert pending["stage"] == "REFACTOR_RTL"
        assert pending["token"] == "ap-1"


# ═══════════════════════════════════════════════════════════════
# 重入
# ═══════════════════════════════════════════════════════════════

def _run_dir(tmp_path, run_id):
    from src.layers.l2_orchestration.run_repository import RunRepository
    return RunRepository(str(tmp_path)).run_dir(run_id)


class TestResume:
    def test_approving_finishes_the_run(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)

        resumed = svc.resume(run_id, "approve")
        result = svc.wait(resumed, timeout=30)
        assert result.get("status") == "PASS"
        assert result.get("final_coverage") == 93.0

    def test_the_journal_records_both_halves(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        svc.wait(svc.resume(run_id, "approve"), timeout=30)

        kinds = [e.kind for e in read_journal(_run_dir(tmp_path, run_id))]
        assert kinds[0] == "run.started"
        assert KIND_RUN_INTERRUPTED in kinds
        assert KIND_RUN_RESUMED in kinds
        assert kinds[-1] == KIND_RUN_FINISHED

    def test_reject_still_lands_the_decision(self, svc, tmp_path):
        """重入路径的答案要**真的生效**，不是记一笔就算数。"""
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        svc.wait(svc.resume(run_id, "reject"), timeout=30)
        events = read_journal(_run_dir(tmp_path, run_id))
        resumed = [e for e in events if e.kind == KIND_RUN_RESUMED][0]
        assert resumed.payload["decision"] == "reject"
        # 答案要**进到图里**才算数：approval 节点跑完后，它写下的
        # `approval_outcome` 会出现在该阶段的状态增量里。
        outcome = [e.payload.get("delta", {}).get("approval_outcome")
                   for e in events if e.stage == "approval" and e.kind == "stage.finished"]
        assert "reject" in outcome

    def test_resume_works_in_a_fresh_service(self, svc, tmp_path, monkeypatch):
        """**换一个服务实例** = 换一个进程。这条不通，"跨进程重入"就是空话。

        检查点在磁盘上（`docs/checkpoints.sqlite`），状态从它读回，
        Runtime 里的运行期对象靠 `hydrate_runtime` 重建 —— 三样缺一不可。
        """
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        svc.shutdown(timeout=5)

        from src.layers.l2_orchestration import run_service as rs
        other = RunService(output_base=str(tmp_path))
        monkeypatch.setattr(rs, "_service", other)
        try:
            other.wait(other.resume(run_id, "approve"), timeout=30)
            kinds = [e.kind for e in read_journal(_run_dir(tmp_path, run_id))]
            assert kinds[-1] == KIND_RUN_FINISHED
        finally:
            other.shutdown(timeout=5)

    def test_resuming_an_unknown_run_is_a_clear_error(self, svc, tmp_path):
        run_id = svc.resume("no-such-run", "approve")
        with pytest.raises(Exception) as info:
            svc.wait(run_id, timeout=20)
        assert "检查点" in str(info.value)

    def test_runtime_objects_survive_the_resume(self, svc, tmp_path):
        """重入时 `n_init` 不会重跑 —— 它建的那些东西必须靠 hydrate 补上。

        少了它们不是"退化"，是 AttributeError：`finalize` 要用 file_audit 与
        tool_auditor，`governor` 要用 exclude_reg。所以这条跑到底就是证据。
        """
        run_id = svc.start(_req(tmp_path))
        svc.wait(run_id, timeout=30)
        result = svc.wait(svc.resume(run_id, "approve"), timeout=30)
        assert result.get("status") == "PASS"


# ═══════════════════════════════════════════════════════════════
# 降级与开关
# ═══════════════════════════════════════════════════════════════

class TestWithoutCheckpointing:
    def test_no_checkpoint_file_when_disabled(self, svc, tmp_path):
        run_id = svc.start(_req(tmp_path, checkpointing=False))
        svc.wait(run_id, timeout=30)
        assert not (_run_dir(tmp_path, run_id) / "docs" / CHECKPOINT_FILE).exists()

    def test_the_run_goes_all_the_way_through(self, svc, tmp_path):
        """没有检查点时审批退回通道模式，跑到底 —— 与改动前一致。"""
        run_id = svc.start(_req(tmp_path, checkpointing=False))
        result = svc.wait(run_id, timeout=30)
        assert result.get("status") == "PASS"
        assert "interrupted" not in result

    def test_a_missing_aiosqlite_degrades_instead_of_failing(self, svc, tmp_path,
                                                             monkeypatch):
        """可选能力不该让主流程起不来 —— 退回通道模式，验证照跑。"""
        import builtins
        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "aiosqlite":
                raise ImportError("模拟没装 aiosqlite")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        run_id = svc.start(_req(tmp_path))
        result = svc.wait(run_id, timeout=30)
        assert result.get("status") == "PASS"


# ═══════════════════════════════════════════════════════════════
# CLI 审批 —— 断链的那一半
# ═══════════════════════════════════════════════════════════════

class TestCliApprovalDrivesTheGraph:
    """`vagent approve` / `resume` 必须**真的**把挂起的图推下去。

    ## 断在哪（这组测试的由来）

    这两个命令原来只往 `<run>/approval.json` 写一条 JSON，而全仓库**没有任何
    读者**（`Read` 侧零命中）。人签了字：记录有了、运行还停在原地、也没人知道。
    "可治理"那一支柱因此是空的 —— 审批动作发生了，但它**不驱动任何东西**。

    所以这组不测"文件写没写"（那半边一直是对的），测**图有没有继续走**：
    签完之后 journal 必须出现 `run.finished`，否则就是回到了断链状态。
    """

    def _interrupted(self, svc, tmp_path, monkeypatch):
        """造一次**真的停在审批上**的运行，返回 (run_id, run_dir)。

        `output_root` 特意放在 `output` 前缀下：CLI 的 `_repo()` 是
        `RunRepository("output")`，它既认 `output/` 也认同级的 `output_*`
        （见 `run_dirs` 的注释）。放别处 CLI 找不到这次运行 —— 那是另一件事。
        """
        monkeypatch.chdir(tmp_path)
        rid = svc.start(_req(tmp_path, output_root=str(tmp_path / "output")))
        result = svc.wait(rid, timeout=30)
        assert result.get("interrupted") is True, "这轮没停在审批上，后面的验收不成立"
        return rid, _run_dir(tmp_path, rid)

    def test_approve_resumes_the_run_and_keeps_the_audit_record(self, svc, tmp_path,
                                                                monkeypatch):
        import json

        from click.testing import CliRunner

        from src.cli.commands import cli

        rid, run_dir = self._interrupted(svc, tmp_path, monkeypatch)
        res = CliRunner().invoke(cli, ["approve", "--run", rid, "--reason", "看过波形了"])
        assert res.exit_code == 0, res.output

        kinds = [e.kind for e in read_journal(run_dir)]
        assert KIND_RUN_FINISHED in kinds, (
            "签完之后运行没有继续 —— 又回到了「只写 approval.json、不驱动图」的断链")
        # 审计那一半不能因为接线而丢掉：理由仍在记录里
        rec = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
        assert rec["action"] == "approve"
        assert rec["reason"] == "看过波形了"

    def test_resume_subcommand_drives_it_too(self, svc, tmp_path, monkeypatch):
        """`resume --decision skip` 这条路 —— `approve`/`reject` 不覆盖的答案。"""
        from click.testing import CliRunner

        from src.cli.commands import cli

        rid, run_dir = self._interrupted(svc, tmp_path, monkeypatch)
        res = CliRunner().invoke(cli, ["resume", "--run", rid, "--decision", "skip"])
        assert res.exit_code == 0, res.output
        assert KIND_RUN_FINISHED in [e.kind for e in read_journal(run_dir)]

    def test_resume_works_outside_the_output_namespace(self, svc, tmp_path, monkeypatch):
        """`-o /别处/xx` 跑出来的运行也要能恢复 —— 用 `--output-base` 指过去。

        这条盯的是"基准目录写死 `output`"那个坑：写死的话，运行落在
        `elsewhere_*/` 下就永远恢复不了 —— 而且报错是"找不到 run"，
        让人以为是 run 不存在，而不是"我看错了地方"。
        """
        from click.testing import CliRunner

        from src.cli.commands import cli

        monkeypatch.chdir(tmp_path)
        rid = svc.start(_req(tmp_path, output_root=str(tmp_path / "elsewhere")))
        assert svc.wait(rid, timeout=30).get("interrupted") is True
        runs = sorted(tmp_path.glob("elsewhere_*"))
        assert runs, "run 目录没建出来"
        run_dir = runs[0]
        assert run_dir.name == rid

        res = CliRunner().invoke(cli, [
            "resume", "--run", run_dir.name, "--decision", "approve",
            "--output-base", str(tmp_path / "elsewhere")])
        assert res.exit_code == 0, res.output
        assert KIND_RUN_FINISHED in [e.kind for e in read_journal(run_dir)]

    def test_resume_reports_clearly_when_there_is_nothing_to_resume(self, tmp_path,
                                                                   monkeypatch):
        """没有检查点 = 没有挂起的审批：**说清楚**，不是堆一个 traceback。"""
        from click.testing import CliRunner

        from src.cli.commands import cli

        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "output" / "fake_run_1"
        run_dir.mkdir(parents=True)
        res = CliRunner().invoke(cli, ["resume", "--run", "fake_run_1"])
        assert res.exit_code == 0, res.output
        assert "没有检查点" in res.output

    def test_approve_without_a_checkpoint_still_records(self, tmp_path, monkeypatch):
        """没挂起的图时 `approve` 仍然记审计 —— **不报错**。

        审批记录是"人何时为何签了"的凭证，与"这次签核有没有推着图走"是两件事。
        把前者绑死在后者上，等于"没东西可推时连记录都不留"。
        """
        import json

        from click.testing import CliRunner

        from src.cli.commands import cli

        monkeypatch.chdir(tmp_path)
        run_dir = tmp_path / "output" / "fake_run_2"
        run_dir.mkdir(parents=True)
        res = CliRunner().invoke(cli, ["approve", "--run", "fake_run_2", "--reason", "留档"])
        assert res.exit_code == 0, res.output
        rec = json.loads((run_dir / "approval.json").read_text(encoding="utf-8"))
        assert rec["action"] == "approve" and rec["reason"] == "留档"
        assert not (run_dir / "docs").exists(), "没有检查点却去建 docs/ 了"


class TestStateRoundTrip:
    def test_state_of_filters_unknown_keys(self):
        """检查点里可能混着框架塞的键，`extra="forbid"` 会把它们当错误。"""
        class _Snap:
            values = {"run_id": "r1", "target": 90.0, "output_root": "out",
                      "framework_internal": "x"}

        state = _state_of(_Snap())
        assert state is not None and state.run_id == "r1"

    def test_state_of_returns_none_without_a_run_id(self):
        class _Snap:
            values = {"target": 90.0}

        assert _state_of(_Snap()) is None

    def test_state_of_returns_none_for_an_empty_snapshot(self):
        class _Snap:
            values = {}

        assert _state_of(_Snap()) is None


class TestTheRtlPathDoesNotShadowTheTarget:
    """`--rtl` 走 streaming 时，拷贝循环**不许**遮蔽参数 `target`。

    ## 这条是怎么来的（真实事故）

    把 `verify` 从 `run_closed_loop` 换到 `run_closed_loop_streaming`（为了落检查点）
    之后，`vagent verify --rtl specs/npu_sched` **当场崩**：

        execution.py:_stream_run
            for f in ...:  target = dst / f.name      ← 把参数 target 遮蔽了
            ...
            PipelineState(target=float(target))
        TypeError: float() argument must be ... not 'WindowsPath'

    而且**100% 复现** —— 不是偶发。另一条路 `run_closed_loop` 里那句写的是就地
    表达式（`(_dst / _f.name).write_bytes(...)`），没这个坑：**同一个"把外部 RTL
    拷进 run 目录"的动作，两条路各写了一遍，一边踩了另一边没踩。**

    一条端到端测试本该拦住它 —— 而当时没有：`--rtl` 这条全路径没有任何测试覆盖，
    测试套件全绿而命令是坏的。
    """

    def test_the_target_argument_survives_the_rtl_copy(self):
        """`_stream_run` 里不许对 `target` 赋值 —— 它不是局部变量，是**参数**。

        静态扫一眼源码就能拦（比"真跑一遍全流程"便宜得多）：那是个赋值语句，
        不是传参。真跑的话要拉 EDA、要几分钟，而这条断言瞬间就红。
        """
        import ast
        from pathlib import Path

        src = Path("src/layers/l2_orchestration/execution.py")
        tree = ast.parse(src.read_text(encoding="utf-8"))

        offender = None
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or node.name != "_stream_run":
                continue
            for sub in ast.walk(node):
                # `target = ...`（Name 存）—— 参数被当局部变量重新绑定了。
                #
                # **一处例外**：`target = get_coverage_target()` 是"没给就用配置
                # 默认值"的兜底赋值，那是正当的（不这么写就没法区分"没给"和"给了 0"）。
                # 除了它，任何对 `target` 的赋值都是遮蔽。
                if not (isinstance(sub, ast.Assign) and sub.targets
                        and any(isinstance(t, ast.Name) and t.id == "target"
                                for t in sub.targets)):
                    continue
                rhs = sub.value
                if (isinstance(rhs, ast.Call) and isinstance(rhs.func, ast.Name)
                        and rhs.func.id == "get_coverage_target"):
                    continue
                offender = sub.lineno
        assert offender is None, (
            f"`_stream_run` 第 {offender} 行给 `target` 赋值了 —— 它是**覆盖率目标**"
            f"参数，被当局部变量用会让 `PipelineState(target=float(target))`"
            f"拿到一个 Path 而当场 TypeError（`--rtl` 上 100% 复现，实测）。")

    def test_the_rtl_dir_is_actually_accepted(self, svc, tmp_path, monkeypatch):
        """真跑一次带 `rtl_dir` 的 streaming 路径 —— 端到端那条缺的覆盖。

        用 `test_checkpoint` 现有的假图（不碰 EDA），只验"这条路走得通"：
        修复前它在 `float(target)` 那行就崩，连图都进不去。
        """
        import asyncio

        # 造一个像样的外部 RTL 目录
        ext = tmp_path / "ext_rtl"
        ext.mkdir()
        (ext / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")

        out = tmp_path / "out_20260101_000000"
        from src.layers.l2_orchestration.execution import PipelineExecutionService

        PipelineExecutionService.get_instance()._initialized = True
        result = asyncio.run(
            PipelineExecutionService.get_instance().run_closed_loop_streaming(
                spec_text="# 假规格", output_root=str(out), target=95.0,
                max_rounds=1, rtl_dir=str(ext), checkpointing=False,
                # 假图里的审批节点会问 `rt.approval_gate` —— 直接调服务时
                # 得自己给一个，否则它拿到 None（与那组 `svc` 夹具同一套替身）
                approval_gate=_auto_gate()))
        assert isinstance(result, dict), "带 rtl_dir 的 streaming 路径没能跑完"
        # 外部 RTL 被拷进 run 目录（那正是出问题的那段循环的产物）。
        #
        # **别猜目录名**：`make_output_root` 的"已带时间戳"判据要求中间有用户段
        # （`_[a-z]+\d*_\d{8}_\d{6}$`），`out_20260101_000000` 这种**不匹配** ——
        # 它会再套一层 `_<用户>_<时间戳>`（实测）。所以在 tmp_path 下找那个 run 目录
        # （假图的 finalize 不返回 run_id，只能按"带 rtl/ 的目录"认）。
        runs = [p for p in tmp_path.iterdir() if p.is_dir() and (p / "rtl").is_dir()]
        assert runs, f"没找到 run 目录（{list(tmp_path.iterdir())}）"
        assert (runs[0] / "rtl" / "dut.sv").is_file(), \
            f"外部 RTL 没被拷进 run 目录（{runs[0]}）—— 拷贝那段没跑对"
