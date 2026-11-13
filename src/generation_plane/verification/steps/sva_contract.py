"""把 `data/assertions.csv` 落成可执行 SVA（module + bind 进 DUT）。

规则来自 VPlan 执行资产；资产头写 `CONTRACT_REFS`，供 `vplan gate` 认领。
没有可生成内容时如实 warning，不用“没报错”冒充“验过了”。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


def sva_contract_refs(project, decls: Dict[str, Any],
                      module: str = "") -> List[str]:
    """断言 `tp_bindings` → TP → contract_id。"""
    mapping: Dict[str, str] = {}
    if project is not None:
        root = Path(project.root)
        module = str(module or getattr(project, "module", "") or root.name)
        path = root / "docs" / "specs" / f"{module}_testpoints.csv"
        if path.is_file():
            try:
                with path.open(encoding="utf-8-sig", newline="") as fh:
                    for row in csv.DictReader(fh):
                        if row.get("tp_id") and row.get("contract_id"):
                            mapping[str(row["tp_id"])] = str(row["contract_id"])
            except OSError:
                mapping = {}
    refs = set()
    for assertion in decls.get("assertions") or []:
        if not isinstance(assertion, dict):
            continue
        for binding in assertion.get("tp_bindings") or []:
            if not isinstance(binding, dict):
                continue
            cid = mapping.get(str(binding.get("tp_id") or ""))
            if cid:
                refs.add(cid)
    return sorted(refs)


def attach_sva_assertions(output_dir: Path, module_name: str,
                          files: List[str]) -> None:
    """生成 SVA 到 `<run>/assertions/` 并追加到 `files`。"""
    from src.orchestration_plane.l2.communication.tool_hub import call_tool
    from src.ir_plane.vplan import engine

    from .helpers import _load_runtime_model_doc, _spec_of

    try:
        project = engine.project_for(_spec_of(output_dir), output_dir)
        decls: Dict[str, Any] = {}
        if project is not None:
            decls = _load_runtime_model_doc(engine.model_text(project))
        sva_spec = {
            "sampling": decls.get("sampling") or {},
            "assertions": decls.get("assertions") or [],
        }
        sva = call_tool("generate_sva_assertions", {
            "specs": json.dumps(sva_spec, ensure_ascii=False)})
        if not (sva or "").strip():
            logger.warning(
                "断言：没有可生成的 SVA（模型没有 assertions 或 "
                "sampling.dut_module）—— 本轮 pass 只代表没报错")
            return
        contracts = sva_contract_refs(project, decls, module_name)
        header = (
            "// " + "=" * 76 + "\n"
            f"// assertions/{module_name}_assertions.sv — SignOffAI 生成资产（VPlan 布局）\n"
            f"// ARTIFACT: {module_name}_assertions\n"
            f"// CONTRACT_REFS: {' '.join(contracts) or '(none)'}\n"
            "// " + "=" * 76 + "\n")
        asrt_dir = output_dir / "assertions"
        asrt_dir.mkdir(parents=True, exist_ok=True)
        path = asrt_dir / f"{module_name}_assertions.sv"
        path.write_text(header + sva, encoding="utf-8")
        files.append(str(path))
        logger.info(
            f"断言：{path.name}（bind 到 "
            f"{sva_spec['sampling'].get('dut_module')}；契约 "
            f"{', '.join(contracts) or '无'}；会被真编译、真报错）")
    except Exception as e:                     # noqa: BLE001 断言是可选增强，不拦主流程
        logger.warning(f"断言生成失败（本轮没有 SVA）: {e}")


__all__ = ["attach_sva_assertions", "sva_contract_refs"]
