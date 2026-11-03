"""PATH 组 —— **按指令生命周期切**的端到端路径覆盖（不是功能组）。

## 为什么功能组 100% 不等于路径通

功能组回答"每个功能契约的取值/场景打没打到"；一条完整指令从 `cmd_hs` 到
`rsp` 的生命周期，可能由多个功能组的 bin **分别**命中，但**没有任何一处**
记录"这些 bin 是在同一条路径上、按正确顺序发生"。所以 PATH 组单独建模：

    path_groups:
      - id: CG_CMDSCHED_PATH
        name: 端到端指令路径
        sample: path_seq                 # UVM 里那个路径枚举/序号
        coverpoint: cp_path_issue_lifecycle
        bins:
          - name: direct_full
            sequence: [cmd_hs, no_dep, direct, start, done, rls, rsp]
            checks: [SVA-START-DONE-ID, SCB-RSP-DATA]
            requirement: Feat-10
            timing: {expect_cycles: {min: 2, max: 12},
                     start: cmd_valid, end: rsp_valid}

每个 bin 是一条路径（阶段序列），`checks` 列出**这条路径必须同时绑定的
SVA / scoreboard 检查项** —— PATH 组负责"路径走通"，checker 负责"走通且走对"。

第一阶段（P1b 前）只进 TP IR 与证据视图：`execution.stage = "behavior"`，
如实标 `PENDING_BACKEND`，不冒充可执行、也不从覆盖率分母里消失。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


@dataclass
class PathBin:
    """一条端到端路径（阶段序列 + 绑定的检查项）。"""
    name: str
    sequence: List[str] = field(default_factory=list)
    checks: List[str] = field(default_factory=list)
    description: str = ""
    requirement: str = ""
    #: 可选时序窗口（与 `framework.model.Timing` 同形）。
    timing: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["PathBin"]:
        if not isinstance(raw, dict):
            return None
        name = str(raw.get("name") or "").strip()
        if not name:
            return None
        return cls(
            name=name,
            sequence=[str(s) for s in _as_list(raw.get("sequence")) if str(s)],
            checks=[str(c) for c in _as_list(raw.get("checks")) if str(c)],
            description=str(raw.get("description") or ""),
            requirement=str(raw.get("requirement") or ""),
            timing=dict(raw.get("timing") or {})
            if isinstance(raw.get("timing"), dict) else {},
        )

    def to_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "sequence": list(self.sequence),
               "checks": list(self.checks)}
        if self.description:
            out["description"] = self.description
        if self.requirement:
            out["requirement"] = self.requirement
        if self.timing:
            out["timing"] = dict(self.timing)
        return out


@dataclass
class PathGroup:
    """一组端到端路径（一条 = 一个 PATH bin，对应一条 TP）。"""
    id: str
    name: str = ""
    sample: str = "path_seq"
    coverpoint: str = ""
    #: 这条路径**经过的功能组**（与 `dimension_name` 同名）—— 矩阵视图用它
    #: 决定"组 × 路径"的格子该不该有证据；空 = 不限制（按维度自动推断）。
    groups: List[str] = field(default_factory=list)
    bins: List[PathBin] = field(default_factory=list)

    @property
    def cp_name(self) -> str:
        """SV 里那个 coverpoint 名（作者给了就用作者的）。"""
        return self.coverpoint or f"cp_path_{self.id}"

    @classmethod
    def from_dict(cls, raw: Any, index: int = 1) -> Optional["PathGroup"]:
        if not isinstance(raw, dict):
            return None
        gid = str(raw.get("id") or raw.get("name") or f"PATH{index}").strip()
        if not gid:
            return None
        bins = [b for b in (PathBin.from_dict(x)
                            for x in _as_list(raw.get("bins"))) if b is not None]
        if not bins:
            return None
        return cls(id=gid, name=str(raw.get("name") or gid),
                   sample=str(raw.get("sample") or "path_seq"),
                   coverpoint=str(raw.get("coverpoint") or ""),
                   groups=[str(g) for g in _as_list(raw.get("groups")) if str(g)],
                   bins=bins)

    def to_dict(self) -> Dict[str, Any]:
        out = {"id": self.id, "name": self.name, "sample": self.sample,
               "coverpoint": self.cp_name,
               "bins": [b.to_dict() for b in self.bins]}
        if self.groups:
            out["groups"] = list(self.groups)
        return out
