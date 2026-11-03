"""verify 产出的 IR 文件清单 + 契约构建（从 `main.py` 抽出，控制单文件规模）。

这里只放"落盘之后的记账"：哪些文件算这一步的产物、契约怎么编译。
判定与生成逻辑不在这里 —— `main.py` 仍是唯一入口。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()

#: 这一步可能产出的附属文件（相对运行目录）。没生成的不列。
_EXTRA_FILES = (
    ("coverage", ("case_ir.json", "case_group_map.json",
                  "case_checker_map.json", "stimulus_plan.json")),
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


def enrich_case_ir(output_dir: Path, case_ir: Dict[str, Any]) -> Dict[str, Any]:
    """给 Case IR 补**约束归属**（`constraints[]` + `constraint_backing`）。

    约束 id 来自 coverage plan 的策略注册表；归属按维度交集匹配（见
    `humanview.case_ir.constraints`）。没有计划就原样返回 —— 不编 id。
    """
    if not case_ir or not case_ir.get("cases"):
        return case_ir
    try:
        from src.tools.humanview.case_ir import attach_constraints

        return attach_constraints(case_ir, load_coverage_plan(output_dir))
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"约束归属计算失败（Case IR 不带 constraints）: {e}")
        return case_ir


def attach_tp_constraints(payload: Dict[str, Any],
                          output_dir: Path) -> Dict[str, Any]:
    """把约束归属同时写进 **Case IR 与 TP IR**，并保持 manifest 哈希自证。

    `testpoints.yaml` 是 manifest 哈希的对象；改了内容必须重算 YAML 与 sha256，
    否则 verify 末尾那条"manifest 说 X、文件是 Y"的自证会亮红（那不是 bug，
    是证据链在提醒）。
    """
    if not isinstance(payload, dict):
        return payload
    case_ir = enrich_case_ir(output_dir, payload.get("case_ir") or {})
    payload["case_ir"] = case_ir
    by_case = {str(c.get("id")): list(c.get("constraints") or [])
               for c in case_ir.get("cases") or [] if isinstance(c, dict)}
    changed = False
    for tp in payload.get("testpoints") or []:
        if not isinstance(tp, dict):
            continue
        ids = by_case.get(str(tp.get("case_id") or "")) or []
        if ids and list(tp.get("constraints") or []) != ids:
            tp["constraints"] = ids
            changed = True
    if not changed:
        return payload
    try:
        import hashlib

        from src.tools.generation.casemodel_tools.plan import testpoints_yaml

        text = testpoints_yaml(payload)
        payload["testpoints_yaml"] = text
        artifacts = ((payload.get("methodology") or {}).get("artifacts") or {})
        entry = artifacts.get("testpoints_yaml")
        if isinstance(entry, dict):
            entry["sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"TP 约束归属重算 YAML/哈希失败（保持原文件）: {e}")
    return payload


def write_contract_build(output_dir: Path, case_ir: Dict[str, Any]) -> None:
    """M1：把 case_ir 编译成**构建物**（contract/contract.yaml + 义务 + 清单）。

    失败只告警：契约缺失会在 ops 的前置门禁上响亮失败 —— 不在这里把 verify
    整轮拖死（"生成失败"和"没契约"是两件事，各自都要看得见）。
    """
    if not case_ir or not case_ir.get("cases"):
        return
    try:
        from src.tools.checking.verification_os import write_contract

        manifest = write_contract(output_dir, case_ir)
        logger.info(f"契约：{manifest['contract_id']} · "
                    f"{manifest['obligations']} 条义务 · "
                    f"hash {manifest['contract_hash'][:12]}… → contract/")
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"契约编译失败（ops 会被门禁拦下）: {e}")
