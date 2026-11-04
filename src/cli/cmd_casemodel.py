"""SignOffAI CLI 命令组：用例建模（case-model）

从 `src/cli/commands.py` 拆出；导入本模块即把命令注册到 `cli`。
命令实现保持不变，便于逐步搬迁与回滚。
"""
from __future__ import annotations

import asyncio  # noqa: F401
import json
import sys  # noqa: F401
from datetime import datetime  # noqa: F401
from pathlib import Path

import click  # noqa: F401
from rich.panel import Panel  # noqa: F401
from rich.table import Table  # noqa: F401

from src.cli.output import common_options, get_output_adapter  # noqa: F401
from src.cli.commands import (  # noqa: F401
    cli, console,
    EXIT_OK, EXIT_FAIL, EXIT_USAGE, EXIT_WAITING, EXIT_STRICT,
    _repo, _resolve_run, _init_service, _find_run_id,
    _strict_semantic_gate,
    _extract_requirements_from_md, _get_git_info,
    _exclude_registry, _output_junit, _output_gitlab_ci,
    _checkpoint_db, _resume_closed_loop, _report_resume,
    _approver_name, _sha256_path, _write_approval_record, _decide,
)

@cli.group("case-model")
def case_model():
    """case 属性完备性建模（功能组织树 + P0/P1/P2 专题 + 维度约束组合）"""
    pass


@case_model.command("check")
@click.argument("models", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_check(models, json_output):
    """按 JSON Schema 校验 case 模型 YAML（语法 / 类型 / 必填 / 取值表形状）

    \b
    示例:
      vagent case-model check model.yaml            # 单文件
      vagent case-model check examples/             # 目录递归
    """
    out = get_output_adapter(json_output)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_check

    argv = ["check", *models] + (["--json"] if json_output else [])
    rc = cmd_check(build_parser().parse_args(argv))
    if rc and not json_output:
        out.print_error("schema check failed", code=rc)
    sys.exit(rc)


@case_model.command("lint")
@click.argument("model", type=click.Path(exists=True))
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_lint(model, json_output):
    """结构 lint：v2 分节 / manifest 展开 / 必填字段 / 引用形状。

    \b
    示例:
      vagent case-model lint specs/npu_sched/casemodel.yaml
      vagent case-model lint split/casemodel.yaml --json
    """
    from src.tools.generation.casemodel_tools.domain import CaseModelError
    from src.tools.generation.casemodel_tools.repository import load_models

    try:
        models = load_models(model)
    except CaseModelError as exc:
        if json_output:
            click.echo(json.dumps({"ok": False, "error": str(exc)},
                                  ensure_ascii=False))
        else:
            console.print(f"[red]FAIL[/red] {exc}")
        sys.exit(EXIT_FAIL)
    rows = [{
        "object": m.object,
        "object_code": m.object_code,
        "dimensions": len(m.dimensions),
        "themes": len(m.themes),
        "assertions": len(m.assertions),
        "scoreboards": len(m.scoreboards),
        "case_source": dict(m.case_source or {}),
    } for m in models]
    result = {"ok": True, "schema": "casemodel_lint_v1", "models": rows}
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, default=str))
        return
    console.print(f"[green]OK[/green] {Path(model).name} · {len(rows)} 个对象")
    for row in rows:
        console.print(
            f"  {row['object']} ({row['object_code']}) · "
            f"dims={row['dimensions']} themes={row['themes']} "
            f"sva={row['assertions']} scb={row['scoreboards']}")


@case_model.command("analyze")
@click.argument("model", type=click.Path(exists=True))
@click.option("--cases", "-c", "cases_file", type=click.Path(exists=True),
              help="外部真实 case 列表（.yaml/.yml/.json/.csv），做反向核对")
@click.option("--report", "-o", "report_path", type=click.Path(),
              help="把完整文本报告写到文件")
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_analyze(model, cases_file, report_path, seed, max_cases, json_output):
    """全量完备性分析：组织树 / 专题 / 正交性 / 交叉矩阵 / 取值覆盖 / 环境与检查

    \b
    示例:
      vagent case-model analyze model.yaml
      vagent case-model analyze model.yaml --cases real_cases.yaml
      vagent case-model analyze model.yaml --json -o report.txt
    """
    out = get_output_adapter(json_output)
    from src.tools.generation.casemodel_tools.analysis import analyze_file
    from src.tools.generation.casemodel_tools.cli import payload as _payload
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError
    from src.tools.generation.casemodel_tools import text as _text

    try:
        result = analyze_file(model, cases=cases_file, seed=seed,
                              max_cases=max_cases)

        if json_output:
            payload = _payload(result)
            if result.external is not None:
                payload["external"] = result.external.to_dict()
            out.print_result(payload, title="case 属性完备性分析")
        else:
            text = _text.report(result)
            click.echo(text)
            if report_path:
                Path(report_path).parent.mkdir(parents=True, exist_ok=True)
                Path(report_path).write_text(text + "\n", encoding="utf-8")
                out.print_success(f"报告已写出: {report_path}")

        # 有 error → 退出码 1，warning 不阻断（与独立 CLI 一致）
        sys.exit(1 if result.errors else 0)
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"分析失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("tree")
@click.argument("model", type=click.Path(exists=True))
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
def case_model_tree(model, seed, max_cases):
    """只看功能组织树与专题

    \b
    示例:
      vagent case-model tree model.yaml
    """
    out = get_output_adapter(False)
    try:
        from src.tools.generation.casemodel_tools.cli import build_parser, cmd_tree
        argv = ["tree", model]
        if seed is not None:
            argv += ["--seed", str(seed)]
        if max_cases is not None:
            argv += ["--max-cases", str(max_cases)]
        sys.exit(cmd_tree(build_parser().parse_args(argv)))
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"分析失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("rules")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_rules(json_output):
    """列出全部校验规则

    \b
    示例:
      vagent case-model rules
      vagent case-model rules --json
    """
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_rules
    argv = ["rules"] + (["--json"] if json_output else [])
    sys.exit(cmd_rules(build_parser().parse_args(argv)))


@case_model.command("generate")
@click.argument("model", type=click.Path(exists=True))
@click.option("--format", "-f", "fmt", default="table",
              type=click.Choice(["table", "yaml", "json", "csv"]), help="输出格式")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="输出文件（缺省打到 stdout）")
@click.option("--seed", type=int, default=None, help="覆盖模型里的 generation.seed")
@click.option("--max-cases", type=int, default=None, help="覆盖 generation.max_cases")
def case_model_generate(model, fmt, output_path, seed, max_cases):
    """按属性组合生成 case 属性表（专题 → 树节点 → 维度 → 方法 → 组合）

    \b
    示例:
      vagent case-model generate model.yaml -f yaml -o cases.yaml
      vagent case-model generate model.yaml -f csv  -o cases.csv
    """
    out = get_output_adapter(False)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_generate
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["generate", model, "--format", fmt, "--out", output_path or ""]
        if seed is not None:
            argv += ["--seed", str(seed)]
        if max_cases is not None:
            argv += ["--max-cases", str(max_cases)]
        sys.exit(cmd_generate(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)
    except Exception as exc:                      # noqa: BLE001
        out.print_error(f"生成失败: {exc}", code=2)
        sys.exit(2)


@case_model.command("uvm-tests")
@click.argument("model", type=click.Path(exists=True))
@click.option("--dimension", "-d", "dimensions", multiple=True,
              help="只要这些维度（按 id / 名称 / key 匹配）；可重复")
@click.option("--max-tests", type=int, default=32,
              help="最多导出多少条（默认 32；优先保留边界取值，截断会记账）")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="输出文件（缺省打到 stdout）")
def case_model_uvm_tests(model, dimensions, max_tests, output_path):
    """把属性取值摊平成 UVM 的 environment.tests 片段（一条 = 一个 UVM_TEST）

    产出的是一段 YAML 文本，贴进 env 清单的 `environment:` 下即可 ——
    本工具与 uvm_tools 之间只是**文件格式契约**，互不 import。

    \b
    示例:
      vagent case-model uvm-tests model.yaml -d D_ratio
      vagent case-model uvm-tests model.yaml -o tests.yaml
    """
    out = get_output_adapter(False)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_uvm_tests
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["uvm-tests", model, "--max-tests", str(max_tests)]
        for name in dimensions:
            argv += ["--dimension", name]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_uvm_tests(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("covergroups")
@click.argument("model", type=click.Path(exists=True))
@click.option("--module", "-m", default="dut",
              help="covergroup 名字里的模块名（默认 dut）")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="把 covergroup 写到文件（缺省打到 stdout）")
def case_model_covergroups(model, module, output_path):
    """覆盖点 → SystemVerilog covergroup（功能覆盖率方法学）

    维度 → covergroup、字段 → coverpoint、取值点 → bin、可组合的 cross_pair →
    cross。规则见 src/tools/generation/casemodel_tools/coverage.py 的模块头。

    与 `uvm-tests` 是同一份分母的两面：那边说"这些取值点各跑一条用例"（激励），
    这边说"这些取值点各收一个 bin"（度量）—— 两边的数对得上，闭环才成立。

    \b
    示例:
      vagent case-model covergroups model.yaml -m apb_uart
      vagent case-model covergroups model.yaml -o coverage/apb_uart_cg.sv
    """
    out = get_output_adapter(False)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_covergroups
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["covergroups", model, "--module", module]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_covergroups(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("associate")
@click.argument("cases", type=click.Path(exists=True))
@click.argument("coverage", type=click.Path(exists=True))
@click.option("--constraint", "-c", "constraint_path", type=click.Path(exists=True),
              help="约束模型 YAML（可选；给了才查边 ③④）")
@click.option("--json", "-j", "json_output", is_flag=True, help="纯 JSON 输出")
def case_model_associate(cases, coverage, constraint_path, json_output):
    """三层模型的关联校验：case / 功能覆盖率 / 约束

    三条边都靠**名字**对齐（不是位置、不是复制）：

    \b
      1  case.field.cover_bins  ->  coverage.coverpoints[].bins[].name
      2  case.cross_matrix 键   ->  coverage.crosses[].matrix_ref
      3/4 专题方法与约束层的策略 / 组合器

    有 error 时退出码 1 —— "关联断了"不是警告：这组模型渲染不出可信的 SV
    （取值投影不出来时给个 0 让 bin 照生成，收的是**错的数**，比生成不了更坏）。

    \b
    示例:
      vagent case-model associate cases.yaml coverage.yaml
      vagent case-model associate cases.yaml coverage.yaml -c constraint.yaml --json
    """
    out = get_output_adapter(json_output)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_associate
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["associate", cases, coverage]
        if constraint_path:
            argv += ["--constraint", constraint_path]
        if json_output:
            argv.append("--json")
        sys.exit(cmd_associate(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("constraints")
@click.argument("model", type=click.Path(exists=True))
@click.option("--port", "-p", "ports", multiple=True, metavar="NAME:TYPE",
              help="端口（agent 名 : seq_item 类型），如 "
                   "apb_master:APB_master_seq_item；可重复。**至少给一个**")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="把约束模型写到文件（缺省打到 stdout）")
def case_model_constraints(model, ports, output_path):
    """由 case 模型生成约束模型：专题的生成方法 → 策略 + 组合器（骨架）

    方法学的第三条腿：case 说「该测什么」、覆盖率说「怎么量」、**约束说
    「怎么驱动」**。这里把 `themes[].method`（D/G/SPCL/RND/RPLY）落成
    `policies` + `combinator`，产出正好是 `gen_uvm` 认的约束模型形状。

    出的是**骨架**：case 模型有建模语义（专题/维度/方法/优先级），没有协议参数
    （地址对齐/容量/握手时序）—— 所以策略体在 gen_uvm 里落成空 apply，逻辑由
    人补在 `env/cons/` 的策略里。

    端口要**显式给**：case 说字段名、约束说 agent 名 + seq_item 类型，端口名 ↔
    字段名的对应没有建模 —— 推不出来。不给端口就不生成（空 `transactions` 会渲
    染出一个空壳协调序列）。

    \b
    示例:
      vagent case-model constraints model.yaml -p apb_master:APB_master_seq_item
      vagent case-model constraints model.yaml -p cpu_master:CPU_seq_item \\
              -p dma_master:DMA_seq_item -o constraint.yaml
    """
    out = get_output_adapter(False)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_constraints
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["constraints", model]
        for spec in ports:
            argv += ["--port", spec]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_constraints(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("coverage-plan")
@click.argument("model", type=click.Path(exists=True))
@click.option("--module", "-m", default="dut", help="模块名（默认 dut）")
@click.option("--output", "-o", "output_path", type=click.Path(),
              help="把计划写到文件（缺省打到 stdout）")
def case_model_coverage_plan(model, module, output_path):
    """功能覆盖率计划：覆盖点 + 批次 + 种子管理 + 需求追溯

    与 `covergroups` 的分工：那个出的是**给编译器**的 SV；这个出的是**给人看、
    给回归吃**的计划书 —— §3 覆盖点 / §5 批次 / §6 种子 / §8 需求追溯四张表摆
    在一起，"声明了 12 个覆盖点、回归里只跑 8 条"这种事才看得出来。

    
    示例:
      vagent case-model coverage-plan model.yaml -m npu_sched
      vagent case-model coverage-plan model.yaml -o coverage_plan.yaml
    """
    out = get_output_adapter(False)
    from src.tools.generation.casemodel_tools.cli import build_parser, cmd_coverage_plan
    from src.tools.generation.casemodel_tools.domain import CaseModelError as _CaseModelError

    try:
        argv = ["coverage-plan", model, "--module", module]
        if output_path:
            argv += ["--out", output_path]
        sys.exit(cmd_coverage_plan(build_parser().parse_args(argv)))
    except _CaseModelError as exc:
        out.print_error(f"模型无法构建: {exc}", code=2)
        sys.exit(2)


@case_model.command("gui")
@click.argument("model", required=False, type=click.Path(exists=True))
def case_model_gui(model):
    """打开验证工作台并落在 case 建模模块上（不传模型则加载内置示例）

    \b
    示例:
      vagent case-model gui
      vagent case-model gui config/casemodel/examples/cpu_pipeline.yaml
    """
    try:
        from src.workbench.app import main as workbench_main
    except ImportError as exc:                    # PySide6 没装
        click.echo(
            "GUI 需要 PySide6，当前环境没有装：\n"
            f"  {exc}\n\n"
            "装法：pip install -e .[gui]　　或　　pip install PySide6\n"
            "（纯 CLI 用法 check / analyze / generate 不需要它）",
            err=True)
        sys.exit(2)
    argv = ["--module", "vms.casemodel"]
    if model:
        argv += ["--input", str(model)]
    sys.exit(workbench_main(argv))


# ═══════════════════════════════════════════════════════════════
# 人工变更证据链 —— 无 GUI 的那一半
# ═══════════════════════════════════════════════════════════════
#
# 界面上的「保存」会自动记账；在终端里用编辑器改文件**没有那个钩子**，所以
# 无 GUI 时这套东西等于不存在。这一组就是补那一半。
#
# 三条命令里 `check` 才是最要紧的：一条只在"你记得记账时才记账"的链，读的人
# 分不清"没人改"和"改了没记"——两者在链上都是一片空白。**没记的能被发现，
# 链才可信。**



@case_model.command("import-xlsx")
@click.argument("xlsx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--module", required=True, help="模块名（进 casemodel object）")
@click.option("--code", "object_code", default=None,
              help="object_code（缺省从模块名推，须匹配 ^[A-Z][A-Z0-9]{1,7}$）")
@click.option("--out", "-o", "out_dir", default=None,
              help="输出目录（缺省 specs/<module>）")
@click.option("--axes", "axes_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="轴声明 sidecar（xlsx 没有维度建模时，用它把组合格拆成 cross）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_import_xlsx(xlsx, module, object_code, out_dir, axes_path, json_output):
    """PM 手写测试点表（xlsx）→ casemodel + source_map（方案 B）。

    xlsx 管"该测什么"（人评审、diff），casemodel 管"怎么测"（执行契约）。
    生成的 casemodel **必须过 schema** 才落盘；两边哈希写进 source_map，表改了
    没重新导入可以用 `case-model verify-import` 查出来。

    \b
    示例:
      vagent case-model import-xlsx NPU.xlsx --module npu_cmdsched
      vagent case-model verify-import NPU.xlsx specs/npu_cmdsched/casemodel.yaml \
             specs/npu_cmdsched/source_map.json
    """
    from src.tools.humanview.aivm_ir import load_xlsx_to_ontology
    from src.tools.humanview.aivm_ir.bridge import import_ontology

    target = Path(out_dir) if out_dir else Path("specs") / module
    try:
        onto = load_xlsx_to_ontology(str(xlsx))
        result = import_ontology(onto, target, module_name=module,
                                 object_code=object_code, source_path=xlsx,
                                 axes_path=axes_path)
    except Exception as exc:                    # noqa: BLE001  CLI 边界统一报
        console.print(f"[red]导入失败：{exc}[/red]")
        raise SystemExit(2)
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    console.print(f"[green]✓[/green] {result['casemodel']} · bins={result['bins']}"
                  f" · dropped={result['dropped']} · warnings={result['warnings']}")
    console.print(f"  source_map：{result['source_map']}")
    if result["dropped"]:
        console.print(f"  [yellow]{result['dropped']} 个格子未映射"
                      f"（逐条见 source_map.dropped）[/yellow]")


@case_model.command("verify-import")
@click.argument("xlsx", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("casemodel", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.argument("source_map", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--axes", "axes_path", default=None,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="轴声明 sidecar（导入时用过就一起校验）")
@click.option("--json", "-j", "json_output", is_flag=True, help="JSON 输出")
def case_model_verify_import(xlsx, casemodel, source_map, axes_path, json_output):
    """双哈希校验：xlsx 或 casemodel 被单边改过（没重新导入）就失败。"""
    from src.tools.humanview.aivm_ir.bridge import verify_import

    result = verify_import(xlsx, casemodel, source_map, axes_path=axes_path)
    if json_output:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    elif result["ok"]:
        console.print("[green]✓ xlsx 与 casemodel 的绑定未被改动[/green]")
    else:
        for issue in result["issues"]:
            console.print(f"[red]✗ {issue['check']}: {issue['detail']}[/red]")
    raise SystemExit(0 if result["ok"] else 1)
