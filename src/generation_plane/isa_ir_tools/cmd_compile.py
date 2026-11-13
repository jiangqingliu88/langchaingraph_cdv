"""Compile operand-resolved seq.ir for an explicitly selected hardware target."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from .ir_flow import IRFlowError, _call, _statements, tb_operation, tb_fields
from .ir_isa import ISAError, instruction, instruction_fields, unsigned, vector_variant
from .isa_versions import (normalize_revision, normalize_address_schema, address_schema,
                           version_metadata, REVISION_CHOICES)
from .csr_map import validate as csr_validate, canonical_text as csr_canonical


class CompileError(ValueError):
    pass


CONTROL_OPS = ("wait cycles", "wait done", "wait event", "signal event",
               "nop", "watchdog", "mem_init", "mem_scrub", "checkpoint",
               "expect rd", "expect write", "expect region", "expect intr",
               "expect idle", "expect perf", "perf window")

# seq.ir spells TB operations with underscores; control rows below use the
# historical space form. Instruction opcodes are never in this map.
_CONTROL_ALIASES = {
    'wait_cycles': 'wait cycles', 'wait_done': 'wait done', 'wait_event': 'wait event',
    'signal_event': 'signal event', 'raw_cmd': 'raw cmd',
    'expect_rd': 'expect rd', 'expect_write': 'expect write',
    'expect_region': 'expect region', 'expect_intr': 'expect intr',
    'expect_idle': 'expect idle', 'expect_perf': 'expect perf',
    'perf_window': 'perf window',
}


def _encoding_label(encoding):
    """Normalize a resolved-IR encoding label to the current contract form.

    Retired seq.ir wrote ``<revision>:<rs1>,<rs2>``; the V1.4 emitter writes
    ``<revision>:<rs1>:<rs2>``. Both describe the same operand descriptors, so
    compare them in the current form.
    """
    head, sep, rest = encoding.partition(':')
    try:
        revision = normalize_revision(head)
    except ValueError:
        return encoding
    rs1, comma, rs2 = rest.partition(',')
    return f'{revision}:{rs1}:{rs2}' if comma else f'{revision}:{rest}'


def _read_program(text, isa_revision=None):
    """Read resolved operands without regenerating tensors or projecting views."""
    actions = []
    declared_revision, declared_schema = None, None
    declared_csr_clk_rst = False
    for statement, line, original in _statements(text, include_original=True):
        tb_op = tb_operation(statement)
        if tb_op:
            # TB syntax belongs to the player. Only decode the explicit
            # separated raw hardware format, whose layout is already known.
            fields = tb_fields(statement, tb_op, line)
            actions.append({'op': tb_op, 'fields': fields, 'passthrough': original,
                            'source': {'line': line, 'text': original}})
            continue
        if statement.startswith('.'):
            directive = statement.split(None, 1)[0]
            if directive not in {'.case', '.profile', '.tensor', '.view', '.reserve_output'}:
                raise CompileError(f"line {line}: unsupported resolved-IR directive {directive}")
            if directive == '.case':
                # The only compile-visible .case field today is the CSR write-gate
                # permission; the seed is consumed by the tensor stage.
                body = statement[len(directive):].strip()
                fields = _call('.case' + ' ' + body + ' ', line)[1]
                if 'csr_clk_rst' in fields:
                    if fields['csr_clk_rst'] not in (0, 1, True, False):
                        raise CompileError(f"line {line}: csr_clk_rst must be 0/1")
                    declared_csr_clk_rst = bool(fields['csr_clk_rst'])
            if directive == '.profile':
                body = statement[len(directive):].strip()
                profile = _call('.profile' + ' ' + body + ' ', line)[1]
                if 'isa_revision' in profile:
                    try:
                        candidate = normalize_revision(profile['isa_revision'])
                    except ValueError as exc:
                        raise CompileError(f"line {line}: ISA REVISION MISMATCH: {exc}") from exc
                    if declared_revision is not None and candidate != declared_revision:
                        raise CompileError(f"line {line}: ISA REVISION MISMATCH: multiple contracts in one seq.ir")
                    declared_revision = candidate
                if 'address_schema' in profile:
                    candidate = normalize_address_schema(profile['address_schema'])
                    if declared_schema is not None and candidate != declared_schema:
                        raise CompileError(f"line {line}: ADDRESS SCHEMA MISMATCH: multiple contracts in one seq.ir")
                    declared_schema = candidate
            continue
        call = _call(statement, line)
        if call is None:
            parts = statement.split(None, 1)
            call = _call(parts[0] + (' ' + (parts[1] if len(parts) == 2 else '') + ' '), line)
        if call is None:
            raise CompileError(f"line {line}: expected an ISA instruction")
        name, fields = call
        actions.append({'op': name, 'fields': fields, 'source': {'line': line, 'text': ' '.join(statement.split()).replace('\t', ' ')}})

    try:
        revision = normalize_revision(isa_revision if isa_revision is not None else declared_revision)
    except ValueError as exc:
        raise CompileError(str(exc)) from exc
    if declared_revision is not None and declared_revision != revision:
        raise CompileError("ISA REVISION MISMATCH: regenerate seq.ir from source using the requested revision")
    if declared_schema is not None and declared_schema != address_schema(revision):
        raise CompileError("ADDRESS_SCHEMA MISMATCH: regenerate seq.ir from source")
    for action in actions:
        action['isa_revision'] = revision
    return actions, revision, declared_csr_clk_rst


def read_actions(text, *, isa_revision=None):
    return _read_program(text, isa_revision)[0]


def pack_cmddata(fields):
    """{rs2val[31:0], rs1val[31:0], funct7[6:0], xd, xs1, xs2}."""
    rs2 = unsigned(fields['rs2val'], 32, 'rs2val')
    rs1 = unsigned(fields['rs1val'], 32, 'rs1val')
    funct = unsigned(fields['funct7'], 7, 'funct7')
    xd, xs1, xs2 = (unsigned(fields[k], 1, k) for k in ('xd', 'xs1', 'xs2'))
    return (rs2 << 42) | (rs1 << 10) | (funct << 3) | (xd << 2) | (xs1 << 1) | xs2


def compile_actions(actions, *, target, core_id, isa_revision=None, allow_csr_clk_rst=False):
    if target == 'cluster':
        raise CompileError('UNSUPPORTED_TARGET: cluster instr dispatch format is not defined; no standalone cmddata is emitted')
    if target != 'standalone':
        raise CompileError(f'unknown target {target!r}')
    unsigned(core_id, 4, 'standalone core id')
    revisions = {a['isa_revision'] for a in actions if 'isa_revision' in a}
    revision = normalize_revision(isa_revision if isa_revision is not None else next(iter(revisions), None))
    if revisions - {revision}:
        raise CompileError('ISA REVISION MISMATCH: mixed-version actions cannot be compiled together')
    records = []
    # Standalone models the dispatch destination selection, not CPU-side ROB
    # behavior. Keep the existing flow's explicit all-core startup policy until
    # software writes group mask; this is a TB profile, not a claimed RTL reset.
    nice_core_mask = 0xffff
    # wait done tag liveness (TB rule): tag must reference an instruction that
    # was actually dispatched on this core (kind 'instruction' or raw cmd).
    # Register every upstream tag with how this core's compile resolved it.
    tag_status = {} # tag -> (op, source_line, status in dispatched|skipped|control)
    good_phases = {'cmd accept', 'rsp accept', 'instruction done'}
    def check_wait_done(op_name, tag, values, core_id):
        if not isinstance(tag, str):
            raise CompileError(f'{op_name} requires a string tag')
        phase = values.get('phase')
        if isinstance(phase, str) and phase not in good_phases:
            phase = phase.replace('_', ' ')
        if phase is not None and phase not in good_phases:
            raise CompileError(f'wait done phase {phase!r} not in {sorted(good_phases)} (bare tag defaults to instruction_done)')
        ref = tag_status.get(tag)
        if ref is None:
            raise CompileError(f'wait done tag {tag!r} has no upstream dispatched instruction')
        if ref[2] == 'control':
            raise CompileError(f'wait done tag {tag!r} references control op {ref[0]} (line {ref[1]}); only dispatched instructions may be waited on')
        if ref[2] == 'skipped':
            raise CompileError(f'wait done tag {tag!r}: instruction {ref[0]} (line {ref[1]}) is dispatch_skip for core {core_id}; it can never complete')

    for index, action in enumerate(actions):
        try:
            name, values = _CONTROL_ALIASES.get(action['op'], action['op']), dict(action['fields'])
            tag = values.get('tag')
            if tag is not None and not isinstance(tag, str):
                raise CompileError(f'{name}: tag must be a string')
            def register(status):
                if tag is None:
                    return
                if tag in tag_status:
                    prev = tag_status[tag]
                    raise CompileError(f'tag {tag!r} reused (first at {prev[0]!r} line {prev[1]}); wait done bookkeeping would be ambiguous')
                tag_status[tag] = (name, action['source']['line'], status)

            if name == 'mem_init' and values.get('schema') == 'mem_init_v1':
                if 'isa_revision' in values and normalize_revision(values['isa_revision']) != revision:
                    raise CompileError('ISA REVISION MISMATCH: mem_init metadata uses another contract')
                if normalize_address_schema(values.get('address_schema', address_schema(revision))) != address_schema(revision):
                    raise CompileError('ADDRESS_SCHEMA MISMATCH: mem_init metadata uses another contract')
            if 'passthrough' in action:
                if name in ('csr_write', 'csr_read'):
                    # CSR ops keep their control-row form, but fields are
                    # validated and name= is resolved/canonicalized to addr=.
                    params = csr_validate(name, values, allow_clk_rst=allow_csr_clk_rst)
                    values.clear()
                    values.update(params)
                    register('control')
                    records.append({'index': index, 'kind': 'control', 'op': name,
                                    'source_line': action['source']['line'],
                                    'parameters': values,
                                    'passthrough': csr_canonical(name, params)})
                    continue
                if name == 'raw cmd' and 'cmddata' in values:
                    if 'instr_flag' not in values:
                        raise CompileError('raw cmddata requires explicit instr_flag')
                    data = unsigned(values['cmddata'], 74, 'raw cmddata')
                    unsigned(values['instr_flag'], 1, 'raw instr_flag')
                    # Retain raw syntax in the playback file: provenance must
                    # survive TSV-only playback so dispatch filtering cannot
                    # swallow a deliberately illegal opcode (including funct=0).
                    records.append({'index': index, 'op': name, 'kind': 'control',
                                    'source_line': action['source']['line'],
                                    'source_isa': action['passthrough'],
                                    'passthrough': action['passthrough'],
                                    'cmddata': f'{data:019x}'})
                    register('dispatched')
                else:
                    if name == 'wait done':
                        check_wait_done(name, tag, values, core_id)
                    else:
                        register('control')
                    records.append({'index': index, 'kind': 'control', 'op': name,
                                    'source_line': action['source']['line'],
                                    'parameters': values, 'passthrough': action['passthrough']})
                continue
            if str(values.get('operand_encoding', '')).startswith('pdf_v02:'):
                raise CompileError('LEGACY_RESOLVED_IR: PDF v1.2 address operands cannot be reinterpreted as Word v1.4; regenerate seq.ir from ir.txt')
            if name in CONTROL_OPS:
                if name == 'wait done':
                    check_wait_done(name, tag, values, core_id)
                else:
                    register('control')
                if name == 'wait cycles':
                    n = values.get('n')
                    if type(n) is not int or n < 0:
                        raise CompileError('wait_cycles requires nonnegative integer n')
                if name in {'wait event', 'signal event'} and not isinstance(values.get('event'), str):
                    raise CompileError(f'{name} requires a string event')
                records.append({'index': index, 'kind': 'control', 'op': name,
                                'source_line': action['source']['line'], 'parameters': values})
                continue
    
            spec = instruction(name, revision)
            encoding = values.get('operand_encoding')
            legacy_note = (isinstance(encoding, str) and (
                encoding == 'explicit: rs1/rs2 preserved' or
                (name in ('w r len_drv_xn', 'rd len_drv_xn') and encoding in (
                    'lemem word: rs1=address(dst)+offset, rs2=value[31:0]',
                    'lemem word: rs1=address(src)+offset, rs2=0'))))
            if encoding is not None and not legacy_note and _encoding_label(encoding) != f'{revision}:{spec.rs1}:{spec.rs2}':
                raise CompileError('ISA REVISION MISMATCH: operand encoding does not match selected descriptor contract; regenerate seq.ir')
            variant = vector_variant(name)
            for key in ('rs1val', 'rs2val'):
                value = values.get(key)
                if isinstance(value, list):
                    if not variant or (key == 'rs1val' and variant == 'vn01'):
                        raise CompileError(f'{name}: {key} must be scalar')
                    if len(value) != 4:
                        raise CompileError(f'{name}: resolved vector {key} must have four physical lanes')
                    for lane in value:
                        unsigned(lane, 32, key)
            # A PDF address ambiguity does not change already hand-resolved
            # bits. Preserve them, while reporting the ambiguity for review.
            fields = instruction_fields({'op': name, 'fields': values}, core=core_id,
                                        allow_operand_source_conflict=True, isa_revision=revision)
            flag = fields.pop('instr_flag')
            if 'instr_flag' in values and values['instr_flag'] != flag:
                raise CompileError(f'{name}: instr_flag conflicts with instruction class')
            data = pack_cmddata(fields)
            if name == 'group_mask_drv_xn':
                register('control')
                if fields['rs1val'] >> 16:
                    raise CompileError('group mask reserved bits must be zero; use raw cmd for illegal injection')
                nice_core_mask = fields['rs1val'] & 0xffff
                records.append({'index': index, 'op': 'dispatch_mask', 'kind': 'control',
                                'source_line': action['source']['line'],
                                'source_isa': action['source'].get('text', name),
                                'parameters': {'mask': nice_core_mask},
                                'dispatch_parameters': values})
                continue
            target_mask = nice_core_mask
            if flag:
                # The group/mask belongs to the FIRST operand before per-core
                # projection, not to the selected lane's high address bits.
                mask_operand = values.get('rs1val') if fields['xs1'] else values.get('rs2val', 0)
                if isinstance(mask_operand, list):
                    mask_operand = mask_operand[0]
                # Generated seq.ir retains the full dispatch descriptor even
                # when explicit lane payloads intentionally preserve all bits.
                group_mask = values.get('vn_6b_grp_mask', (mask_operand >> 26) & 0x3f)
                unsigned(group_mask, 6, 'VNICE dispatch group/mask')
                target_mask = (group_mask & 0xf) << (4 * (group_mask >> 4))
            if not target_mask & (1 << core_id):
                register('skipped')
                records.append({'index': index, 'op': 'dispatch_skip', 'kind': 'control',
                                'source_line': action['source']['line'],
                                'source_isa': action['source'].get('text', name),
                                'parameters': {'core_id': core_id, 'target_mask': target_mask},
                                'dispatch_parameters': values})
                continue
            register('dispatched')
            records.append({'index': index, 'op': name, 'source_line': action['source']['line'],
                            'kind': 'instruction', 'parameters': values,
                            'source_isa': action['source'].get('text', name),
                            'cmddata': f'{data:019x}',
                            **fields, **({'source_warning': spec.issue} if spec.issue else {})})
        except ValueError as exc:
            detail = f'{exc.code}: {exc}' if isinstance(exc, ISAError) else str(exc)
            raise CompileError(f"line {action['source']['line']}: {detail}") from exc
    return records


def compile_seq(source, out_dir, *, target, core_id, isa_revision=None, allow_csr_clk_rst=False):
    source = Path(source)
    payload = source.read_bytes()
    actions, revision, case_csr_clk_rst = _read_program(payload.decode('utf-8-sig'), isa_revision)
    allow_csr_clk_rst = allow_csr_clk_rst or case_csr_clk_rst
    records = compile_actions(actions, target=target, core_id=core_id, isa_revision=revision,
                              allow_csr_clk_rst=allow_csr_clk_rst)
    # Validate the whole program before creating output files.
    out = Path(out_dir)
    asset_dir = out / 'data'
    asset_dir.mkdir(parents=True, exist_ok=True)
    for record in records:
        fields = record['parameters']
        if record['op'] == 'mem_init' and (fields.get('schema') == 'mem_init_v1'
                                           or 'file' in fields or 'map file' in fields):
                # Make the command bundle self-contained. seq.ir paths are relative
                # to seq.ir; playback paths are relative to commands.tsv/data.
                for key in ('file', 'map_file'):
                    if key in fields:
                        declared = Path(fields[key])
                        resolved = declared if declared.is_absolute() else source.resolve().parent / declared
                        resolved = resolved.resolve()
                        if not resolved.is_file():
                            raise CompileError(f'mem_init {key} does not exist: {resolved}')
                        destination = asset_dir / resolved.name
                        if destination.exists() and destination.read_bytes() != resolved.read_bytes():
                            raise CompileError(f'mem_init asset name collision: {resolved.name}')
                        if not destination.exists():
                            destination.write_bytes(resolved.read_bytes())
                        fields[key] = f'data/{resolved.name}'
                        record['passthrough'] = 'mem_init ' + json.dumps(fields, ensure_ascii=False, separators=(',', ':'))
    if out.resolve() == source.resolve().parent:
        protected = {source.resolve()}
    else:
        protected = set()
    names = ('cmddata.memh', 'commands.txt', 'commands.json', 'commands.tsv')
    if any((out / name).resolve() in protected for name in names):
        raise CompileError('output would overwrite input seq.ir')
    out.mkdir(parents=True, exist_ok=True)
    instructions = [r for r in records if r['kind'] == 'instruction' or
                    (r['op'] == 'raw cmd' and 'cmddata' in r)]
    (out / 'cmddata.memh').write_text(''.join(r['cmddata'] + '\n' for r in instructions), encoding='utf-8')
    def tsv_row(record):
        if record['kind'] == 'instruction' or 'passthrough' in record:
            text = record.get('source_isa', record.get('passthrough', record['op']))
            return f"{record['index']}\t{record['source_line']}\t{text}"
        if record['op'] in {'dispatch_mask', 'dispatch_skip'}:
            return (record['op'] + '\t' +
                    json.dumps(record['parameters'], ensure_ascii=False, separators=(',', ':')) +
                    f"\t{record['source_line']}\t{record['source_isa']}")
        return None

    (out / 'commands.tsv').write_text(
        ''.join(row + '\n' for row in (tsv_row(r) for r in records) if row is not None),
        encoding='utf-8')
    (out / 'commands.txt').write_text(
        f"// index cmddata[73:0] op source_line\n" +
        ''.join(f"{r['index']:<3} {r['cmddata']} {r['op']} {r['source_line']}\n"
                if r['kind'] == 'instruction'
                else f"{r['index']:<3} CONTROL {r['op']} {json.dumps(r['parameters'], ensure_ascii=False)} {r['source_line']}\n"
                for r in records), encoding='utf-8')
    report = {'schema': 'cmd sch program v2', 'target': target, 'core_id': core_id,
              **version_metadata(revision),
              'csr_clk_rst': allow_csr_clk_rst,
              'playback_file': 'commands.tsv', 'control_execution': 'testbench_player_required',
              'dispatch_policy': {'initial_nice_mask': 0xffff,
                                  'group_mask': 'local control only',
                                  'non_target': 'dispatch_skip', 'raw cmd': 'bypass dispatch'},
              'source': {'source': str(source), 'source_sha256': hashlib.sha256(payload).hexdigest(),
              'cmddata_width': 74,
              'layout': {'rs2val': [73, 42], 'rs1val': [41, 10], 'funct7': [9, 3],
                         'xd': [2, 2], 'xs1': [1, 1], 'xs2': [0, 0]}},
              'commands': records}
    (out / 'commands.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description='Compile resolved seq.ir to hardware stimulus; tensor generation is not run.')
    parser.add_argument('source', help='Operand-resolved seq.ir input (not source .ir.txt)')
    parser.add_argument('--target', choices=['standalone', 'cluster'], required=True,
                        help='Hardware backend; cluster is reserved until instr dispatch format is specified')
    parser.add_argument('--core-id', type=int, required=True, help='Standalone OUT core ID within cluster, 0..15; selects VNICE lane core_id %% 4')
    parser.add_argument('--out-dir', required=True, help='Directory for cmddata/flag memh and annotated listings')
    parser.add_argument('--isa-revision', choices=REVISION_CHOICES,
                        help='Validate against this contract; omitted: read seq.ir profile, or v0.2 for unversioned handwritten IR')
    parser.add_argument('--csr-clk-rst', action='store_true',
                        help='Allow csr_write into gated clk/reset CSR regions (icg_en 0x2F0-0x30C, creg_reset/set 0x320-0x39C); equivalent to .case csr_clk_rst=1, intended for dedicated clk/reset tests')
    args = parser.parse_args(argv)
    try:
        out = compile_seq(args.source, args.out_dir, target=args.target, core_id=args.core_id,
                          isa_revision=args.isa_revision, allow_csr_clk_rst=args.csr_clk_rst)
    except (CompileError, ISAError, IRFlowError, OSError, UnicodeError) as exc:
        parser.exit(2, f'{exc}\n')
    print(f'Compiled {args.target} program: {out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
