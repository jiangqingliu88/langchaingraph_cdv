"""Architecture 4.0 平面快照（Workbench / CLI 共用的只读服务）。

只做两件事：数每个平面的文件、跑一次 Architecture Guard。不执行验证、
不写文件、不调用 LLM。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class PlaneSpec:
    key: str
    dir: str
    responsibility: str
    must_not: str


PLANES: tuple[PlaneSpec, ...] = (
    PlaneSpec("Agent", "src/agent_plane",
              "理解需求、规划、生成建议、诊断、提出修复",
              "不得宣布 PASS/FAIL、不得修改预算"),
    PlaneSpec("Orchestration", "src/orchestration_plane",
              "任务分解、调度、状态机、重试、人工审批",
              "不编译、不仿真、不裁决"),
    PlaneSpec("Generation", "src/generation_plane",
              "生成 RTL / UVM / SVA / C Model / testcase 候选产物",
              "不得宣布产物正确"),
    PlaneSpec("Engine", "src/engine_plane",
              "解析、检查、编译、仿真、覆盖率、诊断、证据、签核",
              "不得调用 LLM、不得依赖 Agent"),
    PlaneSpec("IR", "src/ir_plane",
              "Intent / Execution / Evidence / Case / Resource 语义契约",
              "不执行 EDA、不持有运行时状态"),
    PlaneSpec("Knowledge", "src/knowledge_plane",
              "协议、IP、设计规范与模型/用例注册",
              "不替 Agent 做推理决策"),
    PlaneSpec("Experience", "src/experience_plane",
              "历史失败、修复记录、覆盖率闭合策略",
              "不替代 Knowledge、不驱动编排"),
    PlaneSpec("Runtime", "src/runtime_plane",
              "进程、权限、工作区、会话、EDA 环境、任务恢复",
              "不包含验证业务逻辑"),
)

INTERFACE_DIR = "src/workbench"


def _count_py(root: Path, rel: str) -> int:
    base = root / rel
    if not base.is_dir():
        return 0
    return sum(1 for p in base.rglob("*.py")
               if "__pycache__" not in p.parts and "tests" not in p.parts)


def snapshot(root: str | Path = ROOT) -> Dict[str, Any]:
    """当前平面的文件数 + Guard 结果。"""
    from config import architecture_guard as guard

    root = Path(root)
    planes: List[Dict[str, Any]] = []
    for spec in PLANES:
        planes.append({
            "key": spec.key,
            "dir": spec.dir,
            "responsibility": spec.responsibility,
            "must_not": spec.must_not,
            "files": _count_py(root, spec.dir),
            "exists": (root / spec.dir).is_dir(),
        })
    result = guard.check(root)
    return {
        "planes": planes,
        "workbench": {"dir": INTERFACE_DIR,
                      "files": _count_py(root, INTERFACE_DIR)},
        "guard": {
            "ok": bool(result.get("ok")),
            "version": result.get("tool_version", ""),
            "line_issues": result.get("line_issues") or [],
            "complexity_issues": result.get("complexity_issues") or [],
            "zone_issues": result.get("zone_issues") or [],
            "import_issues": result.get("import_issues") or [],
            "debt_issues": result.get("debt_issues") or [],
        },
    }


__all__ = ["PLANES", "PlaneSpec", "snapshot", "ROOT", "INTERFACE_DIR"]
