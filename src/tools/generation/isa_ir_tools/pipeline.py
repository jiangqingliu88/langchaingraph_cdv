"""Independent tensor and IR stages with an explicit subprocess orchestrator."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

from .ir_flow import FixedIRFlow, IRFlowError
from .core import TensorGenError, digest
from .isa_versions import normalize_revision, version_metadata, REVISION_CHOICES

ROOT = Path(__file__).resolve().parents[1]


def default_output_dir(source):
    """Reserve a fresh sibling directory without replacing existing results."""
    name = source.name
    stem = name[:-7] if name.lower().endswith('.ir.txt') else source.stem
    stem = stem or 'ir_output'
    index = 0
    while True:
        candidate = source.parent / (stem if index == 0 else f'{stem}_{index:03d}')
        try:
            candidate.mkdir(exist_ok=False)
            return candidate
        except FileExistsError:
            index += 1


def load_flow(source, lint=False, isa_revision=None):
    source = Path(source)
    return FixedIRFlow(source.read_text(encoding='utf-8-sig'), str(source), cfg_lint=lint, isa_revision=isa_revision).parse()


def execute(command, log):
    print('RUN: ' + subprocess.list2cmdline(command), flush=True)
    result = subprocess.run(command, cwd=ROOT, text=True, encoding='utf-8', errors='replace',
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    Path(log).write_text(result.stdout, encoding='utf-8')
    try:
        print(result.stdout, end="", flush=True)
    except UnicodeEncodeError:
        # A GBK console cannot encode replacement chars the subprocess decode
        # produced; the log retains them. Echo raw bytes for the operator.
        sys.stdout.buffer.write(result.stdout.encode('utf-8', 'replace') + b'\n')
    if result.returncode:
        raise RuntimeError(f'stage failed ({result.returncode}); see {log}')


def main(argv=None):
    parser = argparse.ArgumentParser(description='Independent tensors, IR projection, and command compilation stages.')
    sub = parser.add_subparsers(dest='stage', required=True)

    for name in ('tensors', 'ir', 'all'):
        p = sub.add_parser(name)
        p.add_argument('source', help='Input ir.txt')
        p.add_argument('--isa-revision', choices=REVISION_CHOICES,
                       help='ISA contract name; only ISA VERSION V1.4 exists (v0.3 XLSX review contract retired 2026-11-07)')
        p.add_argument('--out-dir', required=name == 'all',
                       help='Output directory; top-level default: fresh input-name directory beside ir.txt, numbered if occupied')
        if name == 'ir':
            p.add_argument('--tensor-manifest', required=True)
            p.add_argument('--no-cfg-lint', action='store_true')
        if name == 'all':
            p.add_argument('--no-cfg-lint', action='store_true')
            p.add_argument('--target', choices=['standalone', 'cluster'], required=True)
            p.add_argument('--core-id', type=int, required=True)
            p.add_argument('--csr-clk-rst', action='store_true',
                           help='Allow csr_write into gated clk/reset regions for this compile; normally declared as .case csr_clk_rst=1 in the IR')
    args = parser.parse_args(argv)
    try:
        revision = normalize_revision(args.isa_revision)
        source = Path(args.source).resolve()
        if not source.is_file():
            raise ValueError(f'input file does not exist: {source}')
        if args.stage == 'all':
            if args.target != 'standalone':
                raise ValueError('cluster instr dispatch format is not defined yet')
            if not 0 <= args.core_id < 16:
                raise ValueError('--core-id must be 0..15')
        out = Path(args.out_dir).resolve() if args.out_dir else default_output_dir(source)
        print('Output directory: ' + str(out), flush=True)
        if args.stage == 'tensors':
            flow = load_flow(source, isa_revision=revision)
            out.mkdir(parents=True, exist_ok=True)
            (out / 'stage_report.json').write_text(json.dumps({
                'stage': 'tensors', **version_metadata(revision), 'source': str(source),
            }, indent=2) + '\n', encoding='utf-8')
            spec = out / 'tensor_spec.json'
            case = flow.tensor_case()
            spec.write_text(json.dumps(case, indent=2) + '\n', encoding='utf-8')
            (out / 'scalars.json').write_text(json.dumps({'schema': 'ir_scalars_v2',
                                                          'scalars': list(flow.scalars.values()),
                                                          'history': list(flow.scalar_history)}, indent=2) + '\n', encoding='utf-8')
            if not flow.tensors:
                # Control-only and hand-encoded programs need no tensor payload.
                (out / 'data').mkdir(exist_ok=True)
                (out / 'data/manifest.json').write_text(json.dumps({
                    'schema': 'tensor_manifest_v2', 'tensors': [],
                    'source_revision': {'spec_digest': digest(case),
                                        'isa_revision': revision, 'address_schema': version_metadata(revision)['address_schema']},
                }, indent=2) + '\n', encoding='utf-8')
                (out / 'generator.log').write_text('No tensor declarations; wrote empty manifest.\n', encoding='utf-8')
            else:
                execute([sys.executable, '-B', '-m', 'isa_ir_tools.cli', 'generate', '--spec', str(spec),
                         '--out-dir', str(out / 'data'), '--formats', 'bin,hex,memh', '--overwrite'], out / 'generator.log')
        elif args.stage == 'ir':
            load_flow(source, not args.no_cfg_lint, revision).generate(out, debug_json=True, tensor_manifest=args.tensor_manifest)
        else:
            if args.target != 'standalone':
                raise ValueError('cluster instr dispatch format is not defined yet')
            if not 0 <= args.core_id < 16:
                raise ValueError('--core-id must be 0..15')
            out.mkdir(parents=True, exist_ok=True)
            steps = [
                [sys.executable, '-B', '-m', 'isa_ir_tools.pipeline', 'tensors', str(source), '--out-dir', str(out / '01_tensors')],
                [sys.executable, '-B', '-m', 'isa_ir_tools.pipeline', 'ir', str(source), '--tensor-manifest',
                 str(out / '01_tensors/data/manifest.json'), '--out-dir', str(out / '02_ir')] + (['--no-cfg-lint'] if args.no_cfg_lint else []),
                [sys.executable, '-B', '-m', 'isa_ir_tools.cmd_compile', str(out / '02_ir/seq.ir'), '--target', args.target,
                 '--core-id', str(args.core_id), '--out-dir', str(out / '03_commands')]
                + (['--csr-clk-rst'] if args.csr_clk_rst else []),
            ]
            for command in steps:
                command.extend(['--isa-revision', revision])
            status = {'source': str(source), **version_metadata(revision),
                      'target': args.target, 'core_id': args.core_id, 'stages': []}
            report = out / 'pipeline.report.json'
            for index, command in enumerate(steps, 1):
                entry = {'stage': index, 'command': command, 'status': 'running'}
                status['stages'].append(entry)
                report.write_text(json.dumps(status, indent=2), encoding='utf-8')
                try:
                    execute(command, out / f'stage{index}.log')
                except RuntimeError:
                    entry['status'] = 'failed'
                    report.write_text(json.dumps(status, indent=2), encoding='utf-8')
                    raise
                entry['status'] = 'passed'
                report.write_text(json.dumps(status, indent=2), encoding='utf-8')
            print('Final playback file: ' + str(out / '03_commands/commands.tsv'))
            return 0
    except (IRFlowError, TensorGenError, ValueError, OSError, RuntimeError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
