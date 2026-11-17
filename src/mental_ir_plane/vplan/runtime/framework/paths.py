"""PATH 组编译 —— `path_groups:` → 路径测试点（一条 bin 一条 TP）。

与 `behavior.py` 同一套主键与 IR；区别只在语义：

    迁移 / 序列 / 时序   → 行为域节点（stage=behavior）
    端到端路径 bin       → PATH 组（stage=behavior，`dimension=PATH`）

PATH TP 的 `coverpoint/bin` 直接取组声明的覆盖仓（`cp_path_<id>` / bin 名），
所以它天然进 `tp_matrix` 与 `case_tp`；执行后端（把路径序列编译成 UVM
sequence + 采样 `path_seq`）在 P1b，当前如实标 `PENDING_BACKEND`。
"""
from __future__ import annotations

from typing import List

from .model import Execution, Realization, TestPoint, Timing
from .naming import derive_code, unique_tp_id

KIND_SEQUENCE = "sequence"
_PATH_NOTE = ("PATH 组：按指令生命周期建模的端到端路径；执行后端（序列 → UVM + "
              "path_seq 采样）在 P1b，当前只进 IR / 证据视图")


def _slug(text: str) -> str:
    out = "".join(ch if ch.isalnum() else "_" for ch in str(text or "")).strip("_")
    return out.upper() or "PATH"


def compile_paths(model) -> List[TestPoint]:
    """`CaseModel.path_groups` → PATH 测试点。没有 PATH 组返回空列表。"""
    groups = getattr(model, "path_groups", None) or []
    if not groups:
        return []
    code = (getattr(model, "object_code", "") or derive_code(model.object)
            or "OBJ")
    used: set = set()
    out: List[TestPoint] = []
    for group in groups:
        for bin_ in getattr(group, "bins", []) or []:
            raw = f"TP-{code}-PATH-{_slug(bin_.name)}"
            tp_id = unique_tp_id(raw, used)
            timing = Timing.from_dict(bin_.timing) if bin_.timing else None
            out.append(TestPoint(
                tp_id=tp_id,
                object=str(getattr(model, "object", "")),
                dimension="PATH",
                dimension_name=getattr(group, "name", "") or group.id,
                value=bin_.name,
                requirement=bin_.requirement,
                coverpoint=group.cp_name,
                bin=bin_.name,
                checks=list(bin_.checks),
                realization=Realization(
                    kind=KIND_SEQUENCE,
                    sequence=" > ".join(bin_.sequence),
                ),
                execution=Execution(stage="behavior"),
                timing=timing,
                notes=[_PATH_NOTE],
            ))
    return out
