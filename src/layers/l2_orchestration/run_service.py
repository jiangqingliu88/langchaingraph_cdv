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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# 请求
# ═══════════════════════════════════════════════════════════════

@dataclass
class RunRequest:
    """一次闭环运行的输入。字段与 `run_closed_loop` 的形参一一对应。"""

    spec_text: str = ""
    spec_file: str = ""
    #: 留空 = 用 RunService 自己的 output_base。
    #: 写死 "output" 会让服务层实例化时指定的基准目录被悄悄忽略 ——
    #: 界面上"启动"跑到仓库根的 output/，而列表读的是别处，两边对不上。
    output_root: str = ""
    target: Optional[float] = None
    max_rounds: int = 5
    design_style: str = "baseline"
    bypass_design_model: bool = False
    approval: str = "threshold"
    approval_timeout_s: float = 0.0
    run_id: str = ""
    #: 落检查点。打开之后高风险动作的审批从"阻塞等答案"变成"停下来等人"。
    checkpointing: bool = True
    #: 非空表示"从这次运行停下的地方继续"（值就是要重入的 run_id）。
    resume_from: str = ""
    #: 重入时给出的审批答案：approve / reject / skip。
    resume_value: str = "approve"

    def resolved_spec(self) -> str:
        """`spec_file` 与 `spec_text` 二选一；文件读不到就是空规格（会走启发式）。"""
        if self.spec_text:
            return self.spec_text
        if self.spec_file:
            try:
                return Path(self.spec_file).read_text(encoding="utf-8",
                                                      errors="replace")
            except OSError as exc:
                logger.warning(f"规格读取失败 {self.spec_file}: {exc}")
        return ""


def _resolve_run_dir(output_base: str, run_id: str) -> str:
    """run_id → 那次运行的目录（找不到就退回基准目录）。

    退回而不是抛：不存在的那次运行最终会以"检查点里没有它的状态"失败 ——
    那句话比"目录不存在"更能说明问题是什么。
    """
    from src.layers.l2_orchestration.run_repository import RunRepository
    found = RunRepository(output_base).run_dir(run_id)
    return str(found) if found else output_base


def _unique_root(base: str) -> Path:
    """给这次运行定一个不撞车的输出目录。

    `make_output_root` 的时间戳精确到**秒** —— 串行启动两次仍可能落在同一秒里，
    那会让两次运行写进同一个目录（日志、证据链全混在一起）。撞了就加后缀。
    """
    from src.layers.l1_infrastructure.output_config import make_output_root
    root = Path(make_output_root(base))
    if not root.exists():
        return root
    for i in range(2, 1000):
        candidate = root.with_name(f"{root.name}_{i}")
        if not candidate.exists():
            return candidate
    return root


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
                thread = threading.Thread(target=loop.run_forever,
                                          name="run-service-loop", daemon=True)
                thread.start()
                self._loop, self._thread = loop, thread
                self._worker = threading.Thread(target=self._work,
                                                name="run-service-worker",
                                                daemon=True)
                self._worker.start()
        return self._loop

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
        root = _unique_root(request.output_root or self.output_base)
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
        fut = asyncio.run_coroutine_threadsafe(self._run(handle), loop)
        try:
            handle.result = fut.result()
        except BaseException as exc:              # noqa: BLE001
            handle.error = exc
            logger.warning(f"运行 {handle.run_id} 失败: {exc}")
        finally:
            handle.done.set()

    async def _run(self, handle: _RunHandle) -> Dict[str, Any]:
        from src.layers.l2_orchestration.execution import PipelineExecutionService
        from src.layers.l2_orchestration.governance.approval import (
            create_approval_gate,
        )

        req = handle.request
        # 有人听（界面装了 handler）→ EventChannel：不碰 stdin，超时降级为 SKIP
        # 并记账；没人听（无头 CLI）→ 交给 create_approval_gate 的默认终端通道。
        # 检查点模式下通道根本不会被问到（审批走 interrupt），但还是要造一个：
        # `requires_approval` 的风险判定与记录都挂在它身上。
        channel = self._channel_for()
        gate = create_approval_gate(req.approval, channel=channel,
                                    timeout_s=req.approval_timeout_s)

        service = PipelineExecutionService.get_instance()
        return await service.run_closed_loop_streaming(
            spec_text=req.resolved_spec(),
            output_root=str(handle.root),
            target=req.target,
            max_rounds=req.max_rounds,
            design_style=req.design_style,
            bypass_design_model=req.bypass_design_model,
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

def start_run(spec_file: str = "", spec_text: str = "",
              output_root: str = "", target: Optional[float] = None,
              max_rounds: int = 5, design_style: str = "baseline",
              bypass_design_model: bool = False, approval: str = "threshold",
              approval_timeout_s: float = 0.0) -> Dict[str, Any]:
    """启动一次闭环运行，**立即**返回 run_id（不等它跑完）。

    `output_root` 留空 = 用服务自己的 output_base（默认 `output`）。
    """
    service = get_run_service(output_root or "output")
    request = RunRequest(
        spec_file=spec_file, spec_text=spec_text, output_root=output_root,
        target=target, max_rounds=int(max_rounds), design_style=design_style,
        bypass_design_model=bool(bypass_design_model), approval=approval,
        approval_timeout_s=float(approval_timeout_s or 0.0),
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
