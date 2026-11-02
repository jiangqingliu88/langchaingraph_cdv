"""命令行入口 —— `python -m ...tool_uvm.gen_uvm` 的实现。

从 `tool_uvm/gen_uvm.py` 原样搬入；`gen_uvm.main` 是它的兼容门面。
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
from typing import Dict, List, Optional

from ..constants import TEMPLATES_DIR, __version__
from ..render.file_ops import (
    _clean_generated, _write_report_json, backup_merge_source,
)
from ..render.jinja_renderer import JinjaRenderer
from ..render.region_injector import RegionError, RegionInjector
from ..render.templates import (
    BENCH_TEMPLATES, ENVIRONMENT_ROOT_TEMPLATES, ENVIRONMENT_SEQ_TEMPLATES,
    ENVIRONMENT_TEST_TEMPLATES, ENV_CONSTRAINT_TEMPLATES, INTERFACE_TEMPLATES,
)
from .orchestrator import UVMGenerator

# ── P0-4: 编译仿真门禁（--gate）──
_GATE_SIMULATORS = ("vlog", "vcs")   # 支持 UVM 的仿真器（iverilog/verilator 不支持 UVM 类）

def _detect_simulator() -> Optional[str]:
    for name in _GATE_SIMULATORS:
        if shutil.which(name):
            return name
    return None


def _run_gate(output_root: Path) -> List[Dict[str, str]]:
    """对每个 agent 的 loopback 自检跑编译+仿真，提取 pass/fail/skip。

    无仿真器 → 每项 skip（不阻断生成，仅报告）。
    """
    import subprocess as _sp

    sim = _detect_simulator()
    results: List[Dict[str, str]] = []
    agents_dir = output_root / "agents"
    if not agents_dir.is_dir():
        return results
    for agent_dir in sorted(agents_dir.iterdir()):
        lb_dir = agent_dir / "loopback"
        filelist = lb_dir / "filelist.f"
        if not filelist.is_file():
            continue
        name = agent_dir.name
        if sim is None:
            results.append({"agent": name, "status": "skip",
                            "reason": "no UVM simulator (vlog/vcs) found"})
            continue
        log_file = lb_dir / "gate_sim.log"
        try:
            if sim == "vlog":   # Questa/ModelSim
                cmds = [
                    ["vlog", "-sv", "-f", "filelist.f"],
                    ["vsim", "-c", "-l", "gate_sim.log",
                     "-do", "run -all; quit -f", f"{name}_loopback_tb"],
                ]
            else:               # VCS
                cmds = [
                    ["vcs", "-sverilog", "-f", "filelist.f", "-l", "gate_comp.log"],
                    ["./simv", "-l", "gate_sim.log"],
                ]
            status = "pass"
            for cmd in cmds:
                proc = _sp.run(cmd, cwd=str(lb_dir), capture_output=True,
                               text=True, timeout=300)
                if proc.returncode != 0:
                    status = "fail"
                    break
            if status == "pass":
                log_text = ""
                if log_file.is_file():
                    log_text = log_file.read_text(encoding="utf-8", errors="replace")
                if "UVM_ERROR" in log_text or "LOOPBACK_TIMEOUT" in log_text:
                    status = "fail"
            results.append({"agent": name, "status": status,
                            "sim": sim, "log": str(log_file)})
        except Exception as exc:
            results.append({"agent": name, "status": "fail",
                            "reason": f"{type(exc).__name__}: {exc}"})
    return results


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_uvm.py",
        description="Generate UVM SystemVerilog from YAML descriptors (tool_uvm).",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s (tool_uvm) {__version__}",
        help="Show script version number and exit.",
    )
    parser.add_argument(
        "-i", "--input", nargs="+", default=["."],
        help="Input YAML file(s) or directories containing YAML files. "
             "A .f list file is also accepted and expanded into the paths it lists.",
    )
    parser.add_argument(
        "-f", "--file", dest="input", nargs="+",
        help="Same as -i/--input: YAML files / directories, or a .f list file "
             "(one path per line; '#' and '//' start comments).",
    )
    parser.add_argument(
        "-d", "--dest_dir", "--output", dest="dest_dir", default="generated",
        help="Specify a destination directory for output. Default is $CWD/generated.",
    )
    parser.add_argument(
        "-o", "--overwrite", action="store_true",
        help="Overwrite existing output files. Default behavior is to skip files "
             "if they already exist in the destination directory.",
    )
    parser.add_argument(
        "-g", "--generate", metavar="NAME",
        help="Only produce the specified component (by name). By default, all "
             "components defined by the input configuration files will be generated.",
    )
    parser.add_argument(
        "-t", "--template_dir", metavar="DIR",
        help="Override the location where templates for generated files are sourced.",
    )
    parser.add_argument(
        "-c", "--clean", action="store_true",
        help="Clean up generated code (banner-signed files only) instead of producing code.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress output while running.",
    )
    parser.add_argument(
        "-m", "--merge_source", metavar="DIR",
        help="Enable auto-merge flow, pulling hand-edited pragma custom blocks from "
             "the specified directory. Updates from YAML will be overlaid on top of "
             "the specified directory. Backup of the original source will be made by default.",
    )
    parser.add_argument(
        "-s", "--merge_skip_missing_blocks", action="store_true",
        help="Continue the merge even if a labeled block was found in old source that "
             "can't be mapped to anything in the new output. A report of all such files "
             "and labels will be produced at the end of the run. By default, missing "
             "blocks will raise an error.",
    )
    parser.add_argument(
        "--merge_no_backup", action="store_true",
        help="Do not produce a backup of the original merge source.",
    )
    parser.add_argument(
        "--merge_debug", action="store_true",
        help="Provide an intermediate unmerged output directory for debug purposes. "
             "The location of this directory is <dest_dir>/merge_debug.",
    )
    parser.add_argument(
        "--merge_verbose", action="store_true",
        help="Output details on names of files and named blocks that were affected "
             "during the merging process.",
    )
    parser.add_argument(
        "--gate", action="store_true",
        help="生成后对每个 agent 的 loopback 自检跑编译+仿真门禁（无 vlog/vcs 则跳过）。",
    )
    parser.add_argument(
        "--skip-schema-check", action="store_true",
        help="跳过 Phase 0 YAML schema 语法检查（缺省执行，schema error 阻断生成）。",
    )
    parser.add_argument(
        "--report-json", action="store_true",
        help="输出结构化生成报告 generation_report.json（供 Agent 决策/签核证据包引用）。",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List the supported Jinja2 templates and exit.",
    )
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    dest_root = Path(args.dest_dir).expanduser().resolve()

    # ── -c/--clean：清理带签名的生成文件 ──
    if args.clean:
        removed = _clean_generated(dest_root)
        log(f"Cleaned {removed} generated file(s) from {dest_root}")
        return 0

    if args.list_templates:
        print("Supported template sets:")
        print("  interface_templates:")
        seen: set = set()
        for entry in INTERFACE_TEMPLATES:
            if entry[0] not in seen:   # 合并模板（port 参数化）注册两次，只列一次
                seen.add(entry[0])
                print(f"    {entry[0]}")
        print("  environment_root_templates:")
        for tpl, _ in ENVIRONMENT_ROOT_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_test_templates:")
        for tpl, _ in ENVIRONMENT_TEST_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_seq_templates:")
        for tpl, _ in ENVIRONMENT_SEQ_TEMPLATES:
            print(f"    {tpl}")
        print("  env_constraint_templates:")
        for tpl, _ in ENV_CONSTRAINT_TEMPLATES:
            print(f"    {tpl}")
        print("  bench_templates:")
        for tpl, _ in BENCH_TEMPLATES:
            print(f"    {tpl}")
        return 0

    input_paths = [Path(x).expanduser() for x in args.input]
    dest_root.mkdir(parents=True, exist_ok=True)

    templates_dir = Path(args.template_dir).expanduser().resolve() if args.template_dir else TEMPLATES_DIR
    renderer = JinjaRenderer(templates_dir)

    # ── 合并流程 ──
    injector = RegionInjector(
        merge_source=args.merge_source,
        skip_missing=args.merge_skip_missing_blocks,
        debug_dir=(dest_root / "merge_debug") if args.merge_debug else None,
    )
    if args.merge_source and not args.merge_no_backup:
        try:
            backup = backup_merge_source(Path(args.merge_source).expanduser())
            log(f"Merge source backed up to: {backup}")
        except OSError as exc:
            log(f"Warning: backup failed: {exc}")

    generator = UVMGenerator(
        renderer, dest_root,
        injector=injector,
        overwrite=args.overwrite,
        generate_names=[args.generate] if args.generate else None,
        quiet=args.quiet,
        schema_check=not args.skip_schema_check,
    )

    try:
        generated_files = generator.run(input_paths)
    except RegionError as exc:
        print(f"Error: {exc}", file=__import__("sys").stderr)
        return 1

    skipped = generator.skipped
    log(f"Generated {len(generated_files)} file(s) into: {dest_root}"
        + (f" (skipped {skipped} existing)" if skipped else ""))
    for path in generated_files:
        log(f"  {path.relative_to(dest_root)}")

    # ── 校验摘要（可审计）──
    n_schema_warn = sum(1 for i in generator.schema_issues if i.severity == "warning")
    if n_schema_warn:
        log(f"Schema check: {n_schema_warn} warning(s) — see {dest_root / 'schema_report.txt'}")
    n_warn = sum(1 for i in generator.validation_issues if i.severity == "warning")
    if n_warn:
        log(f"Semantic check: {n_warn} warning(s) — see {dest_root / 'validation_report.txt'}")

    # ── P0-4: 编译仿真门禁 ──
    gate_results: List[Dict[str, str]] = []
    if args.gate:
        log("Gate: running loopback compile+sim ...")
        gate_results = _run_gate(dest_root)
        for r in gate_results:
            if r.get("status") == "skip":
                log(f"  [SKIP] {r['agent']} — {r.get('reason', '')}")
            else:
                log(f"  [{r['status'].upper()}] {r['agent']} (sim={r.get('sim')})")

    # ── P2-4: 结构化 JSON 报告 ──
    if args.report_json:
        report_path = _write_report_json(
            dest_root,
            generated=len(generated_files),
            skipped=skipped,
            validation_issues=generator.validation_issues,
            merge_reports=injector.report,
            load_errors=injector.load_errors,
            gate_results=gate_results,
            schema_issues=generator.schema_issues,
            inputs=input_paths,
        )
        log(f"Report: {report_path}")

    # ── 合并报告 ──
    if args.merge_source:
        report = injector.report
        merged_files = [r for r in report if r.blocks]
        total_blocks = sum(len(r.blocks) for r in report)
        merged_count = sum(len([b for b in r.blocks if b.source == "merged"]) for r in report)
        log(f"Merge: {len(merged_files)} file(s) with regions, "
            f"{total_blocks} block(s) updated ({merged_count} from hand-edited source)")
        missing = [(r.relpath, slot) for r in report for slot in r.missing]
        if missing:
            log(f"Merge: {len(missing)} block(s) in old source could not be mapped (skipped):")
            for rel, slot in missing:
                log(f"  [{rel}] {slot}")
        if injector.load_errors:
            log(f"Merge: {len(injector.load_errors)} file(s) skipped due to malformed regions:")
            for err in injector.load_errors:
                log(f"  {err}")
        if args.merge_verbose:
            for r in report:
                if not r.blocks and not r.missing:
                    continue
                log(f"  [{r.relpath}]")
                for b in r.blocks:
                    log(f"    {b.slot} <- {b.source} ({b.lines} lines)")

    return 0
