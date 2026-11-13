"""Case IR —— CCAT（分类树）/ CASE（逻辑用例）的身份层。

TST（可执行实例）与 EVD（一次执行证据）**不是**这里的实体：它们由
`test + seed` 派生，id 生成只有一处（`tst_id_of` / `evd_id_of`）。

用法：

    from src.ir_plane.decision.case_ir import (
        load_case_ir, project_from_model, validate_case_doc,
        tst_id_of, evd_id_of,
    )
    doc = project_from_model(model_dict)   # 没写 cases: 就按维度合成
    assert validate_case_doc(doc)["ok"]
    case_id = doc.resolve(test="...", dimension="D_dep")
"""
from __future__ import annotations

from .constraints import (
    attach_constraints, case_dimensions, constraints_for, policy_index,
)
from .contract import attach_contracts, checker_map, group_map
from .ir_core import (
    SCHEMA, SOURCE_DECLARED, SOURCE_SYNTHESIZED, CaseDoc, CaseIR, CCatIR,
    case_id_of, ccat_id_of, evd_id_of, group_id_of, group_short, scb_id_of,
    slug, sva_id_of, tst_id_of,
)
from .loader import (
    DEFAULT_ROOT, load_case_ir, parse_declared, project_from_model, synthesize,
)
from .validate import validate_case_closure, validate_case_doc
from .xlsx_projection import (
    bindings_skeleton, load_bindings, project_from_ontology, project_from_xlsx,
)

__all__ = [
    "SCHEMA", "SOURCE_DECLARED", "SOURCE_SYNTHESIZED",
    "CaseDoc", "CaseIR", "CCatIR", "DEFAULT_ROOT",
    "case_id_of", "ccat_id_of", "evd_id_of", "group_id_of", "group_short",
    "scb_id_of", "slug", "sva_id_of", "tst_id_of",
    "load_case_ir", "parse_declared", "project_from_model", "synthesize",
    "project_from_xlsx", "project_from_ontology", "load_bindings",
    "bindings_skeleton",
    "attach_contracts", "checker_map", "group_map",
    "attach_constraints", "case_dimensions", "constraints_for", "policy_index",
    "validate_case_closure", "validate_case_doc",
]
