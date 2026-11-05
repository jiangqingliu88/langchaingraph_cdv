"""分析层 —— 只读判定（schema 校验、lint、配对核对）。

分层：import `domain`（+ `repository` 的产物），不 import `compile`。
"""
from .issues import SEVERITIES, Issue, count_by_severity, sort_issues
from .schema_check import (DSL_SCHEMA_FILE, check_dsl, check_dsl_text,
                           generated_schema, load_dsl, schema_file_matches_model)

__all__ = ["Issue", "SEVERITIES", "count_by_severity", "sort_issues",
           "check_dsl", "check_dsl_text", "load_dsl", "generated_schema",
           "schema_file_matches_model", "DSL_SCHEMA_FILE"]
