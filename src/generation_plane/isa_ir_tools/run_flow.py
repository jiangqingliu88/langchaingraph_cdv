#!/usr/bin/env python3
"""Single entry point for one case: tensors -> IR -> command bundle.

Usage:
    python -B -X utf8 run_flow.py <case.ir.txt> \
        --target standalone --core-id 0 [--out-dir artifacts/<case>]

The bundle defaults to ``artifacts/<case>/`` beside this script.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent
PACKAGE_PARENT = TOOL_DIR.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from isa_ir_tools.pipeline import main as pipeline_main
from isa_ir_tools.isa_versions import REVISION_CHOICES


def case_name(source: Path) -> str:
    name = source.name
    return name[:-7] if name.lower().endswith('.ir.txt') else source.stem


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='run_flow.py',
        description='Run the three-stage tensor/IR/command flow for one .ir.txt case.',
        epilog='Output defaults to artifacts/<case> next to this script.')
    parser.add_argument('source', help='case IR file (.ir.txt)')
    parser.add_argument('--target', choices=['standalone', 'cluster'], default='standalone')
    parser.add_argument('--core-id', type=int, default=0, help='standalone OUT core ID (0..15)')
    parser.add_argument('--out-dir', help='output bundle; default artifacts/<case>')
    parser.add_argument('--isa-revision', choices=REVISION_CHOICES)
    parser.add_argument('--no-cfg-lint', action='store_true')
    parser.add_argument('--csr-clk-rst', action='store_true')
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    source = Path(args.source).resolve()
    if not source.is_file():
        print(f'input file does not exist: {source}', file=sys.stderr)
        return 2
    out = Path(args.out_dir).resolve() if args.out_dir else TOOL_DIR / 'artifacts' / case_name(source)
    command = ['all', str(source), '--target', args.target, '--core-id', str(args.core_id),
               '--out-dir', str(out)]
    if args.isa_revision:
        command += ['--isa-revision', args.isa_revision]
    if args.no_cfg_lint:
        command.append('--no-cfg-lint')
    if args.csr_clk_rst:
        command.append('--csr-clk-rst')
    print(f'Bundle: {out}', flush=True)
    return pipeline_main(command) or 0


if __name__ == '__main__':
    raise SystemExit(main())
