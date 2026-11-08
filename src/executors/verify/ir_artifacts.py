"""verify 产出的 IR 文件清单 + 契约构建（从 `main.py` 抽出，控制单文件规模）。

这里只放"落盘之后的记账"：哪些文件算这一步的产物、契约怎么编译。
判定与生成逻辑不在这里 —— `main.py` 仍是唯一入口。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

#: 这一步可能产出的附属文件（相对运行目录）。没生成的不列。
_EXTRA_FILES = (
    ("coverage", ("case_ir.json", "case_closure.json", "case_group_map.json",
                  "case_checker_map.json", "stimulus_plan.json",
                  "verification_ir.json", "resource_model.json",
                  "resource_scenarios.json", "intents.json", "claims.json")),
    ("contract", ("contract.yaml", "obligations.json",
                  "contract_manifest.json")),
)


def testpoint_files(output_dir: Path) -> List[str]:
    """TP IR 这一步产出的全部文件（含 Case IR / 契约 / StimulusPlan）。"""
    files = [str(output_dir / "coverage" / "testpoints.yaml"),
             str(output_dir / "coverage" / "testpoints.json"),
             str(output_dir / "coverage" / "methodology.json")]
    for sub, names in _EXTRA_FILES:
        for name in names:
            if (output_dir / sub / name).is_file():
                files.append(str(output_dir / sub / name))
    return files


def load_coverage_plan(output_dir: Path) -> Dict[str, Any]:
    """读 `coverage/coverage_plan.yaml`（约束归属的声明来源）。失败给 `{}`。"""
    path = Path(output_dir) / "coverage" / "coverage_plan.yaml"
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError, ImportError):
        return {}
    return doc if isinstance(doc, dict) else {}


def write_case_closure(output_dir: Path, case_ir: Dict[str, Any],
                       case_model: Path | None, module: str = "",
                       known_dimensions: Optional[List[str]] = None
                       ) -> Dict[str, Any]:
    """**引用闭合** → `coverage/case_closure.json`（生成期只落读数）。

    CASE 绑定的维度必须在执行资产里，checker 必须绑到 TP。这里不阻断
    生成 —— 由 Case Gate 据这份读数发 blocker。

    VPlan 路径直接传 `known_dimensions`（`data/dimensions.csv` 的 id）；
    老路径才从 case 模型读。
    """
    from src.layers.l3_decision.case_ir import parse_declared, validate_case_closure

    known = list(known_dimensions or [])
    if not known and case_model is not None:
        from src.layers.l3_decision.vplan.runtime.repository import load_model

        known = [d.key for d in load_model(case_model).dimensions]
    closure = validate_case_closure(parse_declared(case_ir, module=module),
                                    known_dimensions=known)
    from src.core.runtime.atomic import atomic_write_json

    path = Path(output_dir) / "coverage" / "case_closure.json"
    atomic_write_json(path, closure)
    return closure


def enrich_case_ir(output_dir: Path, case_ir: Dict[str, Any]) -> Dict[str, Any]:
    """给 Case IR 补**约束归属**（`constraints[]` + `constraint_backing`）。

    约束 id 来自 coverage plan 的策略注册表；归属按维度交集匹配（见
    `humanview.case_ir.constraints`）。没有计划就原样返回 —— 不编 id。
    """
    if not case_ir or not case_ir.get("cases"):
        return case_ir
    try:
        from src.layers.l3_decision.case_ir import attach_constraints

        return attach_constraints(case_ir, load_coverage_plan(output_dir))
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"约束归属计算失败（Case IR 不带 constraints）: {e}")
        return case_ir


def _tp_case_ids(tp: Dict[str, Any]) -> List[str]:
    """TP 的全部 CASE 身份（`case_ids` 优先，回退单一 `case_id`）。"""
    ids = [str(c) for c in (tp.get("case_ids") or []) if str(c)]
    if not ids and tp.get("case_id"):
        ids = [str(tp["case_id"])]
    return ids


def _apply_tp_constraints(tp: Dict[str, Any],
                          by_case: Dict[str, List[str]]) -> bool:
    """给一条 TP 填约束**并集**；返回是否有改动。"""
    if not isinstance(tp, dict):
        return False
    ids: List[str] = []
    for cid in _tp_case_ids(tp):
        for c in by_case.get(cid) or []:
            if c not in ids:
                ids.append(c)
    if ids and list(tp.get("constraints") or []) != ids:
        tp["constraints"] = ids
        return True
    return False


def _restamp_testpoints_yaml(payload: Dict[str, Any]) -> None:
    """TP 内容变了 → 重算 YAML 与 sha256（manifest 自证）。失败不挡流程。"""
    try:
        import hashlib

        from src.layers.l3_decision.vplan.serialize import testpoints_yaml

        text = testpoints_yaml(payload)
        payload["testpoints_yaml"] = text
        artifacts = ((payload.get("methodology") or {}).get("artifacts") or {})
        entry = artifacts.get("testpoints_yaml")
        if isinstance(entry, dict):
            entry["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"TP 约束归属重算 YAML/哈希失败（保持原文件）: {e}")


def attach_tp_constraints(payload: Dict[str, Any],
                          output_dir: Path) -> Dict[str, Any]:
    """把约束归属同时写进 **Case IR 与 TP IR**，并保持 manifest 哈希自证。

    `testpoints.yaml` 是 manifest 哈希的对象；改了内容必须重算 YAML 与 sha256，
    否则 verify 末尾那条"manifest 说 X、文件是 Y"的自证会亮红（那不是 bug，
    是证据链在提醒）。
    """
    if not isinstance(payload, dict):
        return payload
    payload["case_ir"] = enrich_case_ir(output_dir, payload.get("case_ir") or {})
    by_case = {str(c.get("id")): list(c.get("constraints") or [])
               for c in payload["case_ir"].get("cases") or []
               if isinstance(c, dict)}
    changed = False
    for tp in payload.get("testpoints") or []:
        changed = _apply_tp_constraints(tp, by_case) or changed
    if changed:
        _restamp_testpoints_yaml(payload)
    return payload


def write_verification_ir(output_dir: Path, case_ir: Dict[str, Any],
                          payload: Dict[str, Any],
                          resources: Dict[str, Any] = None) -> Dict[str, Any]:
    """P1：Case/TP IR → **Unified Verification IR v3**（`coverage/verification_ir.json`）。

    IR 是统一视图，**不替换** `case_ir.json`（后者仍是 CASE/CCAT 身份源）。
    校验失败只告警：IR 是附加读数，不能把已成功的 verify 拖红。
    """
    if not case_ir or not case_ir.get("cases"):
        return {}
    try:
        from src.core.runtime.atomic import atomic_write_json
        from src.layers.l3_decision.verification_ir import (
            compile_from_case_ir, validate,
        )

        methodology = payload.get("methodology") or {}
        ir = compile_from_case_ir(
            case_ir,
            testpoints=payload.get("testpoints") or [],
            resources=resources or {},
            design_version=str(methodology.get("rtl_hash") or ""),
            model_version=str(methodology.get("testpoints_hash") or ""),
            metadata={"source": "verify/testpoints"},
        )
        result = validate(ir)
        doc = ir.to_dict()
        doc["validation"] = result
        atomic_write_json(Path(output_dir) / "coverage" / "verification_ir.json",
                          doc)
        if not result.get("ok"):
            logger.warning(f"Unified IR 校验：{len(result.get('errors') or [])} 条错误"
                           f"（见 coverage/verification_ir.json）")
        return {"ir_id": ir.identity.ir_id,
                "relations": len(ir.relations),
                "testpoints": len((ir.verification or {}).get("testpoints") or []),
                "ok": bool(result.get("ok"))}
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"Unified IR 编译失败（不影响生成）: {e}")
        return {}


def _resources_file(output_dir: Path, case_model: Optional[Path]) -> Optional[Path]:
    """资源模型声明文件的查找顺序（离这次运行由近到远）。"""
    candidates: List[Path] = []
    if case_model is not None:
        candidates.append(Path(case_model).parent / "resources.yaml")
    candidates += [
        Path(output_dir) / "inputs" / "resources.yaml",
        Path(output_dir) / "inputs" / "yaml" / "uvm" / "resources.yaml",
    ]
    return next((p for p in candidates if p.is_file()), None)


def write_resource_artifacts(output_dir: Path, module: str = "",
                             case_model: Optional[Path] = None
                             ) -> Dict[str, Any]:
    """P2：资源/交互模型 → `coverage/resource_model.json` +
    `coverage/resource_scenarios.json`。

    没有声明文件时返回 `{"available": False}` —— **不编造资源**。
    """
    path = _resources_file(output_dir, case_model)
    if path is None:
        # **清掉上一轮残留**：否则 env 渲染会读到旧资源模型，生出一份与本次
        # 声明无关的 checker（不会编译失败，只会静默检查错东西）。
        for name in ("resource_model.json", "resource_scenarios.json"):
            stale = Path(output_dir) / "coverage" / name
            try:
                if stale.is_file():
                    stale.unlink()
                    logger.warning(f"资源声明已移除，删除上一轮残留 {name}")
            except OSError:
                pass
        return {"available": False}
    try:
        import yaml

        from src.core.runtime.atomic import atomic_write_json
        from src.layers.l3_decision.resource_model import (
            compile_scenarios, coverage_summary, from_dict,
        )

        doc = yaml.safe_load(path.read_text(encoding="utf-8",
                                            errors="replace")) or {}
        model = from_dict(doc if isinstance(doc, dict) else {})
        model.module = model.module or module
        facts = model.interaction_facts()
        scenarios = compile_scenarios(model)
        atomic_write_json(Path(output_dir) / "coverage" / "resource_model.json",
                          {**model.to_dict(), "source": str(path),
                           "facts": facts, "validation": model.validate()})
        atomic_write_json(
            Path(output_dir) / "coverage" / "resource_scenarios.json",
            {"schema": "resource_scenarios_v1", "module": model.module,
             "scenarios": scenarios,
             "coverage": coverage_summary(scenarios)})
        return {"available": True, "source": str(path),
                "resources": len(model.resources),
                "operations": len(model.operations),
                "scenarios": len(scenarios),
                # 供 Unified IR 的 D4 域与 StimulusPlan 的附加段复用。
                "model": model.to_dict(),
                "scenario_docs": scenarios}
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"资源模型编译失败（不影响生成）: {e}")
        return {"available": False, "error": str(e)}


def load_resource_docs(output_dir: Path) -> Dict[str, Any]:
    """读已落盘的资源模型/场景（渲染前写过时复用，不重复解析 YAML）。"""
    cov = Path(output_dir) / "coverage"

    def _read(name: str) -> Dict[str, Any]:
        try:
            doc = json.loads((cov / name).read_text(encoding="utf-8",
                                                    errors="replace"))
        except (OSError, ValueError):
            return {}
        return doc if isinstance(doc, dict) else {}

    model = _read("resource_model.json")
    if not model.get("operations"):
        return {"available": False}
    scenarios = _read("resource_scenarios.json")
    return {"available": True, "source": model.get("source", ""),
            "resources": len(model.get("resources") or []),
            "operations": len(model.get("operations") or []),
            "scenarios": len(scenarios.get("scenarios") or []),
            "model": model, "scenario_docs": scenarios.get("scenarios") or []}


def write_contract_build(output_dir: Path, case_ir: Dict[str, Any]) -> None:
    """M1：把 case_ir 编译成**构建物**（contract/contract.yaml + 义务 + 清单）。

    失败只告警：契约缺失会在 ops 的前置门禁上响亮失败 —— 不在这里把 verify
    整轮拖死（"生成失败"和"没契约"是两件事，各自都要看得见）。
    """
    if not case_ir or not case_ir.get("cases"):
        return
    try:
        from src.layers.l3_decision.contract import write_contract

        manifest = write_contract(output_dir, case_ir)
        logger.info(f"契约：{manifest['contract_id']} · "
                    f"{manifest['obligations']} 条义务 · "
                    f"hash {manifest['contract_hash'][:12]}… → contract/")
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"契约编译失败（ops 会被门禁拦下）: {e}")
