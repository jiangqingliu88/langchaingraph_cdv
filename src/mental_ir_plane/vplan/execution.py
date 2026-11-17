"""VPlan 项目 → **运行期执行模型**（只在内存里组装）。

项目里没有手写模型文件；执行所需的维度/字段/断言/scoreboard
放在 VPlan 的 `data/*.csv`（dimensions/assertions/scoreboards/...），
批次/测试名来自 `cases/*.yaml`（VPlan case 契约）。这里把两者合成一份
**运行期模型**，只在 temp 目录里存在，不写回项目、不落 run 的 inputs。

CSV 是契约输入；运行期结构是确定性投影，run 结束即删。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .source import VPlanError, VPlanProject


def _rows(base: Path, name: str) -> List[Dict[str, str]]:
    path = base / name
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _json(value: Any, default: Any) -> Any:
    """CSV 单元格 → 结构。JSON 优先；`{...}` / `[...]` 再按 YAML flow 解析。

    bootstrap 写 `execution_meta.csv` 的 `sampling` / `generation` 用的是
    `yaml.safe_dump(..., default_flow_style=True)` —— 形如
    `{clock: clk, dut_module: npu_sched, reset: rst_n}`，**不是合法 JSON**
    （键没引号）。只按 JSON 解析会静默得到 `{}`，于是 `sampling.dut_module`
    永远缺失、DUT 覆盖率接口与 env 检查组件一个都生成不出来。
    """
    if value is None or str(value).strip() == "":
        return default
    text = str(value).strip()
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        if text[:1] in ("{", "["):
            try:
                parsed = yaml.safe_load(text)
            except Exception:                      # noqa: BLE001 坏数据走默认值
                return default
            return default if parsed is None else parsed
        return default


def _int_or_none(value: Any) -> Any:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _field_from_row(row: Dict[str, str]) -> Dict[str, Any]:
    field: Dict[str, Any] = {"name": row.get("field_name", ""),
                             "type": row.get("field_type", "")}
    for key in ("width", "min", "max"):
        value = _int_or_none(row.get(key))
        if value is not None:
            field[key] = value
    for key in ("values", "boundary", "cover_bins", "cover_illegal"):
        value = _json(row.get(key), [])
        if value:
            field[key] = value
    for key in ("description", "sample", "cover_id", "requirement"):
        if row.get(key):
            field[key] = row[key]
    return field


def _realization_from_row(row: Dict[str, str]) -> Any:
    kind = row.get("realization_kind", "")
    if not kind:
        return None
    real: Dict[str, Any] = {"kind": kind}
    if row.get("realization_path"):
        real["path"] = row["realization_path"]
    if row.get("realization_sequence"):
        real["sequence"] = row["realization_sequence"]
    seqs = _json(row.get("realization_sequences"), {})
    if seqs:
        real["sequences"] = seqs
    return real


def _load_asset_model(root: Path) -> Dict[str, Any]:
    """从 `data/*.csv` 组装执行资产模型（只读 `data/*.csv`）。"""
    base = root / "data"
    meta_rows = _rows(base, "execution_meta.csv")
    if not meta_rows:
        raise VPlanError(
            f"缺少执行资产 {base / 'execution_meta.csv'}；"
            "VPlan 执行资产现在是 CSV（dimensions/assertions/scoreboards/...）")
    meta = meta_rows[0]
    model: Dict[str, Any] = {
        "version": meta.get("version", "1"),
        "object": meta.get("object", root.name),
        "object_cn": meta.get("object_cn", ""),
        "object_code": meta.get("object_code", ""),
        "description": meta.get("description", ""),
        "sampling": _json(meta.get("sampling"), {}),
        "generation": _json(meta.get("generation"), {}),
    }

    dims: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for row in _rows(base, "dimensions.csv"):
        did = row.get("dimension_id", "")
        if not did:
            continue
        dim = dims.get(did)
        if dim is None:
            dim = {"id": did, "name": row.get("dimension_name", ""),
                   "description": row.get("dimension_description", ""),
                   "sub_objects": _json(row.get("dimension_sub_objects"), []),
                   "fields": []}
            stimulus = _json(row.get("dimension_stimulus"), {})
            if stimulus:
                dim["stimulus"] = stimulus
            dims[did] = dim
            order.append(did)
        dim["fields"].append(_field_from_row(row))
        realization = _realization_from_row(row)
        if realization:
            dim["realization"] = realization
    model["dimensions"] = [dims[did] for did in order]

    model["assertions"] = [{
        "name": row.get("name", ""), "expr": row.get("expr", ""),
        "message": row.get("message", ""),
        "signals": _json(row.get("signals"), []),
        "tp_bindings": _json(row.get("tp_bindings"), []),
    } for row in _rows(base, "assertions.csv")]
    model["scoreboards"] = [{
        "id": row.get("id", ""), "name": row.get("name", ""),
        "checks": _json(row.get("checks"), []),
        "evidence": row.get("evidence", ""),
        "description": row.get("description", ""),
        "rules": _json(row.get("rules"), []),
    } for row in _rows(base, "scoreboards.csv")]
    model["sub_objects"] = [{
        "id": row.get("id", ""), "name": row.get("name", ""),
        "code": row.get("code", ""),
    } for row in _rows(base, "sub_objects.csv")]
    model["cross_matrix"] = {
        row["matrix_key"]: _json(row.get("payload"), {})
        for row in _rows(base, "cross_matrix.csv")
        if row.get("matrix_key")
    }
    behavior = (_rows(base, "behavior.csv") or [{}])[0]
    model["behavior"] = {k: _json(v, v) for k, v in behavior.items() if v != ""}
    config_space = (_rows(base, "config_space.csv") or [{}])[0]
    model["config_space"] = {
        k: _json(v, v) for k, v in config_space.items() if v != ""}
    return model


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
    if text in ("P0", "P1", "P2", "P3"):
        return text
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


#: VPlan 专题 → 执行模型维度（case 的批次只驱动它自己关心的维度）。
TOPIC_DIMS: Dict[str, List[str]] = {
    "接口": ["D_type", "D_dtype", "D_opcode"],
    "时钟复位": ["D_barrier"],
    "参数和配置": ["D_type", "D_opcode"],
    "数据值域": ["D_type", "D_dtype", "D_opcode", "D_priority"],
    "数据形状": ["D_seq", "D_pipeline", "D_cluster"],
    "错误异常": ["D_decision", "D_barrier"],
    "中间复位": ["D_barrier", "D_queue"],
    "边界": ["D_queue", "D_cluster"],
    "流控和反压": ["D_queue", "D_decision"],
    "性能长稳": ["D_pipeline", "D_priority"],
}


def _case_dimensions(project: VPlanProject, case_id: str,
                     all_dims: List[str]) -> List[str]:
    topics = {str(tp.get("topic") or "") for tp in project.testpoints
              if str(tp.get("case_plan") or "") == case_id}
    dims = {d for topic in topics for d in TOPIC_DIMS.get(topic, [])}
    chosen = [d for d in all_dims if d in dims]
    return chosen or list(all_dims)


def build_runtime_model(project: VPlanProject) -> Dict[str, Any]:
    """执行资产（CSV）+ case 契约 → 运行期模型（内存）。"""
    model = _load_asset_model(project.root)

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
        case_dims = _case_dimensions(project, cid, dimensions)
        themes.append({
            "id": f"TH-{cid}",
            "test": test,
            "seeds": {"base": _seed(case, index), "count": 1, "explore": 0},
            "name": cid,
            "priority": priority,
            "description": str(case.get("title") or cid),
            "dimensions": case_dims,
            "method": "RND",
            "checks": ["CHECK-FUNC"],
        })
        declared.append({
            "id": cid,
            "tests": [test],
            # declared case 用显式维度列表（`*` 只在 theme 里展开）。
            "dimensions": case_dims,
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


def write_runtime_model(project: VPlanProject,
                        run_dir: str | Path) -> Path:
    """把派生模型写到 `<dir>/inputs/runtime_model.yaml`（临时运行期产物）。"""
    from src.runtime_plane.core.runtime.atomic import atomic_write_text

    model = build_runtime_model(project)
    path = Path(run_dir) / "inputs" / "runtime_model.yaml"
    atomic_write_text(path, yaml.safe_dump(model, allow_unicode=True,
                                           sort_keys=False))
    return path


# 旧名字兼容（外部/测试还在用）；语义已是 runtime model。
build_execution_model = build_runtime_model
write_execution_model = write_runtime_model
