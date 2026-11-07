"""VPlan 项目 → **运行期 case 模型**（`inputs/casemodel.yaml`）。

项目里不再有手写的 `casemodel.yaml`；执行所需的维度/字段/断言/scoreboard
放在 VPlan 的 `data/execution_model.yaml`（执行资产），批次/测试名来自
`cases/*.yaml`（VPlan case 契约）。这里把两者合成一份**运行期派生模型**，
只写进 run 目录，不写回项目。

这不是"把旧 casemodel 藏起来"：项目输入仍是 spec-first 的 CSV + 契约矩阵；
执行资产与 case 契约是分开的两层，运行期模型是它们的确定性投影。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .source import VPlanError, VPlanProject


def load_cases(project: VPlanProject) -> List[Dict[str, Any]]:
    """`cases/TC_*.yaml`（VPlan case 契约）。"""
    out: List[Dict[str, Any]] = []
    for path in sorted((project.root / "cases").glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError) as exc:
            raise VPlanError(f"case 契约读不出来：{path}（{exc}）") from exc
        if isinstance(doc, dict) and doc.get("case_id"):
            doc["_path"] = str(path)
            out.append(doc)
    return out


def _priority(batch: str) -> str:
    text = str(batch or "").strip().upper()
    if text == "P0":
        return "P0"
    if text == "P1":
        return "P1"
    try:
        return "P0" if int(text) <= 4 else "P1"
    except ValueError:
        return "P1"


def _seed(case: Dict[str, Any], index: int) -> int:
    seeds = case.get("seed_baseline") or []
    if seeds:
        try:
            return int(seeds[0])
        except (TypeError, ValueError):
            pass
    return 1001 + index * 100


def build_execution_model(project: VPlanProject) -> Dict[str, Any]:
    """执行资产 + case 契约 → casemodel 形状（内存）。"""
    asset_path = project.root / "data" / "execution_model.yaml"
    if not asset_path.is_file():
        raise VPlanError(
            f"缺少执行资产 {asset_path}；它提供维度/字段/断言/scoreboard，"
            "不是旧的 casemodel 项目输入")
    try:
        model = yaml.safe_load(asset_path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError) as exc:
        raise VPlanError(f"执行资产读不出来：{asset_path}（{exc}）") from exc
    if not isinstance(model, dict):
        raise VPlanError(f"执行资产不是映射：{asset_path}")

    cases = load_cases(project)
    if not cases:
        raise VPlanError(f"{project.root / 'cases'} 下没有 case 契约")

    dimensions = [str(d.get("id")) for d in (model.get("dimensions") or [])
                  if isinstance(d, dict) and d.get("id")]
    themes: List[Dict[str, Any]] = []
    declared: List[Dict[str, Any]] = []
    for index, case in enumerate(cases):
        cid = str(case["case_id"])
        test = str(case.get("test_name") or "").strip()
        if not test:
            raise VPlanError(f"case {cid} 没有 test_name")
        priority = _priority(case.get("batch", ""))
        themes.append({
            "id": f"TH-{cid}",
            "test": test,
            "seeds": {"base": _seed(case, index), "count": 1, "explore": 0},
            "name": cid,
            "priority": priority,
            "description": str(case.get("title") or cid),
            "dimensions": ["*"],
            "method": "RND",
            "checks": ["CHECK-FUNC"],
        })
        declared.append({
            "id": cid,
            "tests": [test],
            # declared case 用显式维度列表（`*` 只在 theme 里展开）。
            "dimensions": dimensions,
            "requirements": list(case.get("contract_refs") or []),
            "owner": str(case.get("owner") or ""),
            "priority": priority,
            "description": str(case.get("title") or cid),
        })

    model["themes"] = themes
    # `cases` 段必须是 dict（`{cases: [...]}`），list 会被 loader 静默忽略。
    model["cases"] = {"cases": declared}
    model.setdefault("generation", {})
    model["generation"].setdefault("seed", 12345)
    model["generation"].setdefault("max_cases", 400)
    return model


def write_execution_model(project: VPlanProject,
                          run_dir: str | Path) -> Path:
    """把派生模型写到 `<run>/inputs/casemodel.yaml`（运行期产物，不写回项目）。"""
    from src.core.runtime.atomic import atomic_write_text

    model = build_execution_model(project)
    path = Path(run_dir) / "inputs" / "casemodel.yaml"
    atomic_write_text(path, yaml.safe_dump(model, allow_unicode=True,
                                           sort_keys=False))
    return path
