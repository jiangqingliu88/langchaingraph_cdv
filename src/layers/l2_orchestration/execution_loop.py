"""
Pipeline 执行服务 —— CLI 和 Web API 共享的验证流水线引擎

单例模式，管理 Agent 生命周期 + 流水线执行 + 运行状态追踪。
"""
from __future__ import annotations
import time, json, uuid, asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import structlog

from src.layers.l1_infrastructure.output_config import make_output_root
from src.layers.l2_orchestration.regression_tools import sim_modes as _sim_modes

from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
from config.settings import Settings


from .execution_helpers import (
    _new_executor,
    _collect_llm_audit,
    _field,
    _round_of,
    _coverage_of,
    _result_of,
    _mirror_event,
    _translate_debug,
    _wire_approval_events,
    _translate_custom,
    _resolve_run_dir,
    _safe_checkpointer,
    _state_of,
    _interrupt_payload,
    _EXECUTOR_PATHS,
    logger,
)


class ClosedLoopSteps:
    async def run_closed_loop(self, spec_text: str, output_root: str = "output",
                              target: Optional[float] = None, max_rounds: int = 5,
                              design_style: str = "baseline",
                              bypass_design_model: bool = False,
                              sim_modes=None, manual_gate: bool = True, rtl_dir: str = "",
                              approval_gate=None) -> dict:
        """七 Agent 闭环：design → model → verify → ops → coverage → [decision] → audit。

        控制流已由图承载（src/layers/l2_orchestration/graph.py 的 StateGraph），
        本方法只做四件事：解析入口参数 → 建运行期上下文 → 跑图 → 返回结果。

        为什么能把 626 行命令式函数换掉而不改行为：
          原函数的「共享状态」绝大部分其实是控制流（阶段顺序 + 动作分流），
          真实数据流是 _run() 的返回值；逐节点的映射见 graph.py 顶部注释。
        签名与返回结构保持不变，CLI / REPL / run_multi_module 无需改动。

        target: 覆盖率目标（None=从统一配置 Settings.verification.coverage_target 读）。
        design_style: 设计风格（baseline/pipeline/low_power）。
        bypass_design_model: True = 验证专注模式，跳过 design/model。
        approval_gate: 审批门控（None=自动；传入则高风险动作前审批）。
        """
        # 解析输出目录一次（幂等），避免每个 Agent 各自追加时间戳 → 目录不一致
        output_root = make_output_root(output_root)
        # 统一覆盖率目标来源（消除散落硬编码 95）
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()

        if not self._initialized:
            await self.initialize_agents()

        from src.layers.l2_orchestration.graph import (
            Runtime, build_closed_loop_graph, recursion_limit)
        from src.layers.l2_orchestration.state import PipelineState

        rt = Runtime(self, spec_text, approval_gate=approval_gate)
        graph = build_closed_loop_graph()

        # ── 外部 RTL（`--rtl <dir>`）：**两条入口都要做** ──
        # `run_closed_loop`（CLI 走这条）与 `_stream_run`（GUI/服务走那条）是两份
        # 独立实现。第一版只补了 `_stream_run` —— 于是 CLI 上 `--rtl` 被整个忽略，
        # design agent 照样生成 RTL（实测：rtl/ 里是设计产的 2 个文件、不是我给的
        # 6 个，且日志里没有「外部 RTL 已纳入」）。
        _bypass_design = False
        if rtl_dir:
            _src = Path(rtl_dir)
            if not _src.is_dir():
                logger.error(f"--rtl 指的不是目录：{rtl_dir}（按无外部 RTL 处理）")
            else:
                _dst = Path(output_root) / "rtl"
                _dst.mkdir(parents=True, exist_ok=True)
                _n = 0
                for _f in sorted(_src.rglob("*")):
                    if _f.is_file() and _f.suffix.lower() in (".sv", ".v", ".svh", ".vh"):
                        (_dst / _f.name).write_bytes(_f.read_bytes())
                        _n += 1
                logger.info(f"外部 RTL 已纳入：{_n} 个文件 ← {rtl_dir}")
                _bypass_design = True   # 只跳 design；model 照跑（它是比对的那一半）

        initial = PipelineState(
            run_id=Path(output_root).name,
            output_root=str(output_root),
            target=float(target),
            max_rounds=int(max_rounds),
            design_style=design_style,
            bypass_design_model=bool(bypass_design_model),
            bypass_design=bool(_bypass_design),
            sim_modes=list(sim_modes) if sim_modes else [
                _sim_modes.DEFAULT_MODE],
            manual_gate=bool(manual_gate),
        )
        # Architecture 2.0：这次 run 的身份 + 事实日志/产物索引/Job 运行时。
        # 失败只 warning（见 init_run_core）；真缺了会在 quality gate 的 evidence 维度看见。
        from src.layers.l2_orchestration.runtime import init_run_core
        init_run_core(rt, initial.output_root, initial.run_id)
        if rt.event_store is not None:
            rt.event_store.append(
                "run.started", status="running", source="execution",
                payload={"run_id": initial.run_id, "target": initial.target,
                         "max_rounds": initial.max_rounds,
                         "output_root": initial.output_root},
                dedup_key=f"run.started:{initial.run_id}")

        config = {
            "configurable": {"rt": rt},
            # LangGraph 数的是 superstep 而非轮次，一轮约 6-10 步
            "recursion_limit": recursion_limit(int(max_rounds)),
        }
        self._register_run(initial.run_id, output_root, spec_text)
        try:
            final = await graph.ainvoke(initial, config)
            # LangGraph 对 pydantic 状态返回模型实例；defensive 地兼容 dict
            result = (final.get("result") if isinstance(final, dict)
                      else getattr(final, "result", None))
            if rt.event_store is not None:
                rt.event_store.append(
                    "run.finished", status="completed", source="execution",
                    payload={"run_id": initial.run_id,
                             "converged": (result or {}).get("converged")},
                    dedup_key=f"run.finished:{initial.run_id}")
            self._close_run(initial.run_id, result or {})
            return result or {}
        except Exception as exc:              # noqa: BLE001
            if rt.event_store is not None:
                rt.event_store.append(
                    "run.failed", status="failed", source="execution",
                    payload={"run_id": initial.run_id,
                             "error": f"{type(exc).__name__}: {exc}"[:500]},
                    dedup_key=f"run.failed:{initial.run_id}")
            self._close_run(initial.run_id, {}, error=exc)
            raise

    async def run_closed_loop_streaming(
        self, spec_text: str, output_root: str = "output",
        target: Optional[float] = None, max_rounds: int = 5,
        design_style: str = "baseline", bypass_design_model: bool = False,
        sim_modes=None, manual_gate: bool = True, rtl_dir: str = "", approval_gate=None, on_event=None, cancel_event=None,
        run_id: str = "", checkpointing: bool = True,
        resume: Optional[str] = None,
    ) -> dict:
        """`run_closed_loop` 的可观测版本：过程写进 `docs/run_events.jsonl`。

        与 `run_closed_loop` 的差别只有一处：它用 `graph.astream(...)` 而不是
        `ainvoke`，把每个节点的开始/结束翻译成日志记录。**图与节点一行未改**
        —— 阶段边界是 LangGraph 白送的（`stream_mode="debug"` 的 task /
        task_result），不是往 23 个节点里插埋点。

        返回结构与 `run_closed_loop` 完全一致，所以调用方可以按需替换。

        on_event: 可选回调，进程内的快路径（界面直接收信号）；不传就只落盘。
        cancel_event: 可选 `threading.Event`；置位后在**下一个节点边界**退出。
            图没有检查点，所以只能停在边界上 —— 这也正是为什么取消是协作式的。

        checkpointing: 落检查点（`docs/checkpoints.sqlite`，thread_id = run_id）。
            打开之后高风险动作的审批从"阻塞等答案"变成"停下来等人"：
            `astream` 结束、运行**没有结束**，可以在另一个进程里用 `resume` 接着跑。
            缺 `aiosqlite` 时**降级为不落检查点**并告警，不阻断运行。
        resume: 重入时给出的**审批答案**（approve / reject / skip）；None = 首次跑。
            "从哪次运行继续"由 `run_id` 表达，不由这个参数表达 —— 两者混在一个
            形参里会让 `Command(resume=<run_id>)` 把 run_id 当答案喂回去。
            重入时 `output_root` 等参数以检查点里的为准。
        """
        from src.layers.l2_orchestration.run_journal import RunJournal
        from src.layers.l2_orchestration.state import PipelineState

        run_dir = _resolve_run_dir(output_root, run_id) if resume else output_root
        ctx = _safe_checkpointer(run_dir) if checkpointing else None
        if ctx is None:
            return await self._stream_run(
                spec_text=spec_text, output_root=output_root, target=target,
                max_rounds=max_rounds, design_style=design_style,
                bypass_design_model=bypass_design_model, sim_modes=sim_modes,
                manual_gate=manual_gate, rtl_dir=rtl_dir, approval_gate=approval_gate, on_event=on_event,
                cancel_event=cancel_event, run_id=run_id, saver=None,
                resume=resume)
        async with ctx as saver:
            return await self._stream_run(
                spec_text=spec_text, output_root=output_root, target=target,
                max_rounds=max_rounds, design_style=design_style,
                bypass_design_model=bypass_design_model, sim_modes=sim_modes,
                manual_gate=manual_gate, rtl_dir=rtl_dir, approval_gate=approval_gate, on_event=on_event,
                cancel_event=cancel_event, run_id=run_id, saver=saver,
                resume=resume)

    async def _stream_run(self, *, spec_text, output_root, target, max_rounds,
                          design_style, bypass_design_model, approval_gate,
                          on_event, cancel_event, run_id, saver, resume,
                          sim_modes=None, manual_gate: bool = True, rtl_dir: str = ""):
        """`run_closed_loop_streaming` 的身体 —— 拆出来只为把检查点的开合
        收进 `with`，免得流循环被 try/finally 包住看不出重点。"""
        output_root = make_output_root(output_root)
        if target is None:
            from src.layers.l2_orchestration.planning import get_coverage_target
            target = get_coverage_target()

        if not self._initialized:
            await self.initialize_agents()

        from langgraph.types import Command

        from src.layers.l2_orchestration.graph import (
            Runtime, build_closed_loop_graph, hydrate_runtime, recursion_limit)
        from src.layers.l2_orchestration.run_journal import RunJournal
        from src.layers.l2_orchestration.state import PipelineState

        resumed = resume is not None
        rt = Runtime(self, spec_text, approval_gate=approval_gate,
                     interrupt_mode=saver is not None)
        graph = build_closed_loop_graph(checkpointer=saver)

        config: Dict[str, Any] = {"configurable": {"rt": rt}}
        payload: Any = None
        if resumed:
            # 重入：状态从检查点来，LangGraph 会忽略本次传进去的输入
            config["configurable"]["thread_id"] = run_id
            snapshot = await graph.aget_state(config)
            initial = _state_of(snapshot)
            if initial is None:
                raise ValueError(f"检查点里没有 {run_id} 的状态，无法重入")
            # Runtime 里的运行期对象**必须重建**：新进程里 n_init 不会再跑，
            # 而它建的东西（engine / planner / infra / 两个注册表 / 审计链）
            # 后面每个节点都要用 —— 少了不是"退化"，是 AttributeError。
            hydrate_runtime(rt, initial)
            output_root = initial.output_root
            max_rounds = initial.max_rounds
            payload = Command(resume=resume)
        else:
            # ── 外部 RTL（`--rtl <dir>`）：用现成的，**跳过 design/model** ──
            # 验开源 IP 就走这条：把「这份 RTL 对不对」与「design agent 会不会
            # 生成 RTL」两个变量隔开。拷贝而不是就地引用 —— run 目录要能**自洽**
            # 打包（审计/复现时拿着 run 目录就能重跑，不依赖外部路径还在不在）。
            _bypass_design = False   # 未给 --rtl 时必须先有值（否则 UnboundLocalError）
            if rtl_dir:
                src = Path(rtl_dir)
                if not src.is_dir():
                    logger.error(f"--rtl 指的不是目录：{rtl_dir}（按无外部 RTL 处理）")
                else:
                    dst = Path(output_root) / "rtl"
                    dst.mkdir(parents=True, exist_ok=True)
                    _copied = 0
                    for f in sorted(src.rglob("*")):
                        if f.is_file() and f.suffix.lower() in (".sv", ".v", ".svh", ".vh"):
                            # ⚠️ **别把这个局部变量叫 `target`** —— 它是"拷到哪"，
                            # 而同名参数 `target` 是**覆盖率目标**。原来这里写成
                            # `target = dst / f.name`，把它**遮蔽**掉，于是十几行后的
                            # `PipelineState(target=float(target))` 拿到一个 Path，
                            # 当场 `TypeError`。`--rtl` 这条路上 100% 复现。
                            # （另一条路 `run_closed_loop` 写的是就地表达式，没这个坑 ——
                            # 两条路各写一遍，一边踩了另一边没踩。）
                            _dst_file = dst / f.name
                            _dst_file.write_bytes(f.read_bytes())
                            _copied += 1
                    logger.info(f"外部 RTL 已纳入：{_copied} 个文件 ← {rtl_dir}")
                    # **只跳 design，不跳 model**：外部 RTL 只省掉「生成 RTL」
                    # 那一半；参考模型（util_components 装配单）照样要生成 ——
                    # 那是比对的 expected 侧，跳了就等于什么都不验。
                    _bypass_design = True

            initial = PipelineState(
                run_id=run_id or Path(output_root).name,
                output_root=str(output_root),
                target=float(target),
                max_rounds=int(max_rounds),
                design_style=design_style,
                bypass_design_model=bool(bypass_design_model),
                bypass_design=bool(_bypass_design),
                sim_modes=list(sim_modes) if sim_modes else [
                _sim_modes.DEFAULT_MODE],
                manual_gate=bool(manual_gate),
            )
            if saver is not None:
                config["configurable"]["thread_id"] = initial.run_id
        config["recursion_limit"] = recursion_limit(int(max_rounds))

        # Architecture 2.0：身份/事实日志在 **resume 之后**建 —— 重入要用检查点
        # 里的 run_id 与 output_root，而不是本次命令行传进来的。
        from src.layers.l2_orchestration.runtime import init_run_core
        init_run_core(rt, initial.output_root, initial.run_id)

        journal = RunJournal(output_root, run_id=initial.run_id)
        if not resumed:
            self._register_run(initial.run_id, output_root, spec_text)

        def _emit(event) -> None:
            # 一个事实只写一次：RunJournal 是过程日志，EventStore 是事实日志。
            # 镜像放在这里，节点里不再重复写 stage.*。
            _mirror_event(rt, event)
            if on_event is not None:
                try:
                    on_event(event)
                except Exception as exc:      # noqa: BLE001
                    # 观察者坏了不能把运行带崩 —— 它是观测手段，不是流程的一部分
                    logger.warning(f"on_event 回调失败（忽略）: {exc}")

        _wire_approval_events(approval_gate, journal, _emit)

        result: dict = {}
        final_state: Any = None
        started_at: Dict[str, float] = {}
        last_cov: Dict[str, Any] = {}
        try:
            _emit(journal.run_resumed(resume) if resumed else journal.run_started(
                spec=Path(str(spec_text)).name[:80] or "<inline>",
                target=float(target), max_rounds=int(max_rounds),
                design_style=design_style,
                bypass_design_model=bool(bypass_design_model),
                output_root=str(output_root)))

            cancelled = False
            # 重入时传的是 `Command(resume=...)` 而不是初始状态 —— 状态已经在
            # 检查点里了，LangGraph 会忽略输入、从停下那个节点往下走。
            async for mode, chunk in graph.astream(
                    payload if resumed else initial, config,
                    stream_mode=["debug", "custom", "values"]):
                if cancel_event is not None and cancel_event.is_set():
                    _emit(journal.run_cancelled())
                    cancelled = True
                    break

                if mode == "debug":
                    for event in _translate_debug(chunk, started_at, journal):
                        _emit(event)
                elif mode == "custom":
                    for event in _translate_custom(chunk, journal):
                        _emit(event)
                else:                          # values —— 全量状态
                    final_state = chunk
                    rn = _round_of(chunk)
                    if rn is not None:
                        journal.round_num = rn
                    # values 每个节点都推一次；只在覆盖率真的变了时才记一行，
                    # 否则日志会被 80 条重复的 coverage.updated 淹掉
                    cov = _coverage_of(chunk)
                    if cov and cov != last_cov:
                        last_cov = cov
                        _emit(journal.coverage_updated(**cov))

            # 停机原因有三种，别混：
            #   收到 interrupt  → **暂停**，运行没结束，等人来答（检查点上有它）
            #   被要求取消      → 停在节点边界，就此结束
            #   正常跑完        → 出结果
            interrupted = False
            if not cancelled and saver is not None:
                snapshot = await graph.aget_state(config)
                if getattr(snapshot, "next", ()):
                    interrupted = True
                    pending = _interrupt_payload(snapshot)
                    _emit(journal.run_interrupted(
                        str(pending.get("stage", "approval")), pending))
                    result = {"interrupted": True, "pending": pending,
                              "run_id": initial.run_id}
            if not cancelled and not interrupted:
                result = _result_of(final_state)
                _emit(journal.run_finished(result))
            self._close_run(initial.run_id, result, cancelled=cancelled,
                            interrupted=interrupted)
            return result
        except Exception as exc:                # noqa: BLE001
            _emit(journal.run_failed(exc))
            self._close_run(initial.run_id, {}, error=exc)
            raise
        finally:
            journal.close()

    async def run_multi_module(self, module_specs: List[dict], output_root: str = "output",
                               target: Optional[float] = None, max_rounds: int = 5,
                               design_style: str = "baseline", max_concurrency: int = 4,
                               approval_gate=None) -> List[dict]:
        """多模块软件流水：并发跑多个闭环，EDA 等待期间互相推进（不阻塞）。

        与"多 DUT"的区别：这里的"多模块"是多个验证任务/规格的流水并行——
        模块 A 在 EDA 编译仿真（to_thread 线程里）时，模块 B 的 LLM 生成
        （design/model/verify）在事件循环里继续推进，不空转、不完全阻塞。

        module_specs: [{"name", "spec_file"|"spec_text", "target"?, "max_rounds"?, "design_style"?}, ...]
        每个模块独立 output_root/<name> + 独立证据链（FileAuditTrail 实例隔离，见 run_closed_loop）。

        返回与输入同序的结果列表（单个模块异常以 Exception 形式留在结果里）。
        """
        from src.layers.l2_orchestration.pipeline_scheduler import PipelineScheduler
        from src.layers.l1_infrastructure.output_config import make_output_root

        # 先确保 agent 初始化（避免多任务并发时重复初始化竞态）
        if not self._initialized:
            await self.initialize_agents()

        base_root = make_output_root(output_root)
        sched = PipelineScheduler(max_concurrency=max_concurrency)

        def _make_task(m: dict, idx: int):
            name = (m.get("name") or f"module_{idx + 1}").replace("/", "_").replace("\\", "_")
            spec = m.get("spec_text", "")
            if not spec and m.get("spec_file"):
                try:
                    spec = Path(m["spec_file"]).read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    spec = ""
                    logger.warning(f"模块 {name} spec 读取失败: {e}")
            # 每个模块独立带时间戳子目录（make_output_root 幂等，互不冲突）
            sub_root = make_output_root(str(Path(base_root) / name))

            async def _run():
                return await self.run_closed_loop(
                    spec_text=spec, output_root=sub_root,
                    target=m.get("target", target),
                    max_rounds=m.get("max_rounds", max_rounds),
                    design_style=m.get("design_style", design_style),
                    approval_gate=approval_gate,
                )
            return _run

        tasks = [_make_task(m, i) for i, m in enumerate(module_specs)]
        return await sched.waterfall(tasks)

    async def run_single_agent(
        self, role: str, input_text: str
    ) -> dict:
        """执行单个 Agent，返回 {success, output, error}"""
        if not self._initialized:
            await self.initialize_agents()

        agent = self.registry.get_agent_instance(role)
        if not agent:
            return {"success": False, "error": f"Agent not found: {role}"}

        task = {"ctx": {}, "input": input_text}
        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "output": r.data.get("output", "") if r.data else "",
            "error": r.error,
        }

    async def generate_testcases(
        self, spec_text: str, output_dir: str = "output/testcases"
    ) -> dict:
        """运行 test_engineer Agent 生成测试用例"""
        if not self._initialized:
            await self.initialize_agents()

        ctx = {
            "spec": {"test_points": []},
            "env": {"env_name": "dut_env"},
        }

        agent = self.registry.get_agent_instance("test")
        if not agent:
            return {"success": False, "error": "test_engineer not found"}

        task = {
            "ctx": ctx,
            "input": json.dumps({
                "test_points": [],
                "env": ctx["env"],
            }),
            "output_dir": output_dir,
        }

        r = await agent.execute_task(task)
        return {
            "success": r.success,
            "tests": r.data.get("tests", {}),
            "output": r.data.get("output", ""),
            "error": r.error,
        }

