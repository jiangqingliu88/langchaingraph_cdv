"""约束产物生成器 —— `constraint_status.json` 与 coverage_plan 标注。

从 `VerifyExecutor` 的两个静态方法拆出；`constraint.yaml` 的构建仍由
`casemodel_tools.associate.build_constraint` 负责（那是领域层，不是本层）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def write_constraint_status(output_dir: Path, payload: Dict[str, Any],
                            logger: Any) -> None:
    """落盘 `coverage/constraint_status.json`（逐条策略生效状态）。"""
    cov_dir = output_dir / "coverage"
    try:
        cov_dir.mkdir(parents=True, exist_ok=True)
        total = int(payload.get("policy_count") or 0)
        backed = int(payload.get("backed_policy_count") or 0)
        unbacked = int(payload.get("unbacked_policy_count")
                       if payload.get("unbacked_policy_count") is not None
                       else (total - backed))
        skeletons = bool(payload.get("policies_are_skeletons"))
        if skeletons:
            note = ("策略体全是空骨架：apply() 落到 `default:` 分支，不做任何事"
                    "（可驱动维度一个都没有 —— 检查模型里的 `stimulus.field`）")
        elif unbacked:
            note = (f"{backed}/{total} 条策略由模型编译出真实赋值；"
                    f"其余 {unbacked} 条仍是骨架 —— 它们的维度不可驱动"
                    f"（没有 `stimulus.field`，通常是 DUT 内部量/输出端口）")
        else:
            note = ""
        status = {
            "constraint_generated": True,
            "constraint_policy_applied": (not skeletons) and unbacked == 0,
            "policy_count": total,
            "backed_policy_count": backed,
            "unbacked_policy_count": unbacked,
            "note": note,
        }
        (cov_dir / "constraint_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"约束状态落盘失败（audit 将看不到约束是否生效）: {e}")


def annotate_coverage_plan(output_dir: Path, payload: Dict[str, Any],
                           logger: Any) -> None:
    """把 `constraint_backing` 追写进 `coverage/coverage_plan.yaml`。"""
    path = output_dir / "coverage" / "coverage_plan.yaml"
    if not path.is_file():
        return
    try:
        import yaml as _yaml

        doc = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(doc, dict):
            return
        doc["constraint_backing"] = payload.get("constraint_backing") or {
            "policy_count": int(payload.get("policy_count") or 0),
            "backed_policy_count": int(payload.get("backed_policy_count") or 0),
            "unbacked_policy_count": int(payload.get("unbacked_policy_count") or 0),
            "policies": [{
                "name": p.get("name"),
                "backed": bool(p.get("backed")),
                "reason": p.get("backing_reason") or "",
                "dimensions": list(p.get("dimensions") or []),
            } for p in (payload.get("policies") or [])],
        }
        path.write_text(
            _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100),
            encoding="utf-8")
    except Exception as e:                       # noqa: BLE001 旁路
        logger.warning(f"coverage_plan 约束标注失败（不影响约束生成）: {e}")
