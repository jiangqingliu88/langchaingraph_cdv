"""SchemaChecker —— case 属性模型的 YAML schema 语法检查。

归在 analysis 层而不是 repository：它产出的是诊断（Issue），
与 rules/ 下的语义规则同层；repository 只负责「把文档读成领域对象」，
不产出诊断。

用 JSON Schema（schema/case_model.schema.json）在原始 YAML 层校验
键名 / 类型 / 必填 / 枚举 / 类型化字段的取值表形状。

这一层只回答「文档写对了吗」。至于「引用指向的维度是否存在」
「维度名是不是把字段当维度了」这类语义问题，交给 completeness.py ——
分工与 uvm_tools 的 schema_check / semantic_check 一致。

severity 映射：本工具所有违规都是 error（模型是生成 case 的输入，
写错一个键就会静默生成一堆错 case，与「可复现·可审计」定位不符）。

用法:
    python -m src.tools.casemodel_tools.analysis.schema_check model.yaml
    python -m src.tools.casemodel_tools.analysis.schema_check -i config/casemodel/examples/ --json
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
    raise SystemExit("缺少依赖 PyYAML，请 pip install pyyaml") from exc

try:
    from jsonschema import Draft202012Validator
except ImportError as exc:  # pragma: no cover
    raise SystemExit("缺少依赖 jsonschema，请 pip install jsonschema") from exc

try:
    from .issues import CATEGORY_SCHEMA, Issue
except ImportError:  # pragma: no cover - 直接脚本运行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from analysis.issues import CATEGORY_SCHEMA, Issue

__version__ = "1.0"

SCHEMA_PATH = (Path(__file__).resolve().parent.parent / "schema"
               / "case_model.schema.json")
YAML_SUFFIXES = (".yaml", ".yml")

# ── jsonschema validator → (severity, rule_id, 中文前缀) ──
_VALIDATOR_INFO: Dict[str, tuple] = {
    "additionalProperties":  ("error", "unknown_property", "未知键"),
    "unevaluatedProperties": ("error", "unknown_property", "未知键"),
    "propertyNames":         ("error", "invalid_property_name", "键名非法"),
    "required":              ("error", "missing_required", "必填字段缺失"),
    "type":                  ("error", "type_mismatch", "类型不匹配"),
    "enum":                  ("error", "invalid_enum", "非法枚举值"),
    "const":                 ("error", "invalid_const", "非法取值"),
    "pattern":               ("error", "invalid_pattern", "格式不匹配"),
    "minLength":             ("error", "empty_value", "空值"),
    "minItems":              ("error", "too_few_items", "条目数不足"),
    "maxItems":              ("error", "too_many_items", "条目数过多"),
    "minProperties":         ("error", "empty_object", "对象为空"),
    "minimum":               ("error", "out_of_range", "取值越界"),
    "exclusiveMinimum":      ("error", "out_of_range", "取值越界"),
    "anyOf":                 ("error", "unknown_document_kind", "非法文档结构"),
    "oneOf":                 ("error", "ambiguous_value", "取值无法归类"),
    "allOf":                 ("error", "schema_violation", "schema 违规"),
    "not":                   ("error", "forbidden_property", "不允许的键"),
}
_DEFAULT_INFO = ("error", "schema_violation", "schema 违规")

# additionalProperties 的违规键只在 message 里（json_path 指向容器）
# 例: "Additional properties are not allowed ('widht' was unexpected)"
_ADDPROP_RE = re.compile(r"\((?P<names>[^()]*?)\s+(?:was|were|is|are)\s+unexpected\)")
_QUOTED_RE = re.compile(r"'([^']+)'")
_REQUIRED_RE = re.compile(r"'([^']+)' is a required property")


def _info(validator: str) -> tuple:
    return _VALIDATOR_INFO.get(validator, _DEFAULT_INFO)


def _json_path_str(error: Any) -> str:
    """json_path 归一化：去 '$.' 前缀，'$' → <root>。"""
    p = error.json_path or "$"
    if p == "$":
        return "<root>"
    return p[2:] if p.startswith("$.") else p


def _target(error: Any, path: Path) -> str:
    return f"{path.name}::{_json_path_str(error)}"


def _unexpected_names(error: Any) -> List[str]:
    m = _ADDPROP_RE.search(error.message)
    return _QUOTED_RE.findall(m.group("names")) if m else []


def _required_keys(error: Any) -> List[str]:
    return _REQUIRED_RE.findall(error.message)


def _forbidden_keys(schema: Any) -> List[str]:
    """从 `not` 分支里挖出被禁止的键名（required / anyOf[required] 两种写法）。"""
    keys: List[str] = []
    if isinstance(schema, dict):
        for k in schema.get("required") or []:
            keys.append(str(k))
        for sub in schema.get("anyOf") or []:
            keys.extend(_forbidden_keys(sub))
    return keys


def _flatten_context(error: Any) -> List[Any]:
    """递归展开 anyOf/oneOf/allOf 的粗粒度错误到叶错误。"""
    if not error.context:
        return [error]
    flat: List[Any] = []
    for ctx in error.context:
        flat.extend(_flatten_context(ctx))
    return flat


def _expand_composite(error: Any, path: Path) -> List[Issue]:
    """展开非顶层 anyOf/oneOf/allOf 失败到可操作的叶错误。

    - 丢弃「纯 type 不匹配」的分支噪音：oneOf 里的多类型分支（如 [string, object]）
      值不匹配的分支只产生 "is not of type" 噪音，真正原因在匹配类型的分支里。
    - 同一容器上多个 required 叶（如 range 的 min/max）合并为一条。
    - 结果去重。
    """
    branches = [_flatten_context(c) for c in error.context]
    substantive = [b for b in branches if any(l.validator != "type" for l in b)]
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
    seen: set = set()
    for group in required_groups.values():
        first = group[0]
        keys = sorted({k for l in group for k in _required_keys(l)})
        if len(keys) >= 2:
            msg = f"必填字段缺失（{' / '.join(keys)} 至少填一个）"
        else:
            msg = f"必填字段缺失: {first.message}"
        issues.append(Issue("error", "missing_required", _target(first, path), msg,
                            CATEGORY_SCHEMA))
    for leaf in others:
        issues.extend(translate_error(leaf, path))

    deduped: List[Issue] = []
    for i in issues:
        key = (i.severity, i.rule, i.target, i.message)
        if key not in seen:
            seen.add(key)
            deduped.append(i)
    return deduped


def translate_error(error: Any, path: Path) -> List[Issue]:
    """一条 ValidationError → N 条 Issue。"""
    if error.validator in ("anyOf", "oneOf", "allOf") and error.context:
        # 顶层（absolute_path 为空）的文档类型检查保留粗粒度报告
        if not list(error.absolute_path):
            severity, rule, prefix = _info(error.validator)
            return [Issue(severity, rule, _target(error, path),
                          f"{prefix}: {error.message}", CATEGORY_SCHEMA)]
        return _expand_composite(error, path)

    severity, rule, prefix = _info(error.validator)
    base = _target(error, path)

    # 未知键：从 message 扇出，每个违规键一条
    if error.validator in ("additionalProperties", "unevaluatedProperties"):
        names = _unexpected_names(error)
        if names:
            container = _json_path_str(error)
            return [
                Issue(severity, rule,
                      f"{path.name}::{container + '.' + n if container != '<root>' else n}",
                      f"{prefix} '{n}': {error.message}", CATEGORY_SCHEMA)
                for n in names
            ]

    # not：jsonschema 只报 "should not be valid under {...}"，把键名挖出来才好懂。
    # 只报「确实写了」的那些键 —— schema 里 forbid 的是全集，写出来的才是真问题。
    if error.validator == "not":
        keys = _forbidden_keys(error.validator_value)
        present = keys
        if isinstance(error.instance, dict):
            written = [k for k in keys if k in error.instance]
            present = written or keys
        if present:
            return [Issue(severity, rule, base,
                          f"{prefix} {' / '.join(present)}：该字段类型不支持此键"
                          f"（type={_sibling_type(error)}）", CATEGORY_SCHEMA)]

    # required 在 oneOf/enum 语境下可能一次报多个键
    if error.validator == "required":
        keys = _required_keys(error)
        if keys:
            return [Issue(severity, rule, base,
                          f"{prefix}: {' / '.join(keys)}", CATEGORY_SCHEMA)]

    return [Issue(severity, rule, base, f"{prefix}: {error.message}", CATEGORY_SCHEMA)]


def _sibling_type(error: Any) -> str:
    """取出错字段自己的 type 值，用来把「不允许的键」说得具体些。"""
    node = error.instance
    if isinstance(node, dict):
        return str(node.get("type", "?"))
    return "?"


def load_schema(schema_path: Path = SCHEMA_PATH) -> Dict[str, Any]:
    """读取并加载 JSON Schema（check_schema 自检，坏 schema 直接退出）。"""
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"加载 schema 失败 {schema_path}: {exc}") from exc
    Draft202012Validator.check_schema(schema)
    return schema


def collect_yaml_paths(inputs: Iterable[Path]) -> List[Path]:
    """文件/目录 → YAML 文件列表（目录递归，按路径排序保证可复现）。"""
    found: List[Path] = []
    for p in inputs:
        if p.is_dir():
            found.extend(sorted(q for q in p.rglob("*")
                                if q.is_file() and q.suffix.lower() in YAML_SUFFIXES))
        elif p.is_file():
            found.append(p)
    seen: set = set()
    out: List[Path] = []
    for p in found:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)
    return out


class SchemaChecker:
    """YAML → JSON Schema 校验入口。"""

    def __init__(self, schema_path: Path = SCHEMA_PATH) -> None:
        self.schema = load_schema(schema_path)
        self.validator = Draft202012Validator(self.schema)

    def check_data(self, data: Any, path: Path) -> List[Issue]:
        if not isinstance(data, dict):
            return [Issue("error", "unknown_document_kind", path.name,
                          f"顶层必须是 mapping（当前为 {type(data).__name__}），"
                          f"模型无法构建", CATEGORY_SCHEMA)]
        issues: List[Issue] = []
        for error in self.validator.iter_errors(data):
            issues.extend(translate_error(error, path))
        return issues

    def check_file(self, path: Path) -> List[Issue]:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return [Issue("error", "yaml_parse_error", path.name,
                          f"YAML 解析失败: {exc}", CATEGORY_SCHEMA)]
        except OSError as exc:
            return [Issue("error", "read_error", path.name,
                          f"读取失败: {exc}", CATEGORY_SCHEMA)]
        return self.check_data(data, path)

    def check_text(self, text: str, name: str = "<编辑器>") -> List[Issue]:
        """从文本校验 —— 编辑器在保存前用它，不必先落盘。"""
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            return [Issue("error", "yaml_parse_error", name,
                          f"YAML 解析失败: {exc}", CATEGORY_SCHEMA)]
        return self.check_data(data, Path(name))

    def check(self, inputs: Iterable[Path]) -> List[Issue]:
        issues: List[Issue] = []
        for path in collect_yaml_paths(inputs):
            issues.extend(self.check_file(path))
        return issues


def format_issues(issues: Iterable[Issue]) -> str:
    return "\n".join(str(i) for i in issues)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="casemodel schema_check",
        description="按 schema/case_model.schema.json 校验 case 属性模型 YAML。"
                    "所有违规（含未知键）都是 error。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("inputs", nargs="*", help="YAML 文件或目录（等价 -i）")
    parser.add_argument("-i", "--input", nargs="+", default=None,
                       help="YAML 文件或目录")
    parser.add_argument("-q", "--quiet", action="store_true",
                       help="只打印摘要")
    parser.add_argument("--json", "-j", dest="json_output", action="store_true",
                       help="输出 JSON")
    parser.add_argument("--report", metavar="PATH", help="把报告写到文件")
    parser.add_argument("--schema", metavar="PATH", help="覆盖 JSON Schema 路径")
    args = parser.parse_args(argv)

    schema_path = Path(args.schema).expanduser().resolve() if args.schema else SCHEMA_PATH
    checker = SchemaChecker(schema_path)

    flagged = [Path(x).expanduser() for x in args.input] if args.input else []
    input_paths = [Path(x).expanduser() for x in args.inputs] + flagged or [Path(".")]
    yaml_files = collect_yaml_paths(input_paths)
    if not yaml_files:
        print("schema_check: 输入路径下没有找到 YAML 文件", file=sys.stderr)
        return 1

    issues = checker.check(input_paths)
    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if i.severity == "warning"]
    summary = f"schema check: {len(errors)} error(s), {len(warnings)} warning(s)"

    if args.json_output:
        print(json.dumps({
            "schema": str(schema_path),
            "files": [str(f) for f in yaml_files],
            "summary": {"error": len(errors), "warning": len(warnings)},
            "issues": [{"severity": i.severity, "rule": i.rule, "target": i.target,
                        "message": i.message, "category": i.category} for i in issues],
        }, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    body = format_issues(issues)
    if not args.quiet and body:
        print(body)
    print(summary)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            "Case model schema check report\n" + body + "\n" + summary + "\n",
            encoding="utf-8")
        if not args.quiet:
            print(f"Report: {report_path}")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
