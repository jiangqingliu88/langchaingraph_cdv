"""VPlan 项目源数据 —— `docs/specs/*.csv` + `data/contract_matrix/*.csv`。

只读、零副作用。所有状态都按文件原样保留：契约 `assume` 不会因为被读进来
就升成 `active`，测试点 `planned` 也不会因为生成了 IR 就变成 `covered`。
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

#: 专题中文名 → ASCII 维度码（TP IR 的 dimension 不能用中文拼 ID）。
TOPIC_CODES: Dict[str, str] = {
    "接口": "IF",
    "时钟复位": "RST",
    "参数和配置": "CFG",
    "数据值域": "DATA",
    "数据形状": "SHAPE",
    "错误异常": "EXC",
    "中间复位": "MRST",
    "边界": "BOUND",
    "流控和反压": "FLOW",
    "性能长稳": "PERF",
}

#: 契约矩阵的 13 列 —— 读进来时按顺序保留，写回时不做二次映射。
MATRIX_COLUMNS = (
    "contract_id", "class", "object", "description", "source_ref", "owner",
    "p_level", "check_method", "check_artifact", "gate", "status",
    "assumption", "remark",
)

#: 由候选抽取表带进矩阵的补充字段（矩阵本身没有这几列）。
CANDIDATE_FIELDS = ("category", "content", "candidate_status")

#: 矩阵状态只能是这三类；其余值一律拒绝，避免手改 CSV 造出“看起来合法”的状态。
MATRIX_STATUSES = ("assume", "active", "exempt")


class VPlanError(ValueError):
    """VPlan 项目输入不成立（缺文件 / hash 不符 / 引用断裂）。"""


@dataclass
class VPlanProject:
    """一个 spec-first 项目根的只读快照。"""

    root: Path
    module: str
    dut: str
    spec_dir: Path
    spec_path: Path
    spec_hash: str
    spec_meta: Dict[str, Any]
    requirements: List[Dict[str, Any]] = field(default_factory=list)
    features: List[Dict[str, Any]] = field(default_factory=list)
    topics: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    contracts: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    testpoints: List[Dict[str, Any]] = field(default_factory=list)
    cases: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def status_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in self.contracts.values():
            status = str(row.get("status") or "unknown")
            out[status] = out.get(status, 0) + 1
        return out

    @property
    def tp_status_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in self.testpoints:
            status = str(row.get("status") or "unknown")
            out[status] = out.get(status, 0) + 1
        return out

    @property
    def case_status_counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in self.cases:
            status = str(row.get("status") or "unknown")
            out[status] = out.get(status, 0) + 1
        return out


def _read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_root(project: str | Path) -> Path:
    path = Path(project)
    if path.is_dir():
        return path
    alternative = Path("specs") / str(project)
    if alternative.is_dir():
        return alternative
    raise VPlanError(f"VPlan 项目目录不存在：{project}")


def _find_prefix(spec_dir: Path) -> str:
    metas = sorted(spec_dir.glob("*_spec_meta.json"))
    if metas:
        return metas[0].stem[: -len("_spec_meta")]
    tps = sorted(spec_dir.glob("*_testpoints.csv"))
    if tps:
        return tps[0].stem[: -len("_testpoints")]
    raise VPlanError(f"{spec_dir} 下找不到 *_spec_meta.json / *_testpoints.csv")


def _load_meta(spec_dir: Path, prefix: str) -> Dict[str, Any]:
    path = spec_dir / f"{prefix}_spec_meta.json"
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise VPlanError(f"spec_meta 读不出来：{path}（{exc}）") from exc
    return doc if isinstance(doc, dict) else {}


def _spec_path(root: Path, spec_dir: Path, prefix: str,
               meta: Dict[str, Any]) -> Path:
    source = str(meta.get("source") or "").strip()
    if source:
        candidate = Path(source)
        if not candidate.is_absolute():
            candidate = root / candidate
        if candidate.is_file():
            return candidate
    fallback = spec_dir / f"{prefix}.md"
    if fallback.is_file():
        return fallback
    raise VPlanError(f"找不到源 spec（meta.source={source!r}，"
                     f"fallback={fallback}）")


def _load_matrix(root: Path) -> Dict[str, Dict[str, Any]]:
    matrix_dir = root / "data" / "contract_matrix"
    if not matrix_dir.is_dir():
        raise VPlanError(f"缺少权威契约矩阵目录：{matrix_dir}")
    required = set(MATRIX_COLUMNS)
    rows: Dict[str, Dict[str, Any]] = {}
    for path in sorted(matrix_dir.glob("*.csv")):
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            fields = set(reader.fieldnames or [])
            missing = sorted(required - fields)
            if missing:
                raise VPlanError(
                    f"契约矩阵列不齐：{path} 缺 {missing}；"
                    f"权威矩阵必须是 {len(MATRIX_COLUMNS)} 列")
            for row in reader:
                cid = str(row.get("contract_id") or "").strip()
                if not cid:
                    continue
                if cid in rows:
                    raise VPlanError(f"契约矩阵里 contract_id 重复：{cid}")
                status = str(row.get("status") or "assume").strip()
                if status not in MATRIX_STATUSES:
                    raise VPlanError(
                        f"契约 {cid} 的 status={status!r} 不在 "
                        f"{MATRIX_STATUSES}；手改状态不等于证据")
                rows[cid] = row
    if not rows:
        raise VPlanError(f"契约矩阵为空：{matrix_dir}")
    return rows


def _merge_candidates(contracts: Dict[str, Dict[str, Any]],
                      candidates: List[Dict[str, Any]]) -> None:
    """把候选表的 spec_ref/内容补进矩阵行；**不改矩阵权威字段**。"""
    index = {str(c.get("contract_id") or ""): c for c in candidates}
    for cid, row in contracts.items():
        candidate = index.get(cid) or {}
        if candidate:
            row.setdefault("category", candidate.get("category", ""))
            row.setdefault("content", candidate.get("content", ""))
            row.setdefault("candidate_status", candidate.get("status", ""))
        # 矩阵没有 spec_ref 时，用候选表的来源补；矩阵有就尊重矩阵。
        if not str(row.get("source_ref") or "").strip():
            row["source_ref"] = candidate.get("spec_ref", "")


def _validate(project: VPlanProject) -> None:
    case_ids = {str(c.get("case_id") or "") for c in project.cases}
    for tp in project.testpoints:
        tp_id = str(tp.get("tp_id") or "")
        cid = str(tp.get("contract_id") or "").strip()
        if cid and cid not in project.contracts:
            project.warnings.append(f"TP {tp_id} 引用了矩阵里没有的契约 {cid}")
        case_id = str(tp.get("case_plan") or "").strip()
        if case_id and case_id not in case_ids:
            project.warnings.append(f"TP {tp_id} 的 case_plan {case_id} 不在 cases.csv")
    for case in project.cases:
        for cid in _split_ids(case.get("contract_ids")):
            if cid not in project.contracts:
                project.warnings.append(
                    f"case {case.get('case_id')} 引用了矩阵里没有的契约 {cid}")


def _split_ids(value: Any) -> List[str]:
    text = str(value or "")
    for sep in ("|", ",", ";", " "):
        text = text.replace(sep, "\n")
    return [x.strip() for x in text.splitlines() if x.strip()]


def load_project(project: str | Path, *,
                 allow_spec_drift: bool = False) -> VPlanProject:
    """读一个 VPlan 项目根（`specs/<module>/`）并做引用校验。

    `allow_spec_drift=True` 只用于预览：spec 与 `spec_hash` 不符时继续读，
    但会写一条 warning；正式生成应保持 False。
    """
    root = _resolve_root(project).resolve()
    spec_dir = root / "docs" / "specs"
    if not spec_dir.is_dir():
        raise VPlanError(f"缺少 docs/specs：{spec_dir}")
    prefix = _find_prefix(spec_dir)
    meta = _load_meta(spec_dir, prefix)
    spec_path = _spec_path(root, spec_dir, prefix, meta)

    actual_hash = _sha256(spec_path)
    expected_hash = str(meta.get("spec_hash") or "").strip()
    if expected_hash and actual_hash != expected_hash:
        msg = (f"spec hash 不符：{spec_path} 实际 {actual_hash[:12]}… / "
               f"meta {expected_hash[:12]}…")
        if not allow_spec_drift:
            raise VPlanError(msg + "（先更新抽取表与 spec_meta；预览可用 --allow-spec-drift）")

    requirements = _read_csv(spec_dir / f"{prefix}_requirements.csv")
    features = _read_csv(spec_dir / f"{prefix}_features.csv")
    topics = _read_csv(spec_dir / f"{prefix}_topics.csv")
    candidates = _read_csv(spec_dir / f"{prefix}_contracts.csv")
    testpoints = _read_csv(spec_dir / f"{prefix}_testpoints.csv")
    cases = _read_csv(spec_dir / f"{prefix}_cases.csv")
    contracts = _load_matrix(root)
    _merge_candidates(contracts, candidates)

    dut = ""
    for feature in features:
        dut = str(feature.get("feature_l1") or "").strip()
        if dut:
            break
    project_obj = VPlanProject(
        root=root,
        module=root.name,
        dut=dut or root.name.upper(),
        spec_dir=spec_dir,
        spec_path=spec_path,
        spec_hash=actual_hash,
        spec_meta=meta,
        requirements=requirements,
        features=features,
        topics=topics,
        candidates=candidates,
        contracts=contracts,
        testpoints=testpoints,
        cases=cases,
    )
    _validate(project_obj)
    return project_obj


def feature_paths(features: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """`feature_id → l1/l2/l3` 路径（读 features.csv 的现成列）。"""
    out: Dict[str, str] = {}
    for row in features:
        fid = str(row.get("feature_id") or "").strip()
        if not fid:
            continue
        parts = [str(row.get(k) or "").strip()
                 for k in ("feature_l1", "feature_l2", "feature_l3")]
        out[fid] = "/".join(p for p in parts if p)
    return out
