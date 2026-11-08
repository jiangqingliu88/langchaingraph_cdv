"""诊断条目 —— 校验与 lint 的统一产物形状。

**为什么不用异常**：一份 DSL 里可能同时有五个键拼错。抛异常只能报第一个，
使用者改一次跑一次。收集成列表一次性给出来，才是"能用的报错"。

与 `CompileError` 的分工：
  · `Issue`   —— 可以攒着一起报的（校验、lint、覆盖提示）
  · `CompileError` —— 走到这一步就没法继续的（分配无解、ref 解析不了）

这两类不混：把"分配无解"做成 Issue 会让调用方以为还能继续，
把"五个键拼错"做成异常会让使用者来回跑五趟。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

SEVERITIES = ("error", "warning", "info")


@dataclass(frozen=True)
class Issue:
    """一条诊断。`target` 是"在哪"，`fix` 是"怎么改" —— 两者缺一都难用。"""

    severity: str
    category: str                    # schema / lint / pairing / alloc / note
    rule: str                        # 机器可读的规则 id
    message: str
    target: str = ""
    fix: str = ""

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"未知的严重度 {self.severity!r}；可选：{SEVERITIES}")

    @property
    def is_error(self) -> bool:
        return self.severity == "error"

    def to_dict(self) -> Dict[str, str]:
        out = {"severity": self.severity, "category": self.category,
               "rule": self.rule, "message": self.message}
        if self.target:
            out["target"] = self.target
        if self.fix:
            out["fix"] = self.fix
        return out

    def __str__(self) -> str:
        bits = [f"[{self.severity}]", self.message]
        if self.target:
            bits.append(f"@ {self.target}")
        if self.fix:
            bits.append(f"→ {self.fix}")
        return "  ".join(bits)


def count_by_severity(issues: Iterable[Issue]) -> Dict[str, int]:
    counts = {name: 0 for name in SEVERITIES}
    for issue in issues:
        counts[issue.severity] = counts.get(issue.severity, 0) + 1
    return counts


def sort_issues(issues: Iterable[Issue]) -> List[Issue]:
    """error → warning → info；同级按 target —— 顺序稳定，结果才能 diff。

    与 VPlan 的 `sort_issues` 同一条纪律：不排序的话，同样的输入
    每次跑出来的报告顺序可能不同，diff 里全是噪声。
    """
    order = {name: index for index, name in enumerate(SEVERITIES)}
    return sorted(issues, key=lambda i: (order.get(i.severity, 99), i.target, i.rule))
