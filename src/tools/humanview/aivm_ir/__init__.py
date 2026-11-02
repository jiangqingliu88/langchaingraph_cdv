"""AIVM 测试点 IR：枚举化数据模型 + xlsx 往返 + M1 计划编译器。

典型用法：
    from aivm_ir import load_xlsx_to_ontology, compile_ontology, Category
    onto = load_xlsx_to_ontology("xxx.xlsx")
    plan = compile_ontology(onto, categories={Category.IF})
"""
from .ir_core import (
    Category, DimType, Status, ExecutionMode, TestNumKind,
    CellRole, CellType,
    Component, RawColumn,
    Provenance, DimensionValue, LegalityRule, Dimension,
    CoverageCell, TestPointIR, Ontology,
)
from .xlsx_loader import load_xlsx_to_ontology
from .xlsx_writer import write_ontology_to_xlsx, write_ontology_to_json
from .validate import validate_ontology
from .plan_compiler_m1 import compile_ontology, compile_tp
from .api import summarize_xlsx

__all__ = [
    # 枚举
    "Category", "DimType", "Status", "ExecutionMode", "TestNumKind",
    "CellRole", "CellType",
    "Component", "RawColumn",
    # 数据模型
    "Provenance", "DimensionValue", "LegalityRule", "Dimension",
    "CoverageCell", "TestPointIR", "Ontology",
    # IO / 校验 / 编译
    "load_xlsx_to_ontology",
    "write_ontology_to_xlsx", "write_ontology_to_json",
    "validate_ontology",
    "compile_ontology", "compile_tp", "summarize_xlsx",
]
__version__ = "1.2.0"
