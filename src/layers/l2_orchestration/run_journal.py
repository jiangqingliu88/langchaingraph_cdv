"""运行日志 —— 一次闭环「发生过什么」的唯一记录。

为什么要有这个文件
    在此之前，一次运行的过程只活在进程里：agent 日志进 logger，阶段推进进
    `state.phases`，跑完把结果写进 `docs/manifest.json`。于是：

      · 运行期间**没有任何可观测面**。`PipelineExecutionService._runs` 从未被
        填充，CLI 的 `watch` / `history` 的实时分支是死的（见 commands.py:1093）；
      · 进程崩了，过程信息随之消失，只剩一个半成品目录；
      · 「在终端里跑、在界面里看」不可能 —— 界面看不到别的进程。

    本模块把过程写成**追加式的 JSONL**，落盘在 `output/{run}/docs/run_events.jsonl`。

四条纪律（都是为了让"可复现·可审计"落到这一层）
    1. **只追加，不修改**。崩溃时日志天然完整（最后一行可能截断，读取侧跳过）。
    2. **seq 单调**。重放顺序确定，增量读只需记住 seq。
    3. **每条自带 round / stage / agent**。前端不必自己维护状态机，过滤即视图。
    4. **只放可 JSON 化的东西**。与 `PipelineState` 同一条纪律：活连接、agent
       实例、LLM 客户端一律不进日志。

实时视图与历史视图读的是**同一份数据**（`read_journal` / `JournalTail`）——
这是本设计最要紧的一点：界面不需要为"正在跑的 run"和"看完的 run"写两套渲染。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union

import structlog

from src.layers.l2_orchestration.stages import executor_of, title_of

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════════
# 事件种类
# ═══════════════════════════════════════════════════════════════

KIND_RUN_STARTED = "run.started"
KIND_RUN_FINISHED = "run.finished"
KIND_RUN_FAILED = "run.failed"
KIND_RUN_CANCELLED = "run.cancelled"
#: 停在检查点上等人（有检查点时的审批）。**不是终态** —— 这次 astream 结束了，
#: 但运行没有结束，它可以（在另一个进程、另一天）接着跑。
KIND_RUN_INTERRUPTED = "run.interrupted"
#: 从检查点续跑。与 run.started 成对出现是正常的：一次运行可以有多个 started。
KIND_RUN_RESUMED = "run.resumed"

KIND_STAGE_STARTED = "stage.started"
KIND_STAGE_FINISHED = "stage.finished"
KIND_STAGE_FAILED = "stage.failed"

KIND_COVERAGE_UPDATED = "coverage.updated"
KIND_DECISION = "decision"
KIND_APPROVAL_REQUESTED = "approval.requested"
KIND_APPROVAL_DECIDED = "approval.decided"
#: 人在界面上改了一个文件（配置或运行产物）。事件落在**运行时间线的正确位置**上
#: —— 因为日志是追加写的，不会被谁覆盖。与它配对的是**项目级**的人工变更链
#: `.signoffai/human_edits.json`（见 evidence/human_edit.py 为什么不能塞进
#: 某次运行的 `file_change_chain.json`）。
KIND_HUMAN_EDIT = "human.edit"

KIND_PROGRESS = "progress"      # 节点内推的细粒度进度（stream_mode="custom"）
KIND_NOTE = "note"              # 任意给人看的一句话

#: 一次运行"结束"了的三种方式 —— 界面用它决定要不要停掉轮询。
#: `run.interrupted` **不在这里**：它是"暂停"，不是"完事"。
TERMINAL_KINDS = (KIND_RUN_FINISHED, KIND_RUN_FAILED, KIND_RUN_CANCELLED)
#: "这次 astream 到此为止" —— 终态 + 暂停。轮询该停，但界面上的"运行状态"
#: 两者不同：前者是完成/失败，后者是**等人**。
IDLE_KINDS = TERMINAL_KINDS + (KIND_RUN_INTERRUPTED,)


# ═══════════════════════════════════════════════════════════════
# 事件
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class RunEvent:
    """日志里的一行。

    字段刻意"宽而平"：多几个空字段，好过让读取侧在 dict 里猜有没有这个键。
    `title` 是写入时就查好的中文名 —— 读的一方不必再 import 阶段表。
    """

    seq: int
    ts: str
    kind: str
    run_id: str = ""
    round: int = 0
    stage: str = ""
    agent: str = ""
    title: str = ""
    status: str = ""
    duration_s: float = 0.0
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seq": self.seq, "ts": self.ts, "kind": self.kind, "run_id": self.run_id,
            "round": self.round, "stage": self.stage, "agent": self.agent,
            "title": self.title, "status": self.status,
            "duration_s": self.duration_s, "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunEvent":
        """容错构造：缺字段用默认值，多字段忽略。

        读的一方是界面 —— 让它在一条脏记录上抛异常，等于整个运行看不见。
        """
        return cls(
            seq=int(d.get("seq", 0)),
            ts=str(d.get("ts", "")),
            kind=str(d.get("kind", "")),
            run_id=str(d.get("run_id", "")),
            round=int(d.get("round", 0) or 0),
            stage=str(d.get("stage", "")),
            agent=str(d.get("agent", "")),
            title=str(d.get("title", "")),
            status=str(d.get("status", "")),
            duration_s=float(d.get("duration_s", 0.0) or 0.0),
            payload=dict(d.get("payload") or {}),
        )

    @property
    def is_terminal(self) -> bool:
        return self.kind in TERMINAL_KINDS

    @property
    def is_failure(self) -> bool:
        return self.kind in (KIND_RUN_FAILED, KIND_STAGE_FAILED) or self.status == "failed"


# ═══════════════════════════════════════════════════════════════
# 写
# ═══════════════════════════════════════════════════════════════

def journal_path(output_root: Union[str, Path]) -> Path:
    """运行目录 → 日志文件。位置固定在 docs/ 下，与 manifest/证据链同处。"""
    return Path(output_root) / "docs" / "run_events.jsonl"


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _last_seq(path: Path) -> int:
    """已有日志里最大的 seq（没有文件 / 读不出来就是 0）。

    只关心"下一个该编几号"，所以容忍坏行：读到什么算什么。
    """
    largest = 0
    for event in iter_events(path):
        largest = max(largest, event.seq)
    return largest


def _jsonable(value: Any, _depth: int = 0) -> Any:
    """把一个状态增量压成可 JSON 化的东西。

    节点返回的是 PipelineState 的增量 dict，里面可能有 Path / dataclass /
    BaseModel —— 日志不能因此写不出来。深度超限或类型不认识时退化成 repr。
    这是**有损**的，所以只用于 payload（给人看的摘要），不用于 seq/stage 这类
    结构字段。
    """
    if _depth > 4:
        return repr(value)[:200]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v, _depth + 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v, _depth + 1) for v in list(value)[:50]]
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(), _depth + 1)
        except Exception:                     # noqa: BLE001
            return repr(value)[:200]
    return repr(value)[:200]


class RunJournal:
    """一次运行的追加式日志。

    写失败**不抛给调用方** —— 日志是观测手段，不能因为它坏了就把验证跑挂掉。
    但也不静默：失败计数记在 `write_errors` 上，结束时能看出来。
    """

    FILENAME = "run_events.jsonl"

    def __init__(self, output_root: Union[str, Path], run_id: str = ""):
        self.output_root = Path(output_root)
        self.run_id = run_id or self.output_root.name
        self.path = journal_path(self.output_root)
        self.round_num: int = 0          # 由观察循环更新；记录时作为默认值
        self.write_errors: int = 0
        # **从已有内容的最后一条接着编号**，不是从 1 重来。
        #
        # 一次运行可以分几次跑完（检查点重入、换个进程继续），日志是**追加**到
        # 同一个文件上的。如果每次开头都把 seq 归零，增量读的一方（界面按
        # `after_seq` 轮询）会认为"这些我都看过了"，把后半段整段丢掉 ——
        # 而且是静默丢掉，界面上表现为"重入了但时间线不动"。
        self._seq: int = _last_seq(self.path)
        self._fh = None
        self._disabled = False

    # ── 底层 ──

    def _open(self) -> bool:
        if self._disabled:
            return False
        if self._fh is not None:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # "a" 追加模式：一次运行一个进程写，不做并发合并（见 run_service 的串行约束）
            self._fh = self.path.open("a", encoding="utf-8", newline="\n")
            return True
        except OSError as exc:
            self.write_errors += 1
            self._disabled = True
            logger.warning(f"运行日志不可写（后续事件将被丢弃）: {exc}")
            return False

    def record(self, kind: str, *, stage: str = "", agent: str = "",
               round_num: Optional[int] = None, status: str = "",
               duration_s: float = 0.0,
               payload: Optional[Dict[str, Any]] = None) -> RunEvent:
        """写一条。返回事件对象（即使写盘失败也返回，调用方可以继续用）。"""
        self._seq += 1
        event = RunEvent(
            seq=self._seq,
            ts=_now(),
            kind=kind,
            run_id=self.run_id,
            round=int(self.round_num if round_num is None else round_num),
            stage=stage,
            agent=agent or (executor_of(stage) if stage else ""),
            title=title_of(stage) if stage else "",
            status=status,
            duration_s=round(float(duration_s), 3),
            payload=_jsonable(payload or {}),
        )
        if self._open():
            try:
                self._fh.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
                self._fh.flush()        # 立刻可见：界面靠轮询 tail，不 flush 会看不到
            except OSError as exc:
                self.write_errors += 1
                logger.warning(f"运行日志写入失败: {exc}")
        return event

    # ── 语义化记录 ──

    def run_started(self, **info: Any) -> RunEvent:
        return self.record(KIND_RUN_STARTED, payload=info)

    def run_finished(self, result: Dict[str, Any]) -> RunEvent:
        return self.record(KIND_RUN_FINISHED, status="ok", payload={
            "status": result.get("status", ""),
            "converged": result.get("converged", False),
            "final_coverage": result.get("final_coverage", 0),
            "effective_coverage": result.get("effective_coverage", 0),
            "iterations": result.get("iterations", 0),
        })

    def run_failed(self, error: BaseException) -> RunEvent:
        return self.record(KIND_RUN_FAILED, status="failed", payload={
            "error": f"{type(error).__name__}: {error}"})

    def run_cancelled(self, reason: str = "用户取消") -> RunEvent:
        return self.record(KIND_RUN_CANCELLED, status="cancelled",
                           payload={"reason": reason})

    def run_interrupted(self, stage: str, payload: Dict[str, Any]) -> RunEvent:
        """停下来了，等人 —— 不是失败，也不是结束。"""
        return self.record(KIND_RUN_INTERRUPTED, stage=stage, status="waiting",
                           payload=payload)

    def run_resumed(self, decision: str) -> RunEvent:
        return self.record(KIND_RUN_RESUMED, status="running",
                           payload={"decision": decision})

    def stage_started(self, stage: str) -> RunEvent:
        return self.record(KIND_STAGE_STARTED, stage=stage, status="running")

    def stage_finished(self, stage: str, duration_s: float,
                       delta: Optional[Dict[str, Any]] = None) -> RunEvent:
        return self.record(KIND_STAGE_FINISHED, stage=stage, status="ok",
                           duration_s=duration_s, payload=self._summarise(delta))

    def stage_failed(self, stage: str, duration_s: float, error: str) -> RunEvent:
        return self.record(KIND_STAGE_FAILED, stage=stage, status="failed",
                           duration_s=duration_s, payload={"error": error})

    def coverage_updated(self, *, total: float = 0.0, functional: float = 0.0,
                         **extra: Any) -> RunEvent:
        return self.record(KIND_COVERAGE_UPDATED, stage="coverage",
                           payload={"total": round(float(total), 4),
                                    "functional": round(float(functional), 4),
                                    **extra})

    def decision(self, action: str, reason: str = "", **extra: Any) -> RunEvent:
        return self.record(KIND_DECISION, stage="decide",
                           payload={"action": action, "reason": reason, **extra})

    def approval_requested(self, action: str, risk: str, reason: str,
                           token: str = "") -> RunEvent:
        return self.record(KIND_APPROVAL_REQUESTED, stage="approval",
                           status="waiting",
                           payload={"action": action, "risk": risk,
                                    "reason": reason, "token": token})

    def approval_decided(self, decision: str, token: str = "",
                         by: str = "human", **extra: Any) -> RunEvent:
        return self.record(KIND_APPROVAL_DECIDED, stage="approval",
                           status=decision,
                           payload={"decision": decision, "token": token,
                                    "by": by, **extra})

    def progress(self, stage: str, message: str, **extra: Any) -> RunEvent:
        return self.record(KIND_PROGRESS, stage=stage,
                           payload={"message": message, **extra})

    def note(self, message: str, **extra: Any) -> RunEvent:
        return self.record(KIND_NOTE, payload={"message": message, **extra})

    # ── 生命周期 ──

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except OSError:                   # noqa: BLE001
                pass
            self._fh = None

    def __enter__(self) -> "RunJournal":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @staticmethod
    def _summarise(delta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """状态增量 → 一行摘要。

        一个节点可能写十几个键，界面上只显示一行 —— 所以只挑结构化的几个。
        全量增量没有丢：它在 `payload.delta` 里，要看细节的有地方看。
        """
        if not delta:
            return {}
        keep = ("status", "passed", "failed", "count", "score", "reason",
                "coverage", "verdict", "message")
        summary = {k: _jsonable(v) for k, v in delta.items() if k in keep}
        summary["delta"] = _jsonable(delta)
        return summary


# ═══════════════════════════════════════════════════════════════
# 读
# ═══════════════════════════════════════════════════════════════

def iter_events(path: Union[str, Path]) -> Iterator[RunEvent]:
    """逐行读，坏行跳过。

    **崩在半截的最后一行**是正常情况：进程被杀时最后一条 JSON 可能只写了一半。
    解析失败的策略是"跳过并继续"，不是抛异常 —— 日志的价值在于它记下的部分。
    """
    p = Path(path)
    if not p.exists():
        return
    try:
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield RunEvent.from_dict(json.loads(line))
                except (json.JSONDecodeError, TypeError, ValueError):
                    continue
    except OSError as exc:
        logger.warning(f"运行日志读取失败 {p}: {exc}")


def read_journal(output_root: Union[str, Path],
                 after_seq: int = 0) -> List[RunEvent]:
    """读一个运行的全部事件（或 seq > after_seq 的部分）。

    `output_root` 可以是运行目录，也可以直接是日志文件路径 —— 调用方从
    RunRepository 拿到的是目录，从界面拿到的是路径，两边都该能用。
    """
    return [e for e in iter_events(_as_path(output_root)) if e.seq > after_seq]


def _as_path(target: Union[str, Path]) -> Path:
    p = Path(target)
    if p.is_dir() or p.suffix != ".jsonl":
        return journal_path(p)
    return p


class JournalTail:
    """增量读 —— 界面轮询用。

    只读**新增字节**，不重读整个文件：一次运行几百条事件，每 500ms 重读一遍
    在文件变大之后是浪费；更重要的是，字节偏移能自然地停在"半截行"之前，
    等下一次轮询再读完整的那一行。

    用法：
        tail = JournalTail(output_root)
        for event in tail.poll():        # 每次只给新的
            ...

    切换 run 时调 `reset()`（或新建一个）。
    """

    def __init__(self, output_root: Union[str, Path]):
        self.path = _as_path(output_root)
        self._offset = 0
        self._seq = 0
        self._partial = ""      # 上次读到的半截行（无换行结尾）

    @property
    def last_seq(self) -> int:
        return self._seq

    def reset(self) -> None:
        self._offset = 0
        self._seq = 0
        self._partial = ""

    def poll(self) -> List[RunEvent]:
        """读自上次以来新增的**完整**行。没有新增就返回空列表。"""
        if not self.path.exists():
            return []
        try:
            size = self.path.stat().st_size
        except OSError:
            return []
        if size < self._offset:
            # 文件被截断/换了一份（同一个 run 目录重跑）—— 重头来
            self._offset = 0
            self._seq = 0
            self._partial = ""
        if size == self._offset:
            return []

        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(self._offset)
                chunk = fh.read()
                self._offset = fh.tell()
        except OSError:
            return []

        chunk = self._partial + chunk
        lines = chunk.split("\n")
        # 最后一段没有换行结尾 → 半截行，留给下次
        self._partial = lines.pop() if lines else ""

        out: List[RunEvent] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                event = RunEvent.from_dict(json.loads(line))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if event.seq > self._seq:
                self._seq = event.seq
            out.append(event)
        return out
