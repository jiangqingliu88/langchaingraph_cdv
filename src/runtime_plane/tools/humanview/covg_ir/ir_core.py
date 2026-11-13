"""功能覆盖率纵横矩阵 IR —— **声明**，不是命中。

形状对应 `arch.md`：

    covergroups  纵向：功能契约切组（CG / CP / BIN / 组内交叉 / 约束 / 矩阵归属）
    paths        横向：生命周期路径（阶段序列 / 绑定 SVA / SB / 定向序列）
    crosses      跨组交叉（实现方式 / 验证意图 / 绑定 checker）

`status` 只做结构判定：`未覆盖 / 已覆盖 / 已签核`。真正的命中率来自 ucdb，
不在这份 IR 里伪造。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..ir_common import as_list, norm_id, norm_ids, refs


def _bins(raw: Any, illegal: bool = False) -> List["BinIR"]:
    """两种写法都认：`[{name, value}]` 与 `{bin_name: value}`。"""
    if isinstance(raw, dict):
        return [BinIR(name=str(name), value=value, illegal=illegal)
                for name, value in raw.items() if str(name).strip()]
    out: List[BinIR] = []
    for item in as_list(raw):
        b = BinIR.from_dict(item, illegal=illegal)
        if b is not None:
            out.append(b)
    return out


@dataclass
class BinIR:
    name: str
    value: Any = None
    illegal: bool = False
    ignore_reason: str = ""

    @classmethod
    def from_dict(cls, raw: Any, illegal: bool = False) -> Optional["BinIR"]:
        if isinstance(raw, dict):
            name = norm_id(raw.get("name") or raw.get("id") or raw.get("value"))
            if not name:
                return None
            return cls(name=name, value=raw.get("value"),
                       illegal=illegal or bool(raw.get("illegal")),
                       ignore_reason=str(raw.get("reason") or ""))
        name = norm_id(raw)
        return cls(name=name, value=raw, illegal=illegal) if name else None

    def to_dict(self) -> Dict[str, Any]:
        out = {"name": self.name, "value": self.value}
        if self.illegal:
            out["illegal"] = True
        if self.ignore_reason:
            out["reason"] = self.ignore_reason
        return out


@dataclass
class CoverpointIR:
    id: str
    name: str
    signal: str
    iff: str = ""
    bins: List[BinIR] = field(default_factory=list)
    illegal_bins: List[BinIR] = field(default_factory=list)
    matrix_rows: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["CoverpointIR"]:
        if not isinstance(raw, dict):
            return None
        cid = norm_id(raw.get("id") or raw.get("name"))
        name = norm_id(raw.get("name") or cid)
        if not cid or not name:
            return None
        return cls(id=cid, name=name,
                   signal=norm_id(raw.get("signal") or name),
                   iff=str(raw.get("iff") or ""),
                   bins=_bins(raw.get("bins")),
                   illegal_bins=_bins(raw.get("illegal_bins"), illegal=True),
                   matrix_rows=norm_ids(raw.get("matrix_rows")))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "signal": self.signal,
                "iff": self.iff, "bins": [b.to_dict() for b in self.bins],
                "illegal_bins": [b.to_dict() for b in self.illegal_bins],
                "matrix_rows": list(self.matrix_rows)}


@dataclass
class IntraCrossIR:
    id: str
    objects: List[str] = field(default_factory=list)
    bins: List[BinIR] = field(default_factory=list)
    ignore_bins: List[BinIR] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["IntraCrossIR"]:
        if not isinstance(raw, dict):
            return None
        cid = norm_id(raw.get("id") or raw.get("name"))
        objects = norm_ids(raw.get("objects"))
        if not cid or len(objects) < 2:
            return None
        return cls(id=cid, objects=objects,
                   bins=_bins(raw.get("bins")),
                   ignore_bins=_bins(raw.get("ignore_bins")))

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "objects": list(self.objects),
                "bins": [b.to_dict() for b in self.bins],
                "ignore_bins": [b.to_dict() for b in self.ignore_bins]}


@dataclass
class ConstraintIR:
    name: str
    klass: str = ""
    targets: List[str] = field(default_factory=list)
    method: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["ConstraintIR"]:
        if not isinstance(raw, dict):
            return None
        name = norm_id(raw.get("name") or raw.get("id"))
        if not name:
            return None
        return cls(name=name, klass=str(raw.get("class") or raw.get("klass") or ""),
                   targets=norm_ids(raw.get("targets")),
                   method=str(raw.get("method") or ""))

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "class": self.klass,
                "targets": list(self.targets), "method": self.method}


@dataclass
class CovergroupIR:
    id: str
    name: str = ""
    requirements: List[str] = field(default_factory=list)
    description: str = ""
    sampling_domain: str = ""
    coverpoints: List[CoverpointIR] = field(default_factory=list)
    intra_cross: List[IntraCrossIR] = field(default_factory=list)
    constraints: List[ConstraintIR] = field(default_factory=list)
    matrix_rows: List[str] = field(default_factory=list)
    evidence_sva: List[str] = field(default_factory=list)
    evidence_scb: List[str] = field(default_factory=list)
    target: Dict[str, Any] = field(default_factory=dict)
    status: str = "未覆盖"
    owner: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["CovergroupIR"]:
        if not isinstance(raw, dict):
            return None
        gid = norm_id(raw.get("group_id") or raw.get("id"))
        if not gid:
            return None
        evidence = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
        return cls(
            id=gid, name=norm_id(raw.get("name") or gid),
            requirements=norm_ids(raw.get("requirements") or raw.get("feats")),
            description=str(raw.get("description") or ""),
            sampling_domain=norm_id(raw.get("sampling_domain")),
            coverpoints=[c for c in (CoverpointIR.from_dict(x)
                                     for x in as_list(raw.get("coverpoints")))
                         if c is not None],
            intra_cross=[c for c in (IntraCrossIR.from_dict(x)
                                     for x in as_list(raw.get("intra_cross")))
                         if c is not None],
            constraints=[c for c in (ConstraintIR.from_dict(x)
                                     for x in as_list(raw.get("constraints")))
                         if c is not None],
            matrix_rows=norm_ids(raw.get("matrix_rows")),
            evidence_sva=norm_ids(evidence.get("sva") or raw.get("bound_sva")),
            evidence_scb=norm_ids(evidence.get("scoreboard") or raw.get("bound_scb")),
            target=dict(raw.get("target") or {})
            if isinstance(raw.get("target"), dict) else {},
            status=str(raw.get("status") or "未覆盖"), owner=str(raw.get("owner") or ""))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "group_id": self.id, "name": self.name,
            "requirements": list(self.requirements),
            "description": self.description, "sampling_domain": self.sampling_domain,
            "coverpoints": [c.to_dict() for c in self.coverpoints],
            "intra_cross": [c.to_dict() for c in self.intra_cross],
            "constraints": [c.to_dict() for c in self.constraints],
            "matrix_rows": list(self.matrix_rows),
            "evidence": {"sva": list(self.evidence_sva),
                         "scoreboard": list(self.evidence_scb)},
            "target": dict(self.target), "status": self.status, "owner": self.owner,
        }


@dataclass
class PathIR:
    id: str
    name: str = ""
    type: str = ""
    feats: List[str] = field(default_factory=list)
    stages: List[Any] = field(default_factory=list)
    coverpoint: str = ""
    bins: List[BinIR] = field(default_factory=list)
    bound_sva: List[str] = field(default_factory=list)
    bound_scoreboard: List[str] = field(default_factory=list)
    directed_seq: List[str] = field(default_factory=list)
    status: str = "未覆盖"

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["PathIR"]:
        if not isinstance(raw, dict):
            return None
        pid = norm_id(raw.get("path_id") or raw.get("id"))
        if not pid:
            return None
        return cls(
            id=pid, name=norm_id(raw.get("name") or pid),
            type=str(raw.get("type") or ""),
            feats=norm_ids(raw.get("feats") or raw.get("requirements")),
            stages=list(raw.get("stages") or []),
            coverpoint=norm_id(raw.get("coverpoint")),
            bins=_bins(raw.get("bins")),
            bound_sva=norm_ids(raw.get("bound_sva") or raw.get("sva")),
            bound_scoreboard=norm_ids(raw.get("bound_scoreboard") or raw.get("scb")),
            directed_seq=norm_ids(raw.get("directed_seq")),
            status=str(raw.get("status") or "未覆盖"))

    def to_dict(self) -> Dict[str, Any]:
        return {"path_id": self.id, "name": self.name, "type": self.type,
                "feats": list(self.feats), "stages": list(self.stages),
                "coverpoint": self.coverpoint, "bins": [b.to_dict() for b in self.bins],
                "bound_sva": list(self.bound_sva),
                "bound_scoreboard": list(self.bound_scoreboard),
                "directed_seq": list(self.directed_seq), "status": self.status}


@dataclass
class InterCrossIR:
    id: str
    objects: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    implementation: str = ""
    bins: List[BinIR] = field(default_factory=list)
    ignore_bins: List[BinIR] = field(default_factory=list)
    intent: str = ""
    bound_sva: List[str] = field(default_factory=list)
    bound_scoreboard: List[str] = field(default_factory=list)
    bound_cells: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> Optional["InterCrossIR"]:
        if not isinstance(raw, dict):
            return None
        cid = norm_id(raw.get("cross_id") or raw.get("id"))
        if not cid:
            return None
        return cls(id=cid, objects=norm_ids(raw.get("objects")),
                   groups=norm_ids(raw.get("groups")),
                   implementation=norm_id(raw.get("implementation")),
                   bins=_bins(raw.get("bins")),
                   ignore_bins=_bins(raw.get("ignore_bins")),
                   intent=str(raw.get("intent") or ""),
                   bound_sva=norm_ids(raw.get("bound_sva") or raw.get("sva")),
                   bound_scoreboard=norm_ids(raw.get("bound_scoreboard")
                                             or raw.get("scb")),
                   bound_cells=norm_ids(raw.get("bound_cells")))

    def to_dict(self) -> Dict[str, Any]:
        return {"cross_id": self.id, "objects": list(self.objects),
                "groups": list(self.groups), "implementation": self.implementation,
                "bins": [b.to_dict() for b in self.bins],
                "ignore_bins": [b.to_dict() for b in self.ignore_bins],
                "intent": self.intent, "bound_sva": list(self.bound_sva),
                "bound_scoreboard": list(self.bound_scoreboard),
                "bound_cells": list(self.bound_cells)}


@dataclass
class CovgIR:
    module: str = ""
    schema: str = "covg_ir_v1"
    feats: List[str] = field(default_factory=list)
    cells: List[str] = field(default_factory=list)
    covergroups: List[CovergroupIR] = field(default_factory=list)
    paths: List[PathIR] = field(default_factory=list)
    crosses: List[InterCrossIR] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, raw: Any) -> "CovgIR":
        if not isinstance(raw, dict):
            raise ValueError("covg_ir 顶层必须是 mapping")
        return cls(
            module=norm_id(raw.get("module")),
            schema=norm_id(raw.get("schema")) or "covg_ir_v1",
            feats=norm_ids(raw.get("feats")),
            cells=norm_ids(raw.get("cells")),
            covergroups=[g for g in (CovergroupIR.from_dict(x)
                                     for x in as_list(raw.get("covergroups")))
                         if g is not None],
            paths=[p for p in (PathIR.from_dict(x)
                               for x in as_list(raw.get("paths")))
                   if p is not None],
            crosses=[c for c in (InterCrossIR.from_dict(x)
                                 for x in as_list(raw.get("crosses")))
                     if c is not None],
            notes=[str(n) for n in as_list(raw.get("notes")) if str(n)])

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": self.schema, "module": self.module,
                "feats": list(self.feats), "cells": list(self.cells),
                "covergroups": [g.to_dict() for g in self.covergroups],
                "paths": [p.to_dict() for p in self.paths],
                "crosses": [c.to_dict() for c in self.crosses],
                "notes": list(self.notes)}

    # ── 查询 ──
    def coverpoints(self) -> Dict[str, tuple]:
        out = {}
        for group in self.covergroups:
            for cp in group.coverpoints:
                out[cp.id] = (group, cp)
                out.setdefault(cp.name, (group, cp))
        return out

    def path_ids(self) -> List[str]:
        return [p.id for p in self.paths]

    def group_ids(self) -> List[str]:
        return [g.id for g in self.covergroups]


def all_bins(ir: CovgIR) -> List[BinIR]:
    out = []
    for group in ir.covergroups:
        for cp in group.coverpoints:
            out.extend(cp.bins + cp.illegal_bins)
        for cross in group.intra_cross:
            out.extend(cross.bins + cross.ignore_bins)
    for path in ir.paths:
        out.extend(path.bins)
    for cross in ir.crosses:
        out.extend(cross.bins + cross.ignore_bins)
    return out
