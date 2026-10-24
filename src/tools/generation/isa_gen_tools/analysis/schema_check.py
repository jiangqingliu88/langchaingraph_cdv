"""DSL 的 schema 校验 —— **一次把所有的错都报出来**。

引擎是 pydantic（不是 jsonschema），理由见 `domain/dsl.py` 的模块头：
两份手写的契约一定会漂移，而 pydantic 模型本身就是契约，
`schema/dsl.schema.json` 由它生成、有测试断言相等。既然引擎是它，
校验就直接用它 —— 再引一个 jsonschema 只会多一个能对不上的地方。

pydantic 的 `ValidationError` 带 `loc`（键路径）与 `msg`，
正好能翻成 `Issue` 的 `target` / `message`。**关键是不要只报第一条**：
一份 DSL 里五个键拼错，抛异常只能报一个，使用者得跑五趟。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import ValidationError

from ..domain import IsaGenError
from ..domain.dsl import DslDocument
from .issues import Issue

#: 生成的契约文件 —— 与 pydantic 模型必须一致（有测试钉住）
DSL_SCHEMA_FILE = Path(__file__).resolve().parents[1] / "schema" / "dsl.schema.json"

#: pydantic 的错误类型 → 我们的规则 id
_RULE_BY_TYPE = {
    "missing": "required_missing",
    "extra_forbidden": "unknown_property",
    "string_type": "type_mismatch",
    "int_type": "type_mismatch",
    "float_type": "type_mismatch",
    "bool_type": "type_mismatch",
    "list_type": "type_mismatch",
    "dict_type": "type_mismatch",
    "value_error": "invalid_value",
    "greater_than_equal": "out_of_range",
    "less_than_equal": "out_of_range",
}


def _target_of(loc: tuple) -> str:
    """pydantic 的 `loc` → 人读的点号路径。

    空 loc 是顶层错误（比如 YAML 根本不是 mapping），给个 `<root>` 比给空串好 ——
    界面上一片空白等于没说在哪。
    """
    if not loc:
        return "<root>"
    return ".".join(str(part) for part in loc)


def check_dsl(data: Any) -> List[Issue]:
    """原始 dict → 诊断列表（不抛）。**一次报全**，不是报第一个。"""
    try:
        DslDocument.model_validate(data)
    except ValidationError as exc:
        return [_issue_from_error(err) for err in exc.errors()]
    return []


def _issue_from_error(error: Dict[str, Any]) -> Issue:
    kind = str(error.get("type", ""))
    rule = _RULE_BY_TYPE.get(kind, kind or "invalid")
    target = _target_of(tuple(error.get("loc") or ()))
    message = str(error.get("msg", ""))

    fix = ""
    if rule == "unknown_property":
        # 键名拼错是最常见的一类 —— 把"这一段允许哪些键"直接说出来，
        # 省得使用者去翻 schema
        fix = "键名拼错了；对照 schema/dsl.schema.json，或跑 `isa_gen ops` 看清单"
    elif rule == "required_missing":
        fix = "这一段是必填的"
    elif rule == "type_mismatch":
        fix = "类型不对；看 schema/dsl.schema.json 里该键的类型"

    return Issue(severity="error", category="schema", rule=rule,
                 message=message, target=target, fix=fix)


def check_dsl_text(text: str) -> List[Issue]:
    """YAML 文本 → 诊断列表。

    YAML 解析失败也是一条 Issue（而不是异常）—— 调用方要的是"这份 DSL 行不行"，
    解析不了也是"不行"的一种。
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [Issue(severity="error", category="schema", rule="yaml_parse_error",
                      message=f"YAML 解析失败：{exc}", target="<root>",
                      fix="检查缩进与引号")]
    if data is None:
        return [Issue(severity="error", category="schema", rule="empty_document",
                      message="文档是空的", target="<root>",
                      fix="至少要有 meta 段")]
    if not isinstance(data, dict):
        return [Issue(severity="error", category="schema", rule="not_a_mapping",
                      message=f"顶层必须是 mapping，拿到 {type(data).__name__}",
                      target="<root>", fix="顶层是一组键值对，不是列表或标量")]
    return check_dsl(data)


def load_dsl(text: str) -> DslDocument:
    """文本 → 模型。schema 不过就抛 `IsaGenError`（**汇总了所有的错**）。

    与 `check_dsl_text` 的分工：那个用于"只想看看行不行"（`run_validate`），
    这个用于"要用它"（编译）。后者不该在模型构建时才发现问题，
    所以先收集再抛 —— 报错信息里一次列全。
    """
    issues = check_dsl_text(text)
    errors = [i for i in issues if i.is_error]
    if errors:
        detail = "\n".join(f"  - {issue}" for issue in errors[:8])
        more = f"\n  …还有 {len(errors) - 8} 条" if len(errors) > 8 else ""
        raise IsaGenError(f"DSL 不合法（{len(errors)} 处）：\n{detail}{more}")
    data = yaml.safe_load(text)
    return DslDocument.model_validate(data)


# ═══════════════════════════════════════════════════════════════
# 契约文件的生成与核对
# ═══════════════════════════════════════════════════════════════

def generated_schema() -> Dict[str, Any]:
    """从 pydantic 模型现推的 JSON Schema —— `schema/dsl.schema.json` 的真相。"""
    schema = DslDocument.model_json_schema()
    schema["$comment"] = (
        "**由 domain/dsl.py 的 pydantic 模型生成，不要手改。** "
        "改了模型跑 `python -m src.tools.generation.isa_gen_tools.schema.gen_dsl_schema`；"
        "tests/test_schema.py 会断言这份文件与模型一致。"
    )
    return schema


def schema_file_matches_model() -> Optional[str]:
    """文件与模型对不上时返回一句人话，对得上返回 None。"""
    if not DSL_SCHEMA_FILE.exists():
        return f"{DSL_SCHEMA_FILE.name} 不存在"
    try:
        on_disk = json.loads(DSL_SCHEMA_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"读不出来：{exc}"
    expected = generated_schema()
    if on_disk != expected:
        differing = sorted(k for k in set(on_disk) | set(expected)
                           if on_disk.get(k) != expected.get(k))
        return f"与模型不一致的顶层键：{differing}"
    return None
