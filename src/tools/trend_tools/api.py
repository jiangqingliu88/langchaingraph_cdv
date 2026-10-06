"""进度趋势工具的程序化接口 —— 读一份 YAML 进度模型，吐可绘制的序列。

只有一个函数 `run_trend(path)`。它做三件事：

  1. 把每个阶段按 `kind` 归一成一个可绘制的进度值 ——
     `build` → 累计 build 数；`loop` → 覆盖率 %；`test` → 通过率 %。
  2. 按量纲分成两组序列：`build_series`（次数，量纲随数据走）与
     `test_series`（百分比，0–100 同轴）。界面据此分两个面板画。
  3. 给一张 `summary`（每阶段最新值 + 通过/总数/通过率），把 build 数量
     显式列出来 —— 图看趋势，表看当前值。

失败**响亮**（与全仓库一致）：没有路径 / 文件不在 / YAML 坏 / 顶层不是映射
一律返回 `{"error": "...（怎么修）"}` 而不是抛异常。**某轮里出现了 stages
没声明的 id 不丢轮**：记进 `unresolved`，照常返回其它数据。

返回值一律是 **dict**，不是 JSON 字符串。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

#: 阶段类型 → 它代表什么量。写在数据里（`kind:`），工具据此选进度口径。
KIND_BUILD = "build"   # 累计构建/编译次数
KIND_LOOP = "loop"     # 仿真循环（覆盖率收敛）
KIND_TEST = "test"     # 按优先级的测试通过率
KINDS = (KIND_BUILD, KIND_LOOP, KIND_TEST)


def run_trend(path: str = "") -> Dict[str, Any]:
    """trend.yaml → 进度趋势的序列与汇总。

    返回：`{"project", "stages", "rounds", "build_series", "test_series",
             "summary", "unresolved", "counts"}`
    """
    if not isinstance(path, str) or not path.strip():
        return {"error": "没有给 trend.yaml 的路径"}

    target = Path(path)
    if not target.exists():
        return {"error": f"找不到进度模型文件：{target}"
                         f"（清单里模块的 `input:` 指向它，相对清单目录解析）"}
    if target.is_dir():
        return {"error": f"进度模型路径是一个目录而不是文件：{target}"}

    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"读不了进度模型 {target}：{exc}"}

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return {"error": f"进度模型 YAML 解析失败：{exc}"}

    if data is None:
        return {"error": f"进度模型是空的：{target}"}
    if not isinstance(data, dict):
        return {"error": "进度模型顶层必须是一个映射（要有 project / stages / rounds）"}

    stages = _normalize_stages(data.get("stages"))
    if not stages:
        return {"error": "进度模型里没有 stages —— 至少要声明一个阶段"}

    rounds_raw = data.get("rounds") or []
    if not isinstance(rounds_raw, list):
        return {"error": "`rounds` 必须是一个列表（每项一轮）"}

    known = {s["id"] for s in stages}
    round_numbers: List[int] = []
    #: stage_id → [(round, value)]，按轮次顺序追加
    points: Dict[str, List[List[Any]]] = {s["id"]: [] for s in stages}
    latest: Dict[str, Any] = {}
    unresolved: List[Dict[str, Any]] = []

    for index, entry in enumerate(rounds_raw):
        if not isinstance(entry, dict):
            continue
        round_no = _as_int(entry.get("round"), default=index + 1)
        round_numbers.append(round_no)

        for key, cell in entry.items():
            if key == "round":
                continue
            if key not in known:
                unresolved.append({"round": round_no, "stage": key})
                continue
            if not isinstance(cell, dict):
                # 允许 `p0: 3/6` 这种简写？不 —— 保持一种写法，含糊的输入别猜
                unresolved.append({"round": round_no, "stage": key})
                continue
            stage = next(s for s in stages if s["id"] == key)
            value = _value_of(stage["kind"], cell)
            if value is None:
                continue                      # 这轮这个阶段还没数据 —— 不画 0
            points[key].append([round_no, value])
            latest[key] = cell

    build_series = [{"id": s["id"], "title": s["title"], "points": points[s["id"]]}
                    for s in stages if s["kind"] == KIND_BUILD and points[s["id"]]]
    test_series = [{"id": s["id"], "title": s["title"], "points": points[s["id"]]}
                   for s in stages if s["kind"] in (KIND_LOOP, KIND_TEST)
                   and points[s["id"]]]

    return {
        "project": str(data.get("project", "") or ""),
        "stages": stages,
        "rounds": round_numbers,
        "build_series": build_series,
        "test_series": test_series,
        "summary": _summarise(stages, latest),
        "unresolved": unresolved,
        "counts": {
            "rounds": len(round_numbers),
            "builds_total": sum(int(latest.get(s["id"], {}).get("build", 0) or 0)
                                for s in stages if s["kind"] == KIND_BUILD),
        },
    }


# ════════════════════════════════════════════════════════════════
# 归一化
# ════════════════════════════════════════════════════════════════

def _normalize_stages(raw: Any) -> List[Dict[str, str]]:
    """stages 列表 → [{id, title, kind}]。未知 kind 归到 build（保守：不猜成百分比）。"""
    stages: List[Dict[str, str]] = []
    for index, entry in enumerate(raw or []):
        if not isinstance(entry, dict):
            continue
        stage_id = str(entry.get("id", "") or "")
        if not stage_id:
            continue
        kind = str(entry.get("kind", KIND_BUILD) or KIND_BUILD)
        if kind not in KINDS:
            kind = KIND_BUILD
        stages.append({"id": stage_id,
                       "title": str(entry.get("title", "") or stage_id),
                       "kind": kind})
    return stages


def _value_of(kind: str, cell: Dict[str, Any]) -> Optional[float]:
    """一个阶段的某轮取值 → 画在 y 轴上的数。没写关键字段就返回 None（不画）。"""
    if kind == KIND_BUILD:
        if "build" not in cell:
            return None
        return float(_as_int(cell.get("build"), default=0))
    if kind == KIND_LOOP:
        if "coverage" not in cell:
            return None
        return round(_as_float(cell.get("coverage")), 1)
    # test：通过率 %
    total = _as_int(cell.get("total"), default=0)
    if "passed" not in cell and "total" not in cell:
        return None
    passed = _as_int(cell.get("passed"), default=0)
    return round(passed / total * 100, 1) if total > 0 else 0.0


def _summarise(stages: List[Dict[str, str]],
               latest: Dict[str, Any]) -> List[Dict[str, Any]]:
    """每阶段**最新一轮**的值 → 一行汇总。没数据的阶段给空行，不丢。"""
    rows: List[Dict[str, Any]] = []
    for stage in stages:
        cell = latest.get(stage["id"])
        row: Dict[str, Any] = {"stage": stage["id"], "title": stage["title"],
                               "kind": stage["kind"], "value": "", "passed": "",
                               "total": "", "pct": ""}
        if isinstance(cell, dict):
            if stage["kind"] == KIND_BUILD:
                row["value"] = str(_as_int(cell.get("build"), default=0))
            elif stage["kind"] == KIND_LOOP:
                cov = _as_float(cell.get("coverage"))
                row["value"] = f"{round(cov, 1)}%"
                row["pct"] = f"{round(cov, 1)}%"
            else:
                total = _as_int(cell.get("total"), default=0)
                passed = _as_int(cell.get("passed"), default=0)
                pct = f"{round(passed / total * 100, 1)}%" if total > 0 else "0%"
                # 「最新值」口径与图上那条线一致 = 通过率；通过/总数是原始数
                row["value"] = pct
                row["passed"] = str(passed)
                row["total"] = str(total)
                row["pct"] = pct
        rows.append(row)
    return rows


def _as_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
