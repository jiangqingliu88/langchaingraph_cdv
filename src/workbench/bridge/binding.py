"""工具注册表 —— 名字 → 函数，外加上一层返回值归一化。

为什么需要归一化：`src/tools/` 里的包**返回值不统一**。
`uvm_tools` 返回真 dict；`debug_tools`、`coverage_tools`、`assertion_tools` 这些返回的是
**JSON 字符串**（因为它们的第一个消费者是 LangChain，而工具得给字符串）。
界面不该为每个模块记一遍「这个要 json.loads、那个不要」—— 那是绑定表该
回答的问题。

**归一化永不抛。** `kind="json"` 但拿到的不是合法 JSON 时，返回
`{"raw": 原文, "_parse_error": ...}`。理由：工具的错误路径常常返回纯文本
（而不是 JSON），那正是最需要让用户看到的时候 —— 这时候抛异常，用户看到
的是「解析失败」，而不是工具真正想说的那句话。

**`pure=False` 的不许被顺手调用。** LLM 相关与长任务（编译/仿真/回归）
标记为非纯，`call()` 默认拒绝执行它们，必须 `force=True`。否则「切了一下
标签页就烧了一次 LLM 调用」这种事迟早会发生。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..loader import FactoryError, resolve

#: 认得出来的归一化方式
KINDS = ("auto", "text", "json", "filesystem")

#: 触发权限：谁能发起这次调用
#:   user     —— 只能由人显式触发（agent 调不动）
#:   agent    —— 人和 agent 都可以（只读工具的默认）
#:   approval —— 必须带人工审批（approval=True）才能执行，例如写发布包
TRIGGERS = ("user", "agent", "approval")


@dataclass(frozen=True)
class ToolBinding:
    """一条绑定：清单里写的名字，对应哪个函数、怎么解释它的返回值。"""

    name: str
    target: str                      # "src.executors.debug.tools.main:collect_sim_log"
    kind: str = "auto"
    #: False = LLM 调用 / 长任务，`call()` 默认不执行
    pure: bool = True
    doc: str = ""
    #: 触发权限；空 = 按 pure 推导（纯工具 agent 可调，非纯的只能人触发）
    trigger: str = ""

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"未知的 kind={self.kind!r}（可选：{KINDS}）")
        if self.trigger and self.trigger not in TRIGGERS:
            raise ValueError(
                f"未知的 trigger={self.trigger!r}（可选：{TRIGGERS}）")

    @property
    def effective_trigger(self) -> str:
        return self.trigger or ("agent" if self.pure else "user")


class ToolError(RuntimeError):
    """工具调用失败。`name` 是绑定名，`cause` 是底层异常或拒绝理由。"""

    def __init__(self, name: str, cause: Any) -> None:
        self.name = name
        self.cause = cause
        super().__init__(f"工具 {name} 调用失败：{cause}")


class UnknownTool(ToolError):
    """绑定表里没有这个名字 —— 通常是清单里写错了。"""


class ToolRegistry:
    """绑定表的查询与调用。

    刻意**同步**：这让「清单里这个工具能不能调通」可以脱离 Qt 回答。长任务
    由调用方丢给 `tasks.TaskRunner`，注册表不替它做主。
    """

    def __init__(self) -> None:
        self._bindings: Dict[str, ToolBinding] = {}

    # ── 注册与查询 ──

    def register(self, binding: ToolBinding) -> None:
        if binding.name in self._bindings:
            existing = self._bindings[binding.name]
            if existing != binding:
                raise ValueError(
                    f"绑定名 {binding.name!r} 重复且不一致："
                    f"{existing.target} vs {binding.target}")
        self._bindings[binding.name] = binding

    def register_all(self, bindings) -> None:
        for binding in bindings:
            self.register(binding)

    def get(self, name: str) -> ToolBinding:
        binding = self._bindings.get(name)
        if binding is None:
            known = ", ".join(sorted(self._bindings)) or "（空）"
            raise UnknownTool(name, f"没有这个绑定。已登记：{known}")
        return binding

    def has(self, name: str) -> bool:
        return name in self._bindings

    def names(self) -> List[str]:
        return sorted(self._bindings)

    def __len__(self) -> int:
        return len(self._bindings)

    # ── 调用 ──

    def call(self, name: str, *args, force: bool = False,
             actor: str = "user", approval: bool = False, **kwargs) -> Any:
        """调一个绑定，返回归一化后的结果。失败抛 `ToolError`。

        三层闸门（缺一不可）：
          1. `pure=False` 还要 `force=True` —— "别切个标签页就顺手跑一次"；
          2. `trigger` 决定**谁能**发起：user 只认人，agent 人机都行，
             approval 必须带 `approval=True`（写发布包/RTL 这类对外动作）；
          3. 真正的权限/目录/命令/预算治理在 Core（Job Supervisor），
             这里只回答"这次调用允许被发起吗"。
        """
        binding = self.get(name)
        if actor not in ("user", "agent"):
            raise ToolError(name, f"未知调用者 actor={actor!r}（user / agent）")
        if not binding.pure and not force:
            raise ToolError(
                name, "这是长任务/LLM 工具，需要显式触发（call(..., force=True)）"
                      "—— 避免切换标签页就顺手跑一次")
        trigger = binding.effective_trigger
        if actor == "agent" and trigger == "user":
            raise ToolError(name, "这条绑定只允许人工触发（trigger=user）")
        if trigger == "approval" and not approval:
            raise ToolError(name, "这条绑定需要人工审批（approval=True）才能执行")
        target = self._target(binding)
        try:
            raw = target(*args, **kwargs)
        except Exception as exc:                  # noqa: BLE001  统一换成 ToolError
            raise ToolError(name, exc) from exc
        return normalize(raw, binding.kind)

    @staticmethod
    def _target(binding: ToolBinding):
        try:
            return resolve(binding.target)
        except FactoryError as exc:
            raise ToolError(binding.name, f"绑定路径解析不了：{exc}") from exc


def normalize(raw: Any, kind: str = "auto") -> Any:
    """把工具返回值归一化成「界面好用的形状」。见模块文档字符串。"""
    if kind == "filesystem":
        return raw
    if kind == "text":
        return "" if raw is None else str(raw)
    if kind == "json":
        return _as_json(raw)
    # auto：字符串长得像 JSON 就试着解析，不像就原样返回
    if isinstance(raw, str) and raw.lstrip()[:1] in ("{", "["):
        return _as_json(raw)
    return raw


def _as_json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)) or raw is None:
        return raw
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return {"raw": raw, "_parse_error": str(exc)}


def payload_error(payload: Any) -> Optional[str]:
    """从工具结果里认出「这是一条错误」并取出那句话。

    `debug_tools` 找不到 output 目录时返回 `{"error": "output_dir not found"}`，
    把它原样丢进表格会显示成一行莫名其妙的文本 —— 认出来才能变成横幅。
    """
    if isinstance(payload, dict):
        for key in ("error", "_parse_error"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(payload, str) and payload.strip().lower().startswith("error"):
        return payload.strip()
    return None


def rows_of(payload: Any, key: Optional[str] = None) -> List[Any]:
    """从工具结果里取出「可以铺进表格的那一列」。

    三种常见形状：顶层就是列表 / `{"<key>": [...]}` / 单个 dict（当一行）。
    """
    data = payload
    if key and isinstance(data, dict):
        data = data.get(key)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        # {"error": ...} 不是一行数据，别把它当行显示
        if payload_error(data) and len(data) <= 2:
            return []
        return [data]
    return [{"value": data}]


def scalar_rows(payload: Any) -> List[Dict[str, str]]:
    """把「扁平 dict」铺成两列表格用的一行行 —— 给指纹这类结果用。

    `{"fingerprint": "abc", "line": 42}` → `[{"键": "fingerprint", "值": "abc"}, ...]`
    """
    if not isinstance(payload, dict):
        return []
    rows: List[Dict[str, str]] = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            text = json.dumps(value, ensure_ascii=False)
        else:
            text = "" if value is None else str(value)
        rows.append({"键": str(key), "值": text})
    return rows
