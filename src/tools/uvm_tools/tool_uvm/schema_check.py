"""SchemaChecker —— YAML schema 语法检查（独立命令，不接入生成流程）。

用 JSON Schema（schema/uvm_config.schema.json）在原始 YAML 层校验
键名 / 类型 / 必填 / 枚举。很多错误会被 normalizer 静默吞掉
（如缺 name/type 的 harness interface 条目被直接丢弃），schema 层先拦一道。

严重度映射：所有违规（含 unknown key / additionalProperties）→ error。
退出码：存在 error → 1；无 error → 0（与 semantic_check 的阻断语义一致）。

用法:
    python -m src.tools.uvm_tools.tool_uvm.schema_check -i examples/*.yaml
    python -m src.tools.uvm_tools.tool_uvm.schema_check -i examples/ --report schema_report.txt
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Missing dependency: PyYAML. Install with: pip install pyyaml") from exc

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install with: pip install jsonschema") from exc

# 双重导入守卫（与 gen_uvm.py:32-35 相同，兼容 python -m 与直接脚本两种路径）
try:
    from .semantic_check import Issue
    from .gen_uvm import YAMLLoader
except ImportError:
    from semantic_check import Issue
    from gen_uvm import YAMLLoader

__version__ = "1.0"

SCHEMA_PATH = Path(__file__).resolve().parent / "schema" / "uvm_config.schema.json"

# ── jsonschema validator → (severity, rule_id, 中文前缀) ──
#   严重度不在 schema 里编码，保持 schema 可被编辑器/IDE 直接复用
_VALIDATOR_INFO: Dict[str, tuple] = {
    # 未知键一律 error：拼错的键会被 normalizer 静默吞掉（配置看似生效实则失效），
    # 与「可复现·可审计」定位不符，直接在 schema 层阻断。
    "additionalProperties":   ("error",   "unknown_property", "未知键"),
    "unevaluatedProperties":  ("error",   "unknown_property", "未知键"),
    "required":               ("error",   "missing_required", "必填字段缺失"),
    "type":                   ("error",   "type_mismatch", "类型不匹配"),
    "enum":                   ("error",   "invalid_enum", "非法枚举值"),
    "const":                  ("error",   "invalid_const", "非法取值"),
    "anyOf":                  ("error",   "unknown_document_kind", "非法文档结构"),
    "oneOf":                  ("error",   "ambiguous_value", "取值无法归类"),
    "minLength":              ("error",   "empty_value", "空值"),
    "minItems":               ("error",   "too_few_items", "条目数不足"),
    # not: 显式拒绝已下线字段（如 interface.config.is_active）
    "not":                    ("error",   "removed_field", "已下线字段"),
}
_DEFAULT_INFO = ("error", "schema_violation", "schema 违规")

# additionalProperties 的违规键名只在 message 里（json_path 指向容器），
# 例: "Additional properties are not allowed ('widht' was unexpected)"
_ADDPROP_RE = re.compile(r"\((?P<names>[^()]*?)\s+(?:was|were|is|are)\s+unexpected\)")
_QUOTED_RE = re.compile(r"'([^']+)'")


def _validator_info(validator: str) -> tuple:
    return _VALIDATOR_INFO.get(validator, _DEFAULT_INFO)


def _extract_unexpected_names(error: Any) -> List[str]:
    """从 additionalProperties 消息解析违规键名；失败返回空列表（回退单条 issue）。"""
    m = _ADDPROP_RE.search(error.message)
    if not m:
        return []
    return _QUOTED_RE.findall(m.group("names"))


def _json_path_str(error: Any) -> str:
    """json_path 归一化：去 '$.' 前缀，'$' → '<root>'。"""
    p = error.json_path or "$"
    if p == "$":
        return "<root>"
    return p[2:] if p.startswith("$.") else p


def target_for(error: Any, path: Path) -> str:
    """Issue target：文件名 + "::" + json_path（additionalProperties 的键名由调用方拼接）。"""
    return f"{path.name}::{_json_path_str(error)}"


_REQUIRED_RE = re.compile(r"'([^']+)' is a required property")


def _flatten_context(error: Any) -> List[Any]:
    """递归展开 anyOf/oneOf/allOf 的粗粒度错误到叶错误（enum/type/required/...）。"""
    if not error.context:
        return [error]
    flat: List[Any] = []
    for ctx in error.context:
        flat.extend(_flatten_context(ctx))
    return flat


def _required_keys(error: Any) -> List[str]:
    return _REQUIRED_RE.findall(error.message)


def _expand_composite(error: Any, path: Path) -> List[Issue]:
    """展开非顶层 anyOf/oneOf/allOf 失败到可操作的叶错误。

    - 丢弃「纯 type 不匹配」的分支噪音：oneOf 里多类型分支（如 [object, array]）
      值不匹配的分支只产生 "is not of type" 噪音，真正原因在匹配类型的分支里；
      仅当所有分支都只有 type 错误时才保留 type 错误。
    - 同一容器上多个 required 叶（别名二选一，如 name|agent_name）合并为一条。
    - 结果去重（同一叶错误可能经多个分支重复出现）。
    """
    branches = [_flatten_context(c) for c in error.context]
    substantive = [b for b in branches
                   if any(l.validator != "type" for l in b)]
    leaves = [l for b in (substantive or branches) for l in b]

    from collections import defaultdict
    required_groups: Dict[tuple, List[Any]] = defaultdict(list)
    others: List[Any] = []
    for leaf in leaves:
        if leaf.validator == "required":
            required_groups[tuple(leaf.absolute_path)].append(leaf)
        else:
            others.append(leaf)

    issues: List[Issue] = []
    seen = set()
    for group in required_groups.values():
        first = group[0]
        keys = sorted({k for l in group for k in _required_keys(l)})
        if len(keys) >= 2:
            msg = f"必填字段缺失（{' / '.join(keys)} 至少填一个）"
        else:
            msg = f"必填字段缺失: {first.message}"
        issues.append(Issue("error", "missing_required",
                            target_for(first, path), msg))
    for leaf in others:
        issues.extend(translate_error(leaf, path))  # 叶可能仍是嵌套组合错误

    deduped: List[Issue] = []
    for i in issues:
        key = (i.severity, i.rule, i.target, i.message)
        if key not in seen:
            seen.add(key)
            deduped.append(i)
    return deduped


def translate_error(error: Any, path: Path) -> List[Issue]:
    """一条 ValidationError → N 条 Issue（additionalProperties 多键扇出 + 组合错误递归到叶）。"""
    # anyOf/oneOf/allOf 分支失败：jsonschema 只报粗粒度消息，具体原因在 context。
    # 顶层（absolute_path 为空）的文档类型检查保留粗粒度报告（unknown_document_kind）；
    # 其余展开到叶错误，避免"is not valid under any of the given schemas"吞掉细节。
    if error.validator in ("anyOf", "oneOf", "allOf") and error.context:
        if not list(error.absolute_path):
            severity, rule, prefix = _validator_info(error.validator)
            return [Issue(severity, rule, target_for(error, path),
                          f"{prefix}: {error.message}")]
        return _expand_composite(error, path)

    severity, rule, prefix = _validator_info(error.validator)
    base_target = target_for(error, path)

    # unknown key：从 message 扇出每个违规键一条 warning
    if error.validator in ("additionalProperties", "unevaluatedProperties"):
        names = _extract_unexpected_names(error)
        if names:
            container = _json_path_str(error)
            return [
                Issue(
                    severity=severity,
                    rule=rule,
                    target=f"{path.name}::{container + '.' + n if container != '<root>' else n}",
                    message=f"{prefix} '{n}': {error.message}",
                )
                for n in names
            ]
        return [Issue(severity, rule, base_target,
                      f"{prefix}: {error.message}")]

    return [Issue(severity, rule, base_target, f"{prefix}: {error.message}")]


def load_schema(schema_path: Path = SCHEMA_PATH) -> Dict[str, Any]:
    """读取并加载 JSON Schema（check_schema 自检，坏 schema 直接 SystemExit）。"""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Failed to load schema {schema_path}: {exc}") from exc
    Draft202012Validator.check_schema(schema)
    return schema


class SchemaChecker:
    """YAML schema 语法检查入口。"""

    def __init__(self, schema_path: Path = SCHEMA_PATH) -> None:
        self.schema = load_schema(schema_path)
        self.validator = Draft202012Validator(self.schema)

    def check(self, inputs: Iterable[Path]) -> List[Issue]:
        """收集 *.yaml/*.yml → 逐文件校验 → Issue 列表（YAML 解析失败亦为 error issue）。"""
        issues: List[Issue] = []
        for path in YAMLLoader.collect_paths(inputs):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError as exc:
                issues.append(Issue("error", "yaml_parse_error", path.name,
                                    f"YAML 解析失败: {exc}"))
                continue
            if not isinstance(data, dict):
                issues.append(Issue("error", "unknown_document_kind", path.name,
                                    f"顶层必须是 mapping（当前为 {type(data).__name__}），"
                                    f"生成器会跳过该文档"))
                continue
            for error in self.validator.iter_errors(data):
                issues.extend(translate_error(error, path))
        return issues


def format_issues(issues: List[Issue]) -> str:
    return "\n".join(str(i) for i in issues)


_checker_cache: Dict[Path, "SchemaChecker"] = {}


def get_checker(schema_path: Path = SCHEMA_PATH) -> "SchemaChecker":
    """带缓存的校验器 —— **进程内复用同一个实例**。

    给"界面上一张审查台要连着校验好几份 YAML"这种用法：`SchemaChecker.__init__`
    每次都要读盘 + `json.loads` + 建 `Draft202012Validator`，而 schema 是仓库里的
    静态文件，一个进程里 parse 一次就够。逐个文件新建实例纯属浪费。

    （`load_schema` 里那句"坏 schema 直接 SystemExit"照旧：坏 schema 是仓库级事故，
    不该被缓存悄悄吞掉。）
    """
    key = Path(schema_path)
    checker = _checker_cache.get(key)
    if checker is None:
        checker = SchemaChecker(key)
        _checker_cache[key] = checker
    return checker


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="schema_check.py",
        description="Validate tool_uvm YAML configs against the JSON Schema "
                    "(schema/uvm_config.schema.json). All violations are errors, "
                    "including unknown/extra keys.",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s (tool_uvm schema_check) {__version__}",
        help="Show script version number and exit.",
    )
    parser.add_argument(
        "inputs", nargs="*",
        help="YAML file(s) or directories (shorthand for -i/--input).",
    )
    parser.add_argument(
        "-i", "--input", nargs="+", default=None,
        help="Input YAML file(s) or directories containing YAML files.",
    )
    parser.add_argument(
        "-f", "--file", dest="input", nargs="+",
        help="Specify a list of YAML configuration files (same as -i/--input).",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress the per-issue lines, keep only the summary.",
    )
    parser.add_argument(
        "--report", metavar="PATH",
        help="Write the report (same text as printed) to PATH.",
    )
    parser.add_argument(
        "--schema", metavar="PATH",
        help="Override the JSON Schema file (default: schema/uvm_config.schema.json).",
    )
    args = parser.parse_args(argv)

    schema_path = Path(args.schema).expanduser().resolve() if args.schema else SCHEMA_PATH
    checker = SchemaChecker(schema_path)

    positional = [Path(x).expanduser() for x in args.inputs]
    flagged = [Path(x).expanduser() for x in args.input] if args.input else []
    input_paths = positional + flagged or [Path(".")]
    yaml_files = YAMLLoader.collect_paths(input_paths)
    if not yaml_files:
        print("schema_check: No YAML files were found in the input paths.",
              file=sys.stderr)
        return 1

    issues = checker.check(input_paths)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]

    body = format_issues(issues)
    if not args.quiet and body:
        print(body)
    summary = f"schema check: {len(errors)} error(s), {len(warnings)} warning(s)"
    print(summary)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "Schema check report (tool_uvm)\n" + body + "\n" + summary + "\n",
            encoding="utf-8")
        if not args.quiet:
            print(f"Report: {report_path}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
