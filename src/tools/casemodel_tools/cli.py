"""casemodel_tools 命令行入口。

    python -m src.tools.casemodel_tools.cli check    <模型.yaml>
    python -m src.tools.casemodel_tools.cli analyze  <模型.yaml> [--cases 真实case.yaml]
    python -m src.tools.casemodel_tools.cli generate <模型.yaml> [--format table|yaml|json|csv]
    python -m src.tools.casemodel_tools.cli matrix   <模型.yaml>
    python -m src.tools.casemodel_tools.cli tree     <模型.yaml>
    python -m src.tools.casemodel_tools.cli rules
    python -m src.tools.casemodel_tools.cli uvm-tests <模型.yaml> [-d 维度] [--max-tests N]

退出码：有 error → 1；模型结构非法 / 文件不存在 → 2；正常 → 0。

**本包是纯工具，没有界面。** 界面在验证工作台里
（`src/workbench/modules/vms/casemodel/`），入口是 `vagent gui run -m vms.casemodel`
或 `vagent case-model gui` —— 那两条在主 CLI 里，不在这里。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── UTF-8 强制编码 ──
# 报告里有 ✓ / ✗ / ★ / █ 这些字符，而 Windows 控制台默认是 GBK：不转的话
# `analyze` / `tree` 会在 print 那一步抛 UnicodeEncodeError（用户看到的是
# 一段 traceback，而不是报告）。主 CLI 里也有同样的一段（`src/cli/commands.py`）。
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from .analysis import AnalysisResult, analyze_file, rule_docs
from .analysis.schema_check import SchemaChecker, collect_yaml_paths
from .domain import CaseModelError
from .domain.errors import CaseListError
from .generation import generate
from .repository import load_model
from .repository.exporters import EXPORT_FORMATS, export_cases
from . import text as T

__version__ = "2.0"

#: 示例模型放在 **`config/casemodel/examples/`**，不放在本包内。
#: 理由：这些 YAML 同时被本工具的命令行与验证工作台（`src/workbench`）使用，
#: 而两边**谁都不该依赖对方** —— 工具包要能在不装 Qt、不装工作台的环境里单独
#: 用。数据放在包外，两边都只往上指一层，谁也不用 import 谁。
#: （`config*` 已在 pyproject 的打包规则里，随包一起走。）
EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "config" / "casemodel" / "examples"


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
    # 多对象（tests: 列表）时每个对象各生成一套，case_id 前缀各自独立
    from .analysis.multi import generate_many
    from .repository import load_models

    gen = generate_many(load_models(args.model), seed=args.seed,
                        max_cases=args.max_cases)
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
# uvm-tests —— 把属性取值摊平成 UVM 的 environment.tests 片段
# ════════════════════════════════════════════════════════════

def cmd_uvm_tests(args: argparse.Namespace) -> int:
    """导出 `tool_uvm` 认的 `tests:` 片段（**一条 = 一个 UVM_TEST = 一个属性取值**）。

    产出的是一段 YAML 文本，贴进 env 清单的 `environment:` 下即可 ——
    本工具与 `uvm_tools` 之间**只是文件格式契约**，互不 import。
    """
    from .api import run_uvm_tests

    # run_uvm_tests 吃的是文本，这里就给它文本 —— 不要再 load 一遍模型，
    # 那等于同一个文件读两次、两条路径两处真相
    payload = run_uvm_tests(Path(args.model).read_text(encoding="utf-8"),
                            dimensions=args.dimension or None,
                            max_tests=args.max_tests)
    if payload.get("error"):
        print(f"模型无法构建: {payload['error']}", file=sys.stderr)
        return 2

    if args.out:
        Path(args.out).write_text(payload["tests_yaml"], encoding="utf-8")
        print(f"已写出 {payload['count']} 条属性测试 → {args.out}")
    else:
        print(f"# {payload['count']} 条属性测试"
              f"（维度：{'、'.join(payload['dimensions_used']) or '无'}）")
        print(payload["tests_yaml"], end="")
    for note in payload["notes"]:
        print(f"  注意: {note}", file=sys.stderr)
    return 0


# ════════════════════════════════════════════════════════════
# covergroups —— 覆盖点 → SystemVerilog covergroup
# ════════════════════════════════════════════════════════════

def cmd_covergroups(args: argparse.Namespace) -> int:
    """功能覆盖率方法学：模型的覆盖点 → 能编译的 covergroup。

    维度 → covergroup、字段 → coverpoint、取值点 → bin、可组合的 cross_pair →
    cross。规则与取舍见 `coverage.py` 的模块头（方法学的唯一出处）。
    """
    from .api import run_covergroups

    payload = run_covergroups(Path(args.model).read_text(encoding="utf-8"),
                              args.module)
    if payload.get("error"):
        print(f"模型无法构建: {payload['error']}", file=sys.stderr)
        return 2

    if args.out:
        Path(args.out).write_text(payload["covergroup_code"], encoding="utf-8")
        print(f"已写出 covergroup → {args.out}"
              f"（{payload['coverpoint_count']} 覆盖点 / {payload['bin_count']} bin"
              f" / {payload['cross_count']} cross）")
    else:
        print(f"// {payload['coverpoint_count']} 覆盖点 / {payload['bin_count']} bin"
              f" / {payload['cross_count']} cross", file=sys.stderr)
        print(payload["covergroup_code"], end="")
    for note in payload["notes"]:
        print(f"  注意: {note}", file=sys.stderr)
    return 0


# ════════════════════════════════════════════════════════════
# coverage-plan —— 一份完整的功能覆盖率计划
# ════════════════════════════════════════════════════════════

def cmd_coverage_plan(args: argparse.Namespace) -> int:
    """功能覆盖率计划：覆盖点 + 批次 + **种子管理** + 需求追溯，一份 yaml。

    与 `covergroups` 的区别：那个出的是**给编译器**的 SV；这个出的是**给人看、
    给回归吃**的计划书 —— §3 覆盖点、§5 批次、§6 种子、§8 追溯四张表摆在一起，
    "声明了 12 个覆盖点、回归里只跑 8 条"这种事才看得出来。
    """
    from .api import run_coverage_plan

    payload = run_coverage_plan(Path(args.model).read_text(encoding="utf-8"),
                                args.module)
    if payload.get("error"):
        print(f"模型无法构建: {payload['error']}", file=sys.stderr)
        return 2

    if args.out:
        Path(args.out).write_text(payload["plan_yaml"], encoding="utf-8")
        print(f"已写出覆盖率计划 → {args.out}")
    else:
        print(payload["plan_yaml"], end="")
    notes = payload["plan"]["notes"]
    for note in notes:
        print(f"  注意: {note}", file=sys.stderr)
    return 0


# ════════════════════════════════════════════════════════════
# associate —— 三层模型的关联校验
# ════════════════════════════════════════════════════════════

def cmd_associate(args: argparse.Namespace) -> int:
    """case / 覆盖率 / 约束 三份 yaml 的**关联**：连上了什么、哪里断了。

    四条边都靠**名字**对齐（见 `associate.py` 的模块头）。有 error 时退出码 1 ——
    "关联断了"不是警告，是这组模型渲染不出可信的 SV。
    """
    from .associate import associate

    payload = associate(
        Path(args.cases).read_text(encoding="utf-8"),
        Path(args.coverage).read_text(encoding="utf-8"),
        Path(args.constraint).read_text(encoding="utf-8") if args.constraint else "")
    if payload.get("error"):
        print(f"关联失败: {payload['error']}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_association(payload)
    for note in payload["notes"]:
        print(f"  注意: {note}", file=sys.stderr)
    return 1 if payload["counts"]["error"] else 0


def _print_association(payload: dict) -> None:
    print(f"关联：{payload['summary']}")
    c = payload["counts"]
    print(f"  case 字段（有 cover_bins）{c['case_fields_with_bins']} / "
          f"覆盖点 {c['coverage_coverpoints']} / bin {c['coverage_bins']} / "
          f"矩阵键 {c['matrix_keys']} / 交叉 {c['crosses']}")
    links = payload["links"]["coverpoints"]
    if links:
        print()
        print("覆盖点 → case 字段：")
        for l in links:
            print(f"  {l['coverpoint']:22s} ← {l['case_field'] or '（没关联上）'}")
    if payload["links"]["methods"]:
        print()
        print("专题 → 约束形态：")
        for m in payload["links"]["methods"]:
            print(f"  {m['theme']:14s} method={m['method']:5s} → {m['constraint_form']}")
    if payload["issues"]:
        print()
        print(f"关联问题 {len(payload['issues'])} 处：")
        for i in payload["issues"]:
            print(f"  [{i['severity']:7s}] 边{i['edge']} {i['subject']}")
            print(f"            {i['message']}")


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

    p = sub.add_parser("uvm-tests",
                       help="导出 UVM 的 environment.tests 片段（一条 = 一个 UVM_TEST）")
    p.add_argument("model", help="case 模型 YAML")
    p.add_argument("--dimension", "-d", action="append", metavar="ID",
                   help="只要这些维度（按 id / 名称 / key 匹配）；可重复")
    p.add_argument("--max-tests", type=int, default=32, dest="max_tests",
                   help="最多导出多少条（默认 32；优先保留边界取值，截断会记账）")
    p.add_argument("--out", "-o", help="输出文件（缺省打到 stdout）")
    p.set_defaults(func=cmd_uvm_tests)

    p = sub.add_parser("covergroups",
                       help="覆盖点 → SystemVerilog covergroup（功能覆盖率方法学）")
    p.add_argument("model", help="case 模型 YAML")
    p.add_argument("--module", "-m", default="dut",
                   help="covergroup 名字里的模块名（默认 dut）")
    p.add_argument("--out", "-o", help="把 covergroup 写到文件（缺省打到 stdout）")
    p.set_defaults(func=cmd_covergroups)

    p = sub.add_parser("associate",
                       help="case / 覆盖率 / 约束 三份 yaml 的关联校验（四条边）")
    p.add_argument("cases", help="case 模型 YAML")
    p.add_argument("coverage", help="功能覆盖率模型 YAML")
    p.add_argument("--constraint", "-c", help="约束模型 YAML（可选）")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_associate)

    p = sub.add_parser("coverage-plan",
                       help="功能覆盖率计划：覆盖点 + 批次 + 种子管理 + 需求追溯")
    p.add_argument("model", help="case 模型 YAML")
    p.add_argument("--module", "-m", default="dut", help="模块名（默认 dut）")
    p.add_argument("--out", "-o", help="把计划写到文件（缺省打到 stdout）")
    p.set_defaults(func=cmd_coverage_plan)

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
