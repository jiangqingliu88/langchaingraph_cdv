"""bootstrap 产物的格式/引用校验。

LLM 抽表是概率性的：字段少了、id 重了、TP 引用了不存在的 case —— 这些错误如果
流进内核，表现会变成"覆盖率 0 / gate 全 blocked"，很难回溯到输入。这里在
bootstrap 落盘后立刻按参考项目（`D:\\vplan\\demo\\docs\\specs\\*.csv`）的表头与
引用关系做一次硬校验，不通过就抛 `ProjectFormatError`。

校验分两级：

- **errors**：表头不符、id 为空/重复、引用断裂、状态非法、spec hash 不符 ——
  这些会让内核读出一棵错树，必须拦住；
- **warnings**：优先级/描述缺失之类，可信但建议人工看一眼。
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Sequence

TOPICS = ("接口", "时钟复位", "参数和配置", "数据值域", "数据形状",
          "错误异常", "中间复位", "边界", "流控和反压", "性能长稳")
FIELDS = {
    "requirements": ("req_id", "spec_section", "description", "feature_ids",
                     "priority", "notes"),
    "features": ("feature_no", "feature_id", "feature_level",
                 "parent_feature_id", "feature_l1", "feature_l2",
                 "feature_l3", "description", "applicable_topics"),
    "topics": ("topic", "applicability", "reason"),
    "contracts": ("contract_id", "category", "content", "check_method",
                  "gate", "spec_ref", "status"),
    "testpoints": ("tp_id", "feature_id", "topic", "spec_ref",
                   "contract_id", "test_point", "stimulus", "expected",
                   "check_method", "case_plan", "priority", "status",
                   "notes"),
    "cases": ("case_id", "test_name", "batch", "contract_ids",
              "covergroups", "checks", "owner", "status", "notes"),
}
MATRIX_FIELDS = ("contract_id", "class", "object", "description",
                 "source_ref", "owner", "p_level", "check_method",
                 "check_artifact", "gate", "status", "assumption", "remark")
CLASS_NAMES = ("cfg", "data", "dbg", "exc", "func", "if", "lp", "perf", "res")
_TP_STATUS = {"planned", "covered", "blocked"}
_CASE_STATUS = {"planned", "covered", "blocked"}
_CONTRACT_STATUS = {"assume", "active"}
_CANDIDATE_STATUS = {"assume", "active", "已转 assume"}


class ProjectFormatError(ValueError):
    """bootstrap 产物不满足 VPlan 表格式/引用约束。"""


def _read_csv(path: Path) -> tuple[List[str], List[Dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        header = list(reader.fieldnames or [])
        return header, [dict(row) for row in reader]


def _split(value: Any) -> List[str]:
    text = str(value or "")
    for sep in ("|", ",", ";", " "):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.splitlines() if x.strip()]


def _spec_prefix(spec_dir: Path) -> str:
    metas = sorted(spec_dir.glob("*_spec_meta.json"))
    return metas[0].stem[: -len("_spec_meta")] if metas else ""


def _check_header(name: str, header: Sequence[str], errors: List[str]) -> None:
    expected = list(FIELDS[name])
    if header != expected:
        errors.append(
            f"{name}.csv 表头不符：实际 {header}，应为 {expected}")


def _check_spec(spec_dir: Path, prefix: str, errors: List[str]) -> None:
    spec = spec_dir / f"{prefix}.md"
    meta_path = spec_dir / f"{prefix}_spec_meta.json"
    if not meta_path.is_file():
        errors.append(f"缺少 spec_meta：{meta_path}")
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        errors.append(f"spec_meta 不是合法 JSON：{exc}")
        return
    if not spec.is_file():
        errors.append(f"缺少源 spec：{spec}")
        return
    actual = hashlib.sha256(spec.read_bytes()).hexdigest()
    if str(meta.get("spec_hash") or "") != actual:
        errors.append(f"spec hash 不符：meta={meta.get('spec_hash')} 实际={actual}")


def _check_ids(name: str, rows: List[Dict[str, str]], key: str,
               errors: List[str]) -> Dict[str, Dict[str, str]]:
    out: Dict[str, Dict[str, str]] = {}
    for idx, row in enumerate(rows, start=2):
        value = str(row.get(key) or "").strip()
        if not value:
            errors.append(f"{name}.csv 第 {idx} 行 {key} 为空")
            continue
        if value in out:
            errors.append(f"{name}.csv {key} 重复：{value}")
        out[value] = row
    return out


def _check_features(rows, feature_ids, errors, warnings) -> None:
    topic_set = set(TOPICS)
    for fid, row in feature_ids.items():
        level = str(row.get("feature_level") or "")
        if level not in {"root", "branch", "leaf"}:
            errors.append(f"feature {fid} 的 feature_level 非法：{level!r}")
        parent = str(row.get("parent_feature_id") or "").strip()
        if level == "root" and parent not in ("-", ""):
            errors.append(f"root feature {fid} 的 parent 应为 '-'，实际 {parent!r}")
        if level != "root" and parent not in feature_ids:
            errors.append(f"feature {fid} 的 parent 不存在：{parent!r}")
        unknown = [t for t in _split(row.get("applicable_topics"))
                   if t not in topic_set]
        if unknown:
            errors.append(f"feature {fid} 引用了未知专题：{unknown}")
        if not str(row.get("description") or "").strip():
            warnings.append(f"feature {fid} 没有 description")


def _check_requirements(rows, feature_ids, errors) -> None:
    for idx, row in enumerate(rows, start=2):
        if not str(row.get("description") or "").strip():
            errors.append(f"requirements.csv 第 {idx} 行 description 为空")
        missing = [f for f in _split(row.get("feature_ids"))
                   if f not in feature_ids]
        if missing:
            errors.append(f"requirements.csv 第 {idx} 行引用了未知 feature：{missing}")


def _check_topics(rows, errors) -> None:
    seen = set()
    for row in rows:
        topic = str(row.get("topic") or "").strip()
        if topic not in TOPICS:
            errors.append(f"topics.csv 出现非标准专题：{topic!r}")
        if topic in seen:
            errors.append(f"topics.csv 专题重复：{topic}")
        seen.add(topic)
    if len(seen) != len(TOPICS):
        errors.append(f"topics.csv 应包含 {len(TOPICS)} 个专题，实际 {len(seen)}")


def _check_contracts(rows, contract_ids, errors) -> None:
    for cid, row in contract_ids.items():
        if not cid.startswith("C-"):
            errors.append(f"contract_id 应以 C- 开头：{cid}")
        if not str(row.get("content") or "").strip():
            errors.append(f"contract {cid} 的 content 为空")
        status = str(row.get("status") or "")
        if status not in _CANDIDATE_STATUS:
            errors.append(f"contract {cid} 的 status 非法：{status!r}")


def _check_testpoints(rows, feature_ids, contract_ids, case_ids,
                      errors) -> None:
    for idx, row in enumerate(rows, start=2):
        tp = str(row.get("tp_id") or "").strip()
        if not tp.startswith("TP"):
            errors.append(f"testpoints.csv 第 {idx} 行 tp_id 非法：{tp!r}")
        if not str(row.get("test_point") or "").strip():
            errors.append(f"testpoints.csv 第 {idx} 行 test_point 为空")
        fid = str(row.get("feature_id") or "").strip()
        if fid and fid not in feature_ids:
            errors.append(f"TP {tp} 引用未知 feature：{fid}")
        cid = str(row.get("contract_id") or "").strip()
        if cid and cid not in contract_ids:
            errors.append(f"TP {tp} 引用未知 contract：{cid}")
        case = str(row.get("case_plan") or "").strip()
        if case and case not in case_ids:
            errors.append(f"TP {tp} 引用未知 case：{case}")
        status = str(row.get("status") or "")
        if status not in _TP_STATUS:
            errors.append(f"TP {tp} 的 status 非法：{status!r}")


def _check_cases(rows, contract_ids, case_ids, errors) -> None:
    for cid, row in case_ids.items():
        if not cid.startswith("TC"):
            errors.append(f"case_id 应以 TC 开头：{cid}")
        if not str(row.get("test_name") or "").strip():
            errors.append(f"case {cid} 的 test_name 为空")
        missing = [c for c in _split(row.get("contract_ids"))
                   if c not in contract_ids]
        if missing:
            errors.append(f"case {cid} 引用未知 contract：{missing}")
        status = str(row.get("status") or "")
        if status not in _CASE_STATUS:
            errors.append(f"case {cid} 的 status 非法：{status!r}")


def _check_matrix(root: Path, contract_ids, errors) -> None:
    matrix = root / "data" / "contract_matrix"
    if not matrix.is_dir():
        errors.append(f"缺少契约矩阵目录：{matrix}")
        return
    files = sorted(matrix.glob("*.csv"))
    if not files:
        errors.append(f"契约矩阵为空：{matrix}")
    for path in files:
        header, rows = _read_csv(path)
        if header != list(MATRIX_FIELDS):
            errors.append(f"{path.name} 表头不符：实际 {header}")
            continue
        cls = path.stem
        if cls not in CLASS_NAMES:
            errors.append(f"{path.name} 的 class 文件名非法：{cls}")
        for idx, row in enumerate(rows, start=2):
            cid = str(row.get("contract_id") or "").strip()
            if cid not in contract_ids:
                errors.append(f"{path.name} 第 {idx} 行 contract_id 不在 "
                              f"contracts.csv：{cid!r}")
            if str(row.get("class") or "") != cls:
                errors.append(f"{path.name} 第 {idx} 行 class={row.get('class')!r}"
                              f" 与文件名不符")
            status = str(row.get("status") or "")
            if status not in _CONTRACT_STATUS:
                errors.append(f"{path.name} 第 {idx} 行 status 非法：{status!r}")


def validate_project_inputs(project_root: str | Path) -> Dict[str, Any]:
    """校验 bootstrap 产物；返回 `{ok, errors, warnings, counts}`。"""
    root = Path(project_root)
    spec_dir = root / "docs" / "specs"
    errors: List[str] = []
    warnings: List[str] = []
    counts: Dict[str, int] = {}
    if not spec_dir.is_dir():
        return {"ok": False, "errors": [f"缺少目录：{spec_dir}"],
                "warnings": [], "counts": {}}
    prefix = _spec_prefix(spec_dir)
    if not prefix:
        return {"ok": False, "errors": [f"找不到 *_spec_meta.json：{spec_dir}"],
                "warnings": [], "counts": {}}
    _check_spec(spec_dir, prefix, errors)

    rows: Dict[str, List[Dict[str, str]]] = {}
    for name, fields in FIELDS.items():
        path = spec_dir / f"{prefix}_{name}.csv"
        if not path.is_file():
            errors.append(f"缺少表：{path.name}")
            rows[name] = []
            continue
        header, data = _read_csv(path)
        _check_header(name, header, errors)
        rows[name] = data
        counts[name] = len(data)
        if not data:
            errors.append(f"{path.name} 为空（LLM 抽取结果不能是空表）")

    feature_ids = _check_ids("features", rows["features"], "feature_id", errors)
    _check_ids("requirements", rows["requirements"], "req_id", errors)
    contract_ids = _check_ids("contracts", rows["contracts"],
                              "contract_id", errors)
    case_ids = _check_ids("cases", rows["cases"], "case_id", errors)
    _check_ids("testpoints", rows["testpoints"], "tp_id", errors)

    _check_features(rows["features"], feature_ids, errors, warnings)
    _check_requirements(rows["requirements"], feature_ids, errors)
    _check_topics(rows["topics"], errors)
    _check_contracts(rows["contracts"], contract_ids, errors)
    _check_testpoints(rows["testpoints"], feature_ids, contract_ids,
                      case_ids, errors)
    _check_cases(rows["cases"], contract_ids, case_ids, errors)
    _check_matrix(root, contract_ids, errors)

    return {"ok": not errors, "errors": errors[:50],
            "warnings": warnings[:20], "counts": counts}


ASSET_FIELDS = {
    "execution_meta.csv": ("version", "object", "object_cn", "object_code",
                           "description", "sampling", "generation"),
    "dimensions.csv": ("dimension_id", "dimension_name", "dimension_description",
                       "dimension_sub_objects", "dimension_stimulus",
                       "field_name", "field_type", "width", "values",
                       "boundary", "cover_bins", "cover_illegal", "description",
                       "sample", "cover_id", "requirement",
                       "realization_kind", "realization_path",
                       "realization_sequence", "realization_sequences"),
    "assertions.csv": ("name", "expr", "message", "signals", "tp_bindings"),
    "scoreboards.csv": ("id", "name", "checks", "evidence", "description",
                        "rules"),
    "sub_objects.csv": ("id", "name", "code"),
    "cross_matrix.csv": ("matrix_key", "payload"),
    "behavior.csv": ("rows",),
    "config_space.csv": ("rows",),
}


def validate_execution_assets(project_root: str | Path) -> Dict[str, Any]:
    """校验 `data/*.csv` 执行资产（表头 / 维度唯一 / 元信息非空）。"""
    root = Path(project_root)
    data = root / "data"
    errors: List[str] = []
    counts: Dict[str, int] = {}
    for name, fields in ASSET_FIELDS.items():
        path = data / name
        if not path.is_file():
            errors.append(f"缺少执行资产：{name}")
            continue
        header, rows = _read_csv(path)
        if tuple(header) != tuple(fields):
            errors.append(f"{name} 表头不符：实际 {header}")
            continue
        counts[name.rsplit(".", 1)[0]] = len(rows)

    meta = _read_csv(data / "execution_meta.csv")[1] if (
        data / "execution_meta.csv").is_file() else []
    if not meta:
        errors.append("execution_meta.csv 没有数据行")
    elif not str(meta[0].get("object") or "").strip():
        errors.append("execution_meta.csv 的 object 为空")

    if (data / "dimensions.csv").is_file():
        _, dims = _read_csv(data / "dimensions.csv")
        seen = set()
        for idx, row in enumerate(dims, start=2):
            did = str(row.get("dimension_id") or "").strip()
            field = str(row.get("field_name") or "").strip()
            if not did or not field:
                errors.append(f"dimensions.csv 第 {idx} 行 dimension_id/field_name 为空")
                continue
            key = (did, field)
            if key in seen:
                errors.append(f"dimensions.csv 维度/字段重复：{did}/{field}")
            seen.add(key)
    return {"ok": not errors, "errors": errors[:30], "counts": counts}


__all__ = ["ProjectFormatError", "validate_execution_assets",
           "validate_project_inputs"]
