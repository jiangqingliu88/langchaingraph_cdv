"""casemodel_tools 命令行入口。

    python -m src.tools.casemodel_tools.cli check    <模型.yaml>
    python -m src.tools.casemodel_tools.cli analyze  <模型.yaml> [--cases 真实case.yaml]
    python -m src.tools.casemodel_tools.cli generate <模型.yaml> [--format table|yaml|json|csv]
    python -m src.tools.casemodel_tools.cli matrix   <模型.yaml>
    python -m src.tools.casemodel_tools.cli tree     <模型.yaml>
    python -m src.tools.casemodel_tools.cli rules
    python -m src.tools.casemodel_tools.cli gui      [<模型.yaml>]

退出码：有 error → 1；模型结构非法 / 文件不存在 → 2；正常 → 0。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from .analysis import AnalysisResult, analyze_file, rule_docs
from .analysis.schema_check import SchemaChecker, collect_yaml_paths
from .domain import CaseModelError
from .domain.errors import CaseListError
from .generation import generate
from .repository import load_model
from .repository.exporters import EXPORT_FORMATS, export_cases
from .view import text as T

__version__ = "2.0"

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
DEFAULT_EXAMPLE = EXAMPLES_DIR / "cpu_pipeline.yaml"


# ════════════════════════════════════════════════════════════
# check
# ════════════════════════════════════════════════════════════

def cmd_check(args: argparse.Namespace) -> int:
    checker = SchemaChecker()
    payloads: List[Dict[str, Any]] = []
    total_errors = 0
    checked = 0

    inputs = [Path(x) for x in args.models]
    for path in inputs:
        if not path.exists():
            print(f"文件不存在: {path}", file=sys.stderr)
            total_errors += 1

    for path in collect_yaml_paths(inputs):
        checked += 1
        issues = checker.check_file(path)
        errors = [i for i in issues if i.is_error]
        total_errors += len(errors)
        payload = {
            # 与 agent 面的 casemodel_validate 保持同一形状
            "file": str(path),
            "valid": not errors,
            "error_count": len(errors),
            "warning_count": len(issues) - len(errors),
            "issues": [{"severity": i.severity, "category": i.category,
                        "rule": i.rule, "target": i.target, "message": i.message}
                       for i in issues],
        }
        if args.json:
            payloads.append(payload)
            continue
        print(f"── {path.name} ──")
        for issue in issues:
            print(f"   {issue}")
        print(f"   schema check: {payload['error_count']} error(s), "
              f"{payload['warning_count']} warning(s)")

    if not checked and not total_errors:
        print("check: 输入路径下没有找到 YAML 文件", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(payloads[0] if len(payloads) == 1 else payloads,
                         ensure_ascii=False, indent=2))
    return 1 if total_errors else 0


# ════════════════════════════════════════════════════════════
# analyze
# ════════════════════════════════════════════════════════════

def payload(result: AnalysisResult) -> Dict[str, Any]:
    """机器可读的完整产物 —— --json 与 agent 面共用。"""
    model = result.model
    return {
        "summary": result.summary(),
        "object": model.object,
        "object_cn": model.object_cn,
        "object_code": model.object_code,
        "layers": model.layer_rows(),
        "org_tree": result.node_rows(),
        "themes": result.theme_rows(),
        "score": {name: {"sub": round(sub, 4), "weighted": round(weighted, 2),
                         "reasons": result.score.reasons.get(key, [])}
                  for (name, sub, weighted), key in zip(result.score.rows(),
                                                        result.score.reasons)},
        "score_total": round(result.score.total, 1),
        "matrix": {
            "dimensions": [d.label for d in (result.matrix.dimensions
                                            if result.matrix else [])],
            "total_pairs": result.matrix.total_pairs() if result.matrix else 0,
            "declared_pairs": result.matrix.declared_count() if result.matrix else 0,
            "pairs": result.matrix.rows() if result.matrix else [],
        },
        "coverage": [
            {"dimension": d.key, "name": d.name, "hit": d.hit_count,
             "total": d.total, "ratio": round(d.ratio, 4),
             "fields": [{"field": f.field, "type": f.field_type,
                         "hit": f.hit_count, "total": f.total,
                         "missing": f.missing, "derived": f.derived}
                        for f in d.fields]}
            for d in result.dimension_coverage],
        "environment": {
            "required": result.model.env_required,
            "provided": result.model.case_defaults.environment,
        },
        "checks": {
            "declared": result.model.checks,
            "usage": {c: sum(1 for x in result.generation.cases if c in x.checks)
                      for c in result.model.checks},
        },
        "explosion": result.explosion,
        "issues": [{"severity": i.severity, "category": i.category, "rule": i.rule,
                    "target": i.target, "message": i.message}
                   for i in result.issues],
    }


def _analyze(args: argparse.Namespace) -> AnalysisResult:
    return analyze_file(args.model, cases=getattr(args, "cases", None),
                        seed=args.seed, max_cases=args.max_cases)


def cmd_analyze(args: argparse.Namespace) -> int:
    result = _analyze(args)
    if args.json:
        data = payload(result)
        if result.external is not None:
            data["external"] = result.external.to_dict()
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        body = T.report(result)
        print(body)
        if args.report:
            out = Path(args.report)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body + "\n", encoding="utf-8")
            print(f"\nReport: {out}")
    return 1 if result.errors else 0


# ════════════════════════════════════════════════════════════
# 局部视图
# ════════════════════════════════════════════════════════════

def cmd_matrix(args: argparse.Namespace) -> int:
    result = _analyze(args)
    print(T.render_matrix(result))
    return 1 if result.errors else 0


def cmd_tree(args: argparse.Namespace) -> int:
    result = _analyze(args)
    print(T.render_org_tree(result))
    print()
    print(T.render_themes(result))
    return 1 if result.errors else 0


def cmd_rules(args: argparse.Namespace) -> int:
    if args.json:
        print(json.dumps([{"rule": r, "severity": s, "category": c,
                           "description": d} for r, s, c, d in rule_docs()],
                         ensure_ascii=False, indent=2))
    else:
        print(T.render_rules())
    return 0


# ════════════════════════════════════════════════════════════
# generate
# ════════════════════════════════════════════════════════════

def cmd_generate(args: argparse.Namespace) -> int:
    model = load_model(args.model)
    gen = generate(model, seed=args.seed, max_cases=args.max_cases)
    body = export_cases(gen.cases, args.format, seed=gen.seed,
                        truncated=gen.truncated, dropped=gen.dropped,
                        notes=gen.notes, driver=gen.driver,
                        themes=gen.themes_used)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(body, encoding="utf-8")
        print(f"已写出 {gen.count} 个 case 属性表 → {out}")
        for note in gen.notes:
            print(f"  注意: {note}")
    else:
        print(body)
    return 0


# ════════════════════════════════════════════════════════════
# gui
# ════════════════════════════════════════════════════════════

def cmd_gui(args: argparse.Namespace) -> int:
    from .view.gui.app import main as gui_main
    target = args.model
    if not target and DEFAULT_EXAMPLE.exists():
        target = str(DEFAULT_EXAMPLE)
        print(f"未指定模型，加载示例: {target}")
    return gui_main([target] if target else [])


# ════════════════════════════════════════════════════════════
# 参数
# ════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="casemodel_tools",
        description="case 属性完备性建模 —— 功能组织树 + P0/P1/P2 专题 + "
                    "维度约束组合。文档见 readem.md。",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser, cases: bool = False) -> None:
        p.add_argument("model", help="case 模型 YAML")
        p.add_argument("--seed", type=int, default=None,
                       help="覆盖模型里的 generation.seed")
        p.add_argument("--max-cases", type=int, default=None, dest="max_cases",
                       help="覆盖模型里的 generation.max_cases")
        if cases:
            p.add_argument("--cases", metavar="PATH",
                           help="外部真实 case 列表（.yaml/.yml/.json/.csv），"
                                "做「模型 vs 实现」反向核对")

    p = sub.add_parser("check", help="只做 JSON Schema 校验（目录会递归）")
    p.add_argument("models", nargs="+", help="case 模型 YAML 或目录")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("analyze", help="全量完备性分析")
    common(p, cases=True)
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.add_argument("--report", metavar="PATH", help="把文本报告写到文件")
    p.set_defaults(func=cmd_analyze)

    p = sub.add_parser("matrix", help="只看维度交叉矩阵")
    common(p)
    p.set_defaults(func=cmd_matrix)

    p = sub.add_parser("tree", help="只看功能组织树与专题")
    common(p)
    p.set_defaults(func=cmd_tree)

    p = sub.add_parser("rules", help="列出全部校验规则")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_rules)

    p = sub.add_parser("generate", help="按属性组合生成 case 属性表")
    common(p)
    p.add_argument("--format", "-f", default="table", choices=list(EXPORT_FORMATS))
    p.add_argument("--out", "-o", help="输出文件（缺省打到 stdout）")
    p.set_defaults(func=cmd_generate)

    p = sub.add_parser("gui", help="打开 tkinter 分析界面")
    p.add_argument("model", nargs="?", default=None, help="case 模型 YAML（可省略）")
    p.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"文件不存在: {exc}", file=sys.stderr)
        return 2
    except (CaseModelError, CaseListError) as exc:
        print(f"无法构建: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # 典型场景：`… --format table | head` 把管道读端提前关掉。
        # 这不是工具的错误，安静退出即可，别抛 traceback 盖住真正的输出。
        if getattr(exc, "errno", None) in (22, 32):     # EINVAL / EPIPE
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
