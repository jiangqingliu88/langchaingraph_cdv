"""点状 LLM 调用的**出处** —— 这次调用是哪一轮、哪个节点催出来的。

## 为什么需要它（以及为什么不能直接塞进 `call_llm` 的参数）

`call_llm`（`tools/lib/llm_call.py`）是**唯一收口**，但它够不着 LangGraph 的
`state`：调用链是

    node(有 state) → `_run_agent`（建 task 时把 state **降级成纯 dict**）
                   → `agent.execute_task(task)`
                   → executor 内的 `@staticmethod`
                   → `call_llm(prompt, code, errors)`

七个调用点里**没有一个**在 `call_llm` 这一层手里有 state（`_llm_write_ip` 连
`self` 都没有）。所以"给 call_llm 加个 node_id 参数"要么改七处签名、要么穿过
三层，都改不动。

而 `_run_agent`（`runtime.py`）是**唯一同时看得见 state 与 task 的地方** ——
在那里把出处记进 contextvar，`call_llm` 沿调用链读回来即可。它是**隐式传参**，
但传的只是"诊断用的出处"，缺少它不影响任何行为，所以隐式是划算的。

## 为什么落盘要在这里带上

审计记录原来只在 `LLMQueryEngine.audit_log` 里留最近 500 条**内存**条目 ——
进程一退就没了。而"这一行 RTL 是谁在哪一轮催出来的"恰恰是**事后**才问的问题。
所以出处里也带上 `audit_dir`（= 这次 run 的目录），审计往
`<run>/docs/llm_audit.jsonl` **追加写**（`docs/` 已被证据包 `dump` 全量收走）。
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator, Optional


@dataclass(frozen=True)
class LLMOrigin:
    """一次 LLM 调用的出处。"""
    node_id: str = ""      # 哪个图节点（`_run_agent` 的 label）
    round: int = 0         # 第几轮（`state.round_num`）
    audit_dir: str = ""    # 这次 run 的目录；空 = 不在某个 run 里（如 CLI 单跑工具）


#: 当前出处。`default=None` = **不在图里跑的**（CLI 直接调工具就是这样），
#: 那时审计只进内存、不落盘 —— 没有 run 目录可写，如实当作"没有"。
_CURRENT: ContextVar[Optional[LLMOrigin]] = ContextVar("llm_origin", default=None)


def current() -> Optional[LLMOrigin]:
    """当前的出处；不在图里跑时为 `None`。"""
    return _CURRENT.get()


@contextmanager
def origin_scope(node_id: str, round_num: int, audit_dir: str = "") -> Iterator[None]:
    """在 `with` 里把出处钉住 —— 退出时**恢复**外层（不是清空）。

    用 `contextvars` 而不是全局变量：LangGraph 会并发跑节点，全局变量会让
    并发的两条链互相覆盖出处，而**错得出处的审计比没有出处更坏**
    （它会把人指向一个无辜的节点）。
    """
    token = _CURRENT.set(LLMOrigin(node_id=str(node_id or ""),
                                   round=int(round_num or 0),
                                   audit_dir=str(audit_dir or "")))
    try:
        yield
    finally:
        _CURRENT.reset(token)
