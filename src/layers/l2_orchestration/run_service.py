"""RunService —— 运行的门面：启动 / 取消 / 查询。

为什么要有这个文件
    流水线是 async 的（`graph.ainvoke` / `astream`，agents 全是 `await`），
    而调用它的两头都是同步的：CLI 用 `asyncio.run()` 一次性跑完，GUI 是 Qt 的
    事件循环。**Qt 与 asyncio 必须只在一个地方交界**，否则迟早有人在 GUI 线程里
    调 `asyncio.run()` —— 那会冻结界面，而且是在运行最忙的时候冻结。

    所以：本模块独占一个 asyncio 事件循环跑在专用线程上，对外只暴露**同步** API。

三条纪律
    1. **这里不出现 Qt**（`grep PySide6 src/layers/` 必须为空）。界面通过
       `workbench/bridge/catalog.py` 的 ToolBinding 到本服务，与访问别的工具同形。
    2. **一次一个 run**。`Runtime` 里握着 sqlite 连接与 agent 实例，不是线程安全的；
       `PipelineExecutionService` 又是单例。EDA 工具本身也是资源独占的，串行合理。
       多余的请求进队列，界面上把"启动"置灰并说明当前在跑什么。
    3. **不解释事件**。本服务只搬事件（落盘的交给 RunJournal），"哪些阶段算一组、
       什么算收敛"属于视图或阶段表（stages.py），不属于这里。

进度从哪来
    `run_closed_loop_streaming` 写 `docs/run_events.jsonl`。观察界面**读文件**
    （`RunRepository.journal` / `JournalTail`），所以「在终端里启动、在界面里看」
    天然成立，关掉界面再打开也还能接着看。`on_event` 回调是可选的低延迟快路径，
    不是唯一通道。
"""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# 请求（唯一实现见 `verify_request.py`；这里保留旧名字给调用方）
# ═══════════════════════════════════════════════════════════════

from src.layers.l2_orchestration.verify_request import (  # noqa: E402
    VerifyRequest as RunRequest, mount_vplan, unique_output_root,
)


def _resolve_run_dir(output_base: str, run_id: str) -> str:
    """run_id → 那次运行的目录（找不到就退回基准目录）。

    退回而不是抛：不存在的那次运行最终会以"检查点里没有它的状态"失败 ——
    那句话比"目录不存在"更能说明问题是什么。
    """
    from src.layers.l2_orchestration.run_repository import RunRepository
    found = RunRepository(output_base).run_dir(run_id)
    return str(found) if found else output_base



# ═══════════════════════════════════════════════════════════════
# 一次运行的句柄
# ═══════════════════════════════════════════════════════════════

class _RunHandle:
    """排队中 / 运行中的一次运行 —— 便于取消与等待。"""

    def __init__(self, request: RunRequest, root: Path):
        self.request = request
        self.root = root
        self.run_id = request.run_id or root.name
        self.cancel_event = threading.Event()
        self.done = threading.Event()
        self.result: Dict[str, Any] = {}
        self.error: Optional[BaseException] = None


# ═══════════════════════════════════════════════════════════════
# 服务
# ═══════════════════════════════════════════════════════════════

class RunService:
    """独占一个 asyncio 循环线程的运行服务（同步门面）。"""

    def __init__(self, output_base: str = "output"):
        self.output_base = output_base
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._queue: List[_RunHandle] = []          # 待跑（含当前）
        self._handles: Dict[str, _RunHandle] = {}   # run_id → handle
        self._current: Optional[_RunHandle] = None
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._worker: Optional[threading.Thread] = None
        self._on_event: Optional[Callable[[Any], None]] = None
        # 审批：有人在听才用 EventChannel（见 _channel_for）。没有听者时退回
        # `create_approval_gate` 的默认 ConsoleChannel —— 无头的 CLI 行为不变。
        self._approval_handler: Optional[Callable[[Any], None]] = None
        self._approval_channel = None

    # ── 生命周期 ──

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """惰性起 loop 线程 —— 只用查询接口的调用方（列运行、读日志）不必付这个成本。"""
        if self._loop is not None:
            return self._loop
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                thread = threading.Thread(target=self._loop_forever, args=(loop,),
                                          name="run-service-loop", daemon=True)
                thread.start()
                self._loop, self._thread = loop, thread
                self._worker = threading.Thread(target=self._work,
                                                name="run-service-worker",
                                                daemon=True)
                self._worker.start()
        return self._loop

    #: 循环被 SystemExit 打断后最多重开几次 —— 防止「每次都抛」变成死转
    _LOOP_RESTART_LIMIT = 5

    @classmethod
    def _loop_forever(cls, loop: asyncio.AbstractEventLoop) -> None:
        """loop 线程的入口 —— 它**必须扛住 SystemExit**。

        这一层是不得不做的兜底，起因是一次实测事故：`src/generation/uvm_tools/` 下的
        `gen_uvm` 是照着独立 CLI 写的，schema 校验不过就 `raise SystemExit`。
        它被进程内调用时跑在这个循环上，于是：

            `Task.__step` 捕获 SystemExit 后会 **原样重新抛出**（asyncio 刻意保留
            KeyboardInterrupt / SystemExit 的"终止"语义）—— 它**不经过 await 链**，
            所以 `_run` 里的 `try/except` 根本拦不到，异常直奔 `run_forever` 之外；
            `threading` 又把线程里的 SystemExit **静默吞掉**（不打印、不回调
            excepthook）。结果：循环线程无声无息地消失，`run_coroutine_threadsafe`
            的 future 永不完成，worker 卡死在 `fut.result()`，而 `self._loop` 还是
            非 None —— **此后每一次启动都照样卡死**。

        症状就是「点了启动没反应」，一条错误都看不到（见 `_execute` 与 `_run` 的
        注释）。一个工具写成了 CLI 形状，不该让整个运行服务报废，所以这里把
        SystemExit 吞掉并**重开循环**：出错的那个 Task 异常已经记在自己身上，
        重开后 await 它的那边会正常收到异常、这次运行如实记成失败。

        正常停机（`shutdown()` 调的 `loop.stop()`）会让 `run_forever` 正常返回，
        于是跳出循环 —— 这条路径不受影响。
        """
        for attempt in range(cls._LOOP_RESTART_LIMIT):
            try:
                loop.run_forever()
                logger.warning("run-service loop 已停止 —— 之后启动的运行都不会跑")
                return
            except SystemExit as exc:
                logger.error(
                    "有工具在运行中调了 sys.exit，运行服务的 loop 被它打断；"
                    "已重开循环（工具应当抛异常而不是退出进程）",
                    error=repr(exc), attempt=attempt + 1)
                continue
            except BaseException as exc:          # noqa: BLE001
                logger.error("run-service loop 线程异常退出", error=repr(exc))
                raise
        logger.error(f"loop 连续 {cls._LOOP_RESTART_LIMIT} 次被 SystemExit 打断，放弃；"
                     f"运行服务已不可用，需要重启程序")

    def shutdown(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._worker is not None:
            self._worker.join(timeout=timeout)
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)

    # ── 启动 / 取消 ──

    def start(self, request: RunRequest,
              on_event: Optional[Callable[[Any], None]] = None) -> str:
        """提交一次运行，**立即返回** run_id。

        不等它跑完 —— 调用方（CLI / GUI）拿 run_id 去查进度。
        """
        self._ensure_loop()
        if not request.origin or request.origin == "service":
            request.origin = "gui"
        root = unique_output_root(request.output_root or self.output_base)
        handle = _RunHandle(request, root)
        if on_event is not None:
            self._on_event = on_event
        with self._lock:
            self._queue.append(handle)
            self._handles[handle.run_id] = handle
        self._wake.set()
        return handle.run_id

    def resume(self, run_id: str, decision: str = "approve") -> str:
        """从一次**暂停**的运行接着跑，返回同一个 run_id。

        运行是不是"暂停"由检查点说了算，本方法不问 —— 问早了会在排队时骗人。
        真不是的话，运行线程会以"检查点里没有这次运行的状态"失败，调用方从
        `wait()` / 日志里看得到。**不在这里抛**：界面需要的是"提交之后异步报错"，
        而不是按钮回调里蹦一个异常（那种错误用户看不到）。

        时间线仍然是同一条：日志追加写、run_id 不变、证据留在同一个目录 ——
        "这次运行分两次跑完"本身就是可审计的一部分。
        """
        self._ensure_loop()
        root = _resolve_run_dir(self.output_base, run_id)
        request = RunRequest(output_root=root, resume_from=run_id,
                             resume_value=decision, run_id=run_id)
        handle = _RunHandle(request, Path(root))
        with self._lock:
            self._queue.append(handle)
            self._handles[handle.run_id] = handle    # 覆盖上一次的句柄
        self._wake.set()
        return handle.run_id

    def cancel(self, run_id: str = "") -> bool:
        """协作式取消。

        图**没有检查点**，所以取消只能停在节点边界 —— 当前节点会跑完。
        这不是缺陷而是如实反映：与其画一个做不到的"暂停"按钮，不如说清边界在哪。
        """
        with self._lock:
            handle = self._handles.get(run_id) if run_id else self._current
        if handle is None or handle.done.is_set():
            return False
        handle.cancel_event.set()
        return True

    def wait(self, run_id: str, timeout: Optional[float] = None) -> Dict[str, Any]:
        """等一次运行结束（CLI 与测试用）。超时返回空 dict —— 不抛，调用方自己判断。"""
        with self._lock:
            handle = self._handles.get(run_id)
        if handle is None:
            return {}
        if not handle.done.wait(timeout):
            return {}
        if handle.error is not None:
            raise handle.error
        return dict(handle.result)

    # ── 审批 ──

    def set_approval_handler(self, handler: Optional[Callable[[Any], None]]) -> None:
        """装上"有人要审批了"的接收方（界面用）。

        回调**在运行线程上被调用** —— Qt 那边必须经信号编组回主线程再弹框
        （`QObject` 的跨线程信号会自动排队，与 `tasks.TaskRunner` 同一套机制）。
        """
        self._approval_handler = handler

    def answer_approval(self, decision: Any) -> bool:
        """由界面线程回答当前挂起的那次审批。返回是否真的有人等着。"""
        channel = self._approval_channel
        if channel is None or channel.pending is None:
            return False
        channel.answer(decision)
        return True

    def pending_approval(self) -> Any:
        channel = self._approval_channel
        return channel.pending if channel is not None else None

    def _channel_for(self) -> Optional[Any]:
        """有人在听就用 EventChannel；没人听返回 None（让 gate 走默认的终端通道）。"""
        if self._approval_handler is None:
            return None
        if self._approval_channel is None:
            from src.layers.l2_orchestration.governance.approval import EventChannel
            self._approval_channel = EventChannel(
                on_request=lambda request: self._approval_handler(request))
        return self._approval_channel

    # ── 查询 ──

    @property
    def busy(self) -> bool:
        return self._current is not None

    def current_run_id(self) -> str:
        handle = self._current
        return handle.run_id if handle else ""

    def queued(self) -> List[str]:
        with self._lock:
            return [h.run_id for h in self._queue if h is not self._current]

    def status(self) -> Dict[str, Any]:
        return {"busy": self.busy, "current": self.current_run_id(),
                "queued": self.queued()}

    # ── 委托给 RunRepository（磁盘是唯一可靠来源）──

    def _repo(self):
        from src.layers.l2_orchestration.run_repository import RunRepository
        return RunRepository(self.output_base)

    def list_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """**含未完成**的运行列表。"""
        return self._repo().discover_runs(limit=limit)

    def journal(self, run_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        return self._repo().journal(run_id, after_seq=after_seq)

    def summary(self, run_id: str) -> Dict[str, Any]:
        return self._repo().journal_summary(run_id)

    def run_detail(self, run_id: str) -> Dict[str, Any]:
        """一次运行的"全部可见信息"：产物 + 过程 + 摘要。

        带全量事件而不是只带摘要：证据页要铺覆盖率曲线、要看逐条阶段，
        这些都在事件里。它是**按选中加载一次**的，不像轮询那样反复调。
        """
        detail = self._repo().get_run(run_id) or {}
        detail.update(self.summary(run_id))
        detail["events"] = self.journal(run_id)
        return detail

    # ── 工人线程 ──

    def _work(self) -> None:
        """串行消费队列。一次一个 run —— 见模块头的纪律 2。"""
        while not self._stop.is_set():
            if not self._wake.wait(timeout=0.5):
                continue
            self._wake.clear()
            while True:
                with self._lock:
                    pending = self._queue[0] if self._queue else None
                    self._current = pending
                if pending is None:
                    break
                if self._stop.is_set():
                    break
                self._execute(pending)
                with self._lock:
                    self._queue.remove(pending)
                    self._current = None
        with self._lock:
            self._current = None

    def _execute(self, handle: _RunHandle) -> None:
        loop = self._loop
        if loop is None:
            return
        # 循环线程要是已经死了，`run_coroutine_threadsafe` 照样返回一个 future，
        # 但它**永远不会完成** —— worker 会卡死在 `fut.result()` 上，界面看到的是
        # 「点了启动没反应」。这里先探一下，宁可立刻报错也不要挂在那儿。
        if not loop.is_running():
            handle.error = RuntimeError(
                "运行服务的 loop 线程已经不在了（见日志里的 'run-service-loop'）"
                "—— 需要重启程序")
            handle.done.set()
            logger.error(f"运行 {handle.run_id} 无法开始：run-service loop 线程已死")
            return
        fut = asyncio.run_coroutine_threadsafe(self._run(handle), loop)
        try:
            handle.result = fut.result()
        except BaseException as exc:              # noqa: BLE001
            handle.error = exc
            logger.warning(f"运行 {handle.run_id} 失败: {exc}")
        finally:
            handle.done.set()

    async def _run(self, handle: _RunHandle) -> Dict[str, Any]:
        """跑完一次运行 —— **这一层是 `SystemExit` 的防火墙**。

        `src/generation/uvm_tools/` 下那些件是照着独立 CLI 写的（`main.py` 里
        `sys.exit(main())`），schema 校验不过就 `raise SystemExit(...)`。当 CLI
        用没问题；可它在进程内被调用时是跑在**子线程的 asyncio 循环**上的，而
        `threading` 对 SystemExit 是**静默吞掉**的（不打印、不回调 excepthook）：

            loop 线程当场消失
            → `run_coroutine_threadsafe` 的 future 永不完成
            → worker 卡死在 `fut.result()`（run_service.py 的 `_execute`）
            → `self._loop` 还是非 None，于是**此后每一次启动都照样卡死**

        症状就是「点了启动没反应」，而且一条错误都看不到 —— 实测复现过一次，
        进程级瘫痪，只能重启。转成普通异常，这些后果全部消失：循环活着、future
        拿到异常、这次运行如实记成失败。工具该改的是别再 `sys.exit`，但**这里
        必须兜住**：界面不该因为某个工具写成了 CLI 形状就整个废掉。
        """
        try:
            return await self._run_impl(handle)
        except SystemExit as exc:                 # noqa: BLE001
            raise RuntimeError(
                f"运行 {handle.run_id} 被 SystemExit 中断：有工具把 CLI 的 "
                f"sys.exit 传上来了（{exc!r}）。工具在进程内被调用时应当抛异常，"
                f"而不是退出进程。") from exc

    async def _run_impl(self, handle: _RunHandle) -> Dict[str, Any]:
        from src.layers.l2_orchestration.execution import PipelineExecutionService

        req = handle.request
        # 有人听（界面装了 handler）→ EventChannel：不碰 stdin，超时降级为 SKIP
        # 并记账；没人听（无头 CLI）→ 交给默认终端通道。
        # 检查点模式下通道根本不会被问到（审批走 interrupt），但还是要造一个：
        # `requires_approval` 的风险判定与记录都挂在它身上。
        channel = self._channel_for()
        gate = req.approval_gate(channel)
        # VPlan 挂载与 CLI **同一套**（`verify_request.mount_vplan`）。
        req.prepare(handle.root)

        service = PipelineExecutionService.get_instance()
        return await service.run_closed_loop_streaming(
            spec_text=req.resolved_spec(),
            output_root=str(handle.root),
            target=req.target,
            max_rounds=req.max_rounds,
            design_style=req.design_style,
            bypass_design_model=req.bypass_design_model,
            sim_modes=list(req.sim_modes or []),
            manual_gate=bool(req.manual_gate),
            rtl_dir=str(req.rtl_dir or ""),
            approval_gate=gate,
            on_event=self._on_event,
            cancel_event=handle.cancel_event,
            run_id=handle.run_id,
            checkpointing=req.checkpointing,
            # **传的是"答案"，不是"哪次运行"** —— 是哪次运行由 run_id 表达。
            # 这两个值混在一起的话，`Command(resume=<run_id>)` 会把 run_id 当成
            # 审批决定喂回去，于是「拒绝」被识别成未知答案而静默降级成 SKIP。
            resume=req.resume_value if req.resume_from else None,
        )


# ═══════════════════════════════════════════════════════════════
# 单例
# ═══════════════════════════════════════════════════════════════

_service: Optional[RunService] = None
_service_lock = threading.Lock()


def get_run_service(output_base: str = "output") -> RunService:
    """进程级单例。

    必须单例：它管着"一次一个 run"这条约束与一个 loop 线程，多实例就等于
    两条约束互相不知道对方在跑什么。
    """
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = RunService(output_base=output_base)
    return _service


# ═══════════════════════════════════════════════════════════════
# 门面函数 —— 给「面」用的（工作台 bridge 按 module:function 解析）
# ═══════════════════════════════════════════════════════════════
# 为什么不直接绑类方法：`workbench/bridge` 只认 `pkg.mod:函数名` 这种可解析路径。
# 这几个壳子只做参数归一与"永远返回 dict"这两件事，不含语义。

def _normalize_sim_modes(sim_modes) -> List[str]:
    """仿真业务词条归一：`"cov,wave"` / `["cov", "wave"]` / None → 干净的词条表。

    **剔除不认识的词条并告警**，不原样透传：`apply_modes` 那边也会挡一次，但
    挡在运行请求这一层时错误还带着"是谁给的"这个上下文（界面下拉 / CLI 参数）。
    留空 → 默认 `cov+wave`（覆盖率是主指标，波形是事后现场）。
    """
    from src.layers.l2_orchestration.regression_tools import sim_modes as sm

    if sim_modes is None:
        return [sm.DEFAULT_MODE]
    if isinstance(sim_modes, str):
        sim_modes = [s.strip() for s in sim_modes.split(",")]
    out: List[str] = []
    for mode in sim_modes or []:
        mode = str(mode).strip()
        if not mode:
            continue
        if not sm.is_known(mode):
            logger.warning(f"未知的仿真业务 {mode!r}，已忽略"
                           f"（可用：{', '.join(m.mode for m in sm.all_modes())}）")
            continue
        if mode not in out:
            out.append(mode)
    unknown_biz = sm.unsupported(out)
    if unknown_biz:
        logger.warning(f"仿真业务 {', '.join(unknown_biz)} 在当前 EDA 后端（Questa）"
                       f"没有对应开关，取值是空的 —— 会被 apply_modes 告警忽略，"
                       f"不会往命令行里塞不存在的参数")
    return out


def start_run(spec_file: str = "", spec_text: str = "",
              output_root: str = "", target: Optional[float] = None,
              max_rounds: int = 5, design_style: str = "baseline",
              bypass_design_model: bool = False, approval: str = "threshold",
              approval_timeout_s: float = 0.0,
              sim_modes=None, manual_gate: bool = True,
              rtl_dir: str = "", vplan: str = "") -> Dict[str, Any]:
    """启动一次闭环运行，**立即**返回 run_id（不等它跑完）。

    `output_root` 留空 = 用服务自己的 output_base（默认 `output`）。

    `sim_modes`：回归要开的仿真业务（`cov` / `wave` / `debug_all` …）。收 `"a,b"` 或
    `["a","b"]`；留空用默认（覆盖率）。**不认识的词条会被剔除并告警**（见
    `sim_modes.unsupported`）—— 界面/CLI 都可能手滑，不能让一个错词条悄悄变成
    "这门业务没生效但也没人说"。
    """
    modes = _normalize_sim_modes(sim_modes)
    service = get_run_service(output_root or "output")
    request = RunRequest(
        spec_file=spec_file, spec_text=spec_text, output_root=output_root,
        target=target, max_rounds=int(max_rounds), design_style=design_style,
        bypass_design_model=bool(bypass_design_model), approval=approval,
        approval_timeout_s=float(approval_timeout_s or 0.0),
        sim_modes=modes,
        # 注意 `bool(...)` 不能省：`manual_gate=""` / `None` 想表达的也是"关"，
        # 但 `RunRequest` 的缺省是 True —— 不显式转布尔会让"关"悄悄变成"开"。
        manual_gate=bool(manual_gate),
        rtl_dir=str(rtl_dir or ""),
        vplan=str(vplan or ""),
    )
    run_id = service.start(request)
    return {"run_id": run_id, **service.status()}


def cancel_run(run_id: str = "") -> Dict[str, Any]:
    """协作式取消（停在节点边界）。run_id 留空 = 取消当前那次。"""
    service = get_run_service()
    accepted = service.cancel(run_id)
    return {"cancelled": accepted, "run_id": run_id or service.current_run_id(),
            **service.status()}


def list_runs(limit: int = 50) -> Dict[str, Any]:
    """**含未完成**的运行列表 —— 正在跑的、跑挂的都在里面。"""
    service = get_run_service()
    return {"runs": service.list_runs(limit=int(limit)), **service.status()}


def read_run_journal(run_id: str, after_seq: int = 0) -> Dict[str, Any]:
    """增量读某次运行的过程日志。`after_seq` 让轮询只取新增的那几条。"""
    events = get_run_service().journal(run_id, after_seq=int(after_seq))
    return {
        "run_id": run_id,
        "events": events,
        "count": len(events),
        "last_seq": max((e.get("seq", 0) for e in events), default=int(after_seq)),
    }


def run_status(run_id: str = "") -> Dict[str, Any]:
    """一次运行的概览（服务状态 + 日志摘要）。"""
    service = get_run_service()
    rid = run_id or service.current_run_id()
    if not rid:
        return {"run_id": "", **service.status()}
    summary = service.summary(rid)
    summary.update({"run_id": rid, **service.status()})
    return summary


def resume_run(run_id: str, decision: str = "approve") -> Dict[str, Any]:
    """从一次**暂停**的运行接着跑（`decision` 取 approve / reject / skip）。

    与 `answer_approval` 的分工：
      · 这一步走的是**检查点模式** —— 运行早就结束在这次 astream 上，人什么时候答都行。
      · `answer_approval` 走的是**通道模式** —— 运行还活着，挂在某个线程上等。
    界面上这两个是同一排按钮，由模块先问 `pending_approval` 再决定发给谁。
    """
    service = get_run_service()
    return {"run_id": service.resume(run_id, decision), "decision": decision,
            **service.status()}


def run_detail(run_id: str) -> Dict[str, Any]:
    """一次运行的全部可见信息（产物 + 过程 + 服务状态）。"""
    service = get_run_service()
    detail = service.run_detail(run_id)
    detail.update(service.status())
    return detail


# ── 审批（界面用）──────────────────────────────────────────────
# 装上 handler 之前，服务层不碰审批：gate 走 create_approval_gate 的默认终端
# 通道，无头 CLI 的行为与改动前完全一致。

def set_approval_handler(handler: Optional[Callable[[Any], None]] = None) -> Dict[str, Any]:
    """装上"有人要审批了"的接收方。

    **回调在运行线程上被调用** —— Qt 那边必须经信号编组回主线程再弹框。
    传 None 表示卸载（界面关掉了），此后运行回落到终端通道。
    """
    get_run_service().set_approval_handler(handler)
    return {"installed": handler is not None}


def answer_approval(decision: str) -> Dict[str, Any]:
    """回答当前挂起的那次审批。`decision` 取 approve / reject / skip / review。"""
    from src.layers.l2_orchestration.governance.approval import ApprovalDecision
    service = get_run_service()
    try:
        value = ApprovalDecision(str(decision).strip().lower())
    except ValueError:
        return {"answered": False, "error": f"未知决策：{decision}"}
    return {"answered": service.answer_approval(value), "decision": value.value}


def pending_approval() -> Dict[str, Any]:
    """当前是否有人正等着审批（界面靠它决定要不要弹框 / 亮提示）。"""
    request = get_run_service().pending_approval()
    if request is None:
        return {"pending": False}
    return {"pending": True, "stage": request.stage, "summary": request.summary,
            "risk_level": request.risk_level, "token": request.token,
            "timeout_s": request.timeout_s}
