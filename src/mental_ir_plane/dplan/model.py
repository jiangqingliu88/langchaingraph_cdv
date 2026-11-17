"""DPlan IR —— 设计/模型契约的稳定形状（`dplan_ir_v1`）。

只描述**设计准备怎么实现**：interfaces / features / architecture / modules /
registers / model_contract。它不描述验证义务、执行结果或签核状态。

来源是 DPlan JSON（可能由 LLM bootstrap 生成），所以：
  · 未知字段进 `extra`，不丢弃；
  · 字符串化/乱码条目原样保留并标记；
  · 不做语义修复，不补造 behavior。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA = "dplan_ir_v1"


def _rows(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        out = []
        for key, row in value.items():
            if isinstance(row, dict):
                item = dict(row)
                item.setdefault("name", key)
                item.setdefault("id", key)
                out.append(item)
            else:
                out.append({"name": key, "value": row})
        return out
    if isinstance(value, (list, tuple)):
        out = []
        for row in value:
            if isinstance(row, dict):
                out.append(dict(row))
            elif isinstance(row, str) and row.strip():
                parsed = _maybe_json(row)
                out.append(parsed if isinstance(parsed, dict) else {"raw": row})
        return out
    return [{"raw": value}]


def _maybe_json(text: str) -> Any:
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        pass
    try:
        import ast

        return ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return text


def _extra(row: Dict[str, Any], known: set[str]) -> Dict[str, Any]:
    return {k: v for k, v in row.items() if k not in known}


@dataclass
class Interface:
    name: str
    data_width: Any = None
    direction: str = ""
    protocol: str = ""
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Interface":
        known = {"name", "data_width", "direction", "protocol", "description", "extra"}
        return cls(
            name=str(row.get("name") or row.get("id") or ""),
            data_width=row.get("data_width", row.get("width")),
            direction=str(row.get("direction") or ""),
            protocol=str(row.get("protocol") or ""),
            description=str(row.get("description") or ""),
            extra={**row.get("extra", {}), **_extra(row, known)},
        )


@dataclass
class Register:
    name: str
    address: str = ""
    width: Any = None
    description: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Register":
        known = {"name", "id", "address", "width", "description", "extra"}
        return cls(
            name=str(row.get("name") or row.get("id") or row.get("address") or ""),
            address=str(row.get("address") or ""),
            width=row.get("width"),
            description=str(row.get("description") or ""),
            extra={**row.get("extra", {}), **_extra(row, known)},
        )


@dataclass
class Feature:
    feature_id: str
    name: str = ""
    level: str = ""
    parent_id: str = ""
    l1: str = ""
    l2: str = ""
    l3: str = ""
    description: str = ""
    priority: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Feature":
        known = {"feature_id", "id", "name", "feature_level", "level", "parent_feature_id", "parent_id",
                 "feature_l1", "feature_l2", "feature_l3", "l1", "l2", "l3",
                 "description", "priority", "extra"}
        return cls(
            feature_id=str(row.get("feature_id") or row.get("id") or row.get("name") or ""),
            name=str(row.get("name") or ""),
            level=str(row.get("feature_level") or row.get("level") or ""),
            parent_id=str(row.get("parent_feature_id") or row.get("parent_id") or ""),
            l1=str(row.get("feature_l1") or row.get("l1") or ""),
            l2=str(row.get("feature_l2") or row.get("l2") or ""),
            l3=str(row.get("feature_l3") or row.get("l3") or ""),
            description=str(row.get("description") or ""),
            priority=str(row.get("priority") or ""),
            extra={**row.get("extra", {}), **_extra(row, known)},
        )


@dataclass
class Module:
    name: str
    level: str = ""
    parent: str = ""
    function: str = ""
    method: str = ""
    interfaces: List[str] = field(default_factory=list)
    combinational: str = ""
    sequential: str = ""
    submodules: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "Module":
        known = {"name", "id", "level", "parent", "function", "method", "interfaces",
                 "combinational", "sequential", "submodules", "extra"}
        def _list(value: Any) -> List[str]:
            if isinstance(value, (list, tuple)):
                return [str(x) for x in value]
            text = str(value or "").strip()
            return [x.strip() for x in text.replace("|", ",").split(",") if x.strip()] if text else []
        return cls(
            name=str(row.get("name") or row.get("id") or ""),
            level=str(row.get("level") or ""),
            parent=str(row.get("parent") or ""),
            function=str(row.get("function") or row.get("description") or ""),
            method=str(row.get("method") or ""),
            interfaces=_list(row.get("interfaces")),
            combinational=str(row.get("combinational") or ""),
            sequential=str(row.get("sequential") or ""),
            submodules=_list(row.get("submodules")),
            extra={**row.get("extra", {}), **_extra(row, known)},
        )


@dataclass
class ModelState:
    name: str
    description: str = ""
    raw: str = ""
    parsed: bool = True
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ModelState":
        name = row.get("name") or row.get("id")
        raw = row.get("raw")
        if name is None and raw is not None:
            return cls(name=str(raw)[:80], raw=str(raw), parsed=False)
        return cls(
            name=str(name or ""),
            description=str(row.get("description") or ""),
            raw=str(row.get("raw") or ""),
            parsed=bool(row.get("parsed", True)),
            extra={**row.get("extra", {}),
                   **_extra(row, {"name", "id", "description", "raw", "parsed", "extra"})},
        )


@dataclass
class ModelBehavior:
    name: str
    when: str = ""
    expect: str = ""
    checks: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ModelBehavior":
        checks = row.get("checks")
        if isinstance(checks, str):
            checks = [x.strip() for x in checks.replace("|", ",").split(",") if x.strip()]
        return cls(
            name=str(row.get("name") or row.get("id") or ""),
            when=str(row.get("when") or ""),
            expect=str(row.get("expect") or row.get("expected") or ""),
            checks=[str(x) for x in (checks or [])],
            extra={**row.get("extra", {}), **_extra(row, {"name", "id", "when", "expect", "expected", "checks", "extra"})},
        )


@dataclass
class ModelContract:
    module: str = ""
    ports: List[Interface] = field(default_factory=list)
    state: List[ModelState] = field(default_factory=list)
    behaviors: List[ModelBehavior] = field(default_factory=list)
    scoreboard: Any = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Dict[str, Any]) -> "ModelContract":
        return cls(
            module=str(row.get("module") or ""),
            ports=[Interface.from_row(r) for r in _rows(row.get("ports"))],
            state=[ModelState.from_row(r) for r in _rows(row.get("state"))],
            behaviors=[ModelBehavior.from_row(r) for r in _rows(row.get("behaviors"))],
            scoreboard=row.get("scoreboard"),
            extra={**row.get("extra", {}), **_extra(row, {"module", "ports", "state", "behaviors", "scoreboard", "extra"})},
        )


@dataclass
class Architecture:
    top: str = ""
    stages: List[str] = field(default_factory=list)
    method: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: Optional[Dict[str, Any]]) -> "Architecture":
        row = row if isinstance(row, dict) else {}
        stages = row.get("stages")
        if isinstance(stages, str):
            stages = [x.strip() for x in stages.replace("|", ",").split(",") if x.strip()]
        return cls(
            top=str(row.get("top") or ""),
            stages=[str(x) for x in (stages or [])],
            method=str(row.get("method") or ""),
            extra={**row.get("extra", {}), **_extra(row, {"top", "stages", "method", "extra"})},
        )


@dataclass
class DesignPlan:
    schema: str = SCHEMA
    design_name: str = ""
    version: str = ""
    overview: str = ""
    interfaces: List[Interface] = field(default_factory=list)
    registers: List[Register] = field(default_factory=list)
    features: List[Feature] = field(default_factory=list)
    modules: List[Module] = field(default_factory=list)
    architecture: Architecture = field(default_factory=Architecture)
    model_contract: ModelContract = field(default_factory=ModelContract)
    #: 原始 DPlan 里嵌入的 VPlan-like 集合：保留但不作为 VPlan 权威
    embedded_vplan: Dict[str, Any] = field(default_factory=dict)
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, doc: Dict[str, Any]) -> "DesignPlan":
        if not isinstance(doc, dict):
            raise TypeError("DPlan 输入必须是 JSON object")
        known = {"schema", "design_name", "version", "overview", "interfaces", "registers",
                 "features", "modules", "architecture", "model_contract", "embedded_vplan", "extra",
                 "requirements", "topics", "contracts", "testpoints", "cases"}
        embedded = doc.get("embedded_vplan")
        if not isinstance(embedded, dict):
            embedded = {k: doc[k] for k in ("requirements", "topics", "contracts", "testpoints", "cases")
                        if k in doc}
        return cls(
            schema=str(doc.get("schema") or SCHEMA),
            design_name=str(doc.get("design_name") or doc.get("module") or ""),
            version=str(doc.get("version") or ""),
            overview=str(doc.get("overview") or ""),
            interfaces=[Interface.from_row(r) for r in _rows(doc.get("interfaces"))],
            registers=[Register.from_row(r) for r in _rows(doc.get("registers"))],
            features=[Feature.from_row(r) for r in _rows(doc.get("features"))],
            modules=[Module.from_row(r) for r in _rows(doc.get("modules"))],
            architecture=Architecture.from_row(doc.get("architecture")),
            model_contract=ModelContract.from_row(
                doc.get("model_contract") if isinstance(doc.get("model_contract"), dict) else {}),
            embedded_vplan=embedded,
            extra={**doc.get("extra", {}), **_extra(doc, known)},
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "design_name": self.design_name,
            "version": self.version,
            "overview": self.overview,
            "interfaces": [asdict(x) for x in self.interfaces],
            "registers": [asdict(x) for x in self.registers],
            "features": [asdict(x) for x in self.features],
            "modules": [asdict(x) for x in self.modules],
            "architecture": asdict(self.architecture),
            "model_contract": {
                "module": self.model_contract.module,
                "ports": [asdict(x) for x in self.model_contract.ports],
                "state": [asdict(x) for x in self.model_contract.state],
                "behaviors": [asdict(x) for x in self.model_contract.behaviors],
                "scoreboard": self.model_contract.scoreboard,
                "extra": self.model_contract.extra,
            },
            "embedded_vplan": self.embedded_vplan,
            "extra": self.extra,
        }

    def canonical(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    def digest(self) -> str:
        return hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def counts(self) -> Dict[str, int]:
        return {
            "interfaces": len(self.interfaces),
            "registers": len(self.registers),
            "features": len(self.features),
            "modules": len(self.modules),
            "model_ports": len(self.model_contract.ports),
            "model_state": len(self.model_contract.state),
            "model_behaviors": len(self.model_contract.behaviors),
        }


__all__ = [
    "SCHEMA", "Interface", "Register", "Feature", "Module", "ModelState",
    "ModelBehavior", "ModelContract", "Architecture", "DesignPlan",
]
