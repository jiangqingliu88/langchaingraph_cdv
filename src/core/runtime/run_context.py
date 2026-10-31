"""RunContext —— 一次运行的**身份与执行环境**。

为什么要有它
    在它之前，「这次 run 是谁、输出在哪、父 run 是谁」散在 CLI 参数、`Runtime`
    的若干属性、`PipelineState.output_root` 和各处 `Path(...)` 拼接里。结果是
    同一份事实有多个来源：多模块并发时各拼各的路径，断点续跑时 run_id 可能被
    重新生成，产物级的「哪次 run 产的」只能靠目录名猜。

    本模块把身份收成不可变对象，执行环境通过 contextvar 绑定。**它不替代
    LangGraph 的流程状态**：流程状态归 PipelineState，执行环境归 RunContext，
    产物生命周期归 ArtifactStore —— 三者不互相承担职责。

刻意不依赖任何上层
    只用标准库。core 比 L1 更底，任何层都可以依赖它。
"""
from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass(frozen=True)
class RunPaths:
    """一次 run 的目录契约 —— 读写的**唯一**入口，别在各处拼字符串。"""

    root: Path

    @property
    def docs(self) -> Path:
        return self.root / "docs"

    @property
    def artifacts(self) -> Path:
        return self.root / "artifacts"

    @property
    def cas(self) -> Path:
        return self.artifacts / "cas"

    @property
    def decision(self) -> Path:
        return self.root / "decision"

    @property
    def coverage(self) -> Path:
        return self.root / "coverage"

    @property
    def jobs(self) -> Path:
        return self.root / ".signoffai" / "jobs"

    def ensure(self) -> "RunPaths":
        for path in (self.root, self.docs, self.artifacts, self.cas,
                     self.decision, self.coverage, self.jobs):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def events_file(self) -> Path:
        return self.docs / "events.jsonl"

    def artifact_index(self) -> Path:
        return self.artifacts / "artifacts.json"


@dataclass(frozen=True)
class RunContext:
    """一次运行的不可变身份。

    字段只放**可序列化、可比较**的事实。活连接、agent 实例、文件句柄一律不放
    —— 那些归 `Runtime`（L2），与本对象无关。
    """

    run_id: str
    output_root: Path
    project_id: str = ""
    module_id: str = ""
    rtl_hash: str = ""
    spec_hash: str = ""
    policy_hash: str = ""
    simulator: str = "questa"
    seed: int = 0
    parent_run_id: Optional[str] = None
    started_at: str = field(default_factory=_now)

    def __post_init__(self) -> None:
        # 允许调用方传 str；统一成 Path（frozen dataclass 用 object.__setattr__）
        if not isinstance(self.output_root, Path):
            object.__setattr__(self, "output_root", Path(self.output_root))

    @property
    def paths(self) -> RunPaths:
        return RunPaths(self.output_root)

    def child(self, name: str, *, module_id: str = "",
              seed: int = 0, simulator: str = "") -> "RunContext":
        """派生一个子 run（多模块 / 多 DUT）。

        子 run 的输出目录是父目录下的 `name`，`parent_run_id` 指回父 run ——
        这是「一个签核依赖了哪些子验证」可追溯的结构基础。
        """
        safe = str(name).strip().replace("\\", "/").strip("/") or "child"
        return RunContext(
            run_id=f"{self.run_id}::{safe}",
            output_root=self.output_root / safe,
            project_id=self.project_id,
            module_id=module_id or safe,
            rtl_hash=self.rtl_hash,
            spec_hash=self.spec_hash,
            policy_hash=self.policy_hash,
            simulator=simulator or self.simulator,
            seed=seed,
            parent_run_id=self.run_id,
        )

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "output_root": str(self.output_root),
            "project_id": self.project_id,
            "module_id": self.module_id,
            "rtl_hash": self.rtl_hash,
            "spec_hash": self.spec_hash,
            "policy_hash": self.policy_hash,
            "simulator": self.simulator,
            "seed": self.seed,
            "parent_run_id": self.parent_run_id,
            "started_at": self.started_at,
        }


_CURRENT: "contextvars.ContextVar[Optional[RunContext]]" = contextvars.ContextVar(
    "signoffai_run_context", default=None)


def open_run_context(output_root: str | Path, run_id: Optional[str] = None,
                     **kwargs) -> RunContext:
    """按输出目录建 RunContext；`run_id` 缺省用目录名（与既有契约一致）。"""
    root = Path(output_root)
    ctx = RunContext(run_id=run_id or root.name, output_root=root, **kwargs)
    return ctx


@contextmanager
def bind(ctx: Optional[RunContext]) -> Iterator[Optional[RunContext]]:
    """在 `with` 作用域内绑定当前 run。退出时恢复原值，可安全嵌套。"""
    token = _CURRENT.set(ctx)
    try:
        yield ctx
    finally:
        _CURRENT.reset(token)


def reset(token) -> None:
    """恢复 `bind` 之前的上下文（给不方便用 with 的调用点）。"""
    _CURRENT.reset(token)


def set_current(ctx: Optional[RunContext]):
    """设置当前 run 并返回 token（`reset(token)` 恢复）。"""
    return _CURRENT.set(ctx)


def active_context() -> Optional[RunContext]:
    """当前绑定的 run；未绑定时返回 None，**不抛异常**。

    这个「返回 None 而不是报错」的选择是有意的：工具层、日志层会在 CLI 的
    非流水线命令里被调用，那里本来就没有 run —— 让它们为「没有 run」写异常
    分支，只会鼓励各处 try/except 吞错。
    """
    return _CURRENT.get()
