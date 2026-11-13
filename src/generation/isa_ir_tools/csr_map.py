"""CSR register map knowledge for the csr_write/csr_read control ops.

Source of truth: npu_top/doc/csr_register_map.csv (RTL de/core_reg/src/reg_ctrl.v),
vendored into this package as data/csr_map.csv. The loader pins the shape so
drift fails loudly; the map is only read when a csr_write/csr_read is compiled.
"""
from __future__ import annotations

import csv
from pathlib import Path

MAP_PATH = Path(__file__).resolve().parent / "data" / "csr_map.csv"
_EXPECTED_ROWS = 232

# Regions where a plain csr_write is dangerous (clk gating) or semantically
# unsigned (CDD mapping open). Reads are always allowed; writes need the
# .case-level csr_clk_rst=1 compile permission.
GATED_WRITE_RANGES = (
    (0x2F0, 0x2EC + 0x20),      # creg_<unit>_icg_en x8, 0x2F0..0x30C
    (0x320, 0x39C),             # creg_reset0..15, creg_set0..15
)


def load_map(path: Path | None = None):
    rows = []
    with (path or MAP_PATH).open(newline='', encoding='utf-8') as fh:
        for entry in csv.DictReader(fh):
            rows.append((int(entry['address'], 16), entry['name'], entry['access']))
    if len(rows) != _EXPECTED_ROWS:
        raise ValueError(f'CSR map drift: {len(rows)} rows != {_EXPECTED_ROWS}; re-vendor from npu_top/doc/csr_register_map.csv')
    icg = [addr for addr, name, _ in rows if name.endswith('_icg_en')]
    assert all(GATED_WRITE_RANGES[0][0] <= addr <= GATED_WRITE_RANGES[0][1] for addr in icg)
    assert len(icg) == 8
    return rows


_ROWS = None


def _rows():
    # Load on first CSR use: programs without csr_write/csr_read must compile
    # even when the vendored map is missing or incomplete.
    global _ROWS
    if _ROWS is None:
        _ROWS = load_map()
    return _ROWS


def _by_name():
    return {name: addr for addr, name, _ in _rows()}


def _by_addr():
    return {addr: name for addr, name, _ in _rows()}


def resolve_address(values, op):
    """Return canonical 32-bit address from addr= or name= fields."""
    addr, name = values.get('addr'), values.get('name')
    if addr is None and name is None:
        raise ValueError(f'{op}: address source required (addr= or name=)')
    names = _by_name()
    if addr is not None and name is not None:
        if name not in names:
            raise ValueError(f'{op}: unknown register name {name!r}')
        if addr != names[name]:
            raise ValueError(f'{op}: addr {addr:#x} contradicts name {name!r} ({names[name]:#x})')
        return addr
    if name is not None:
        if name not in names:
            raise ValueError(f'{op}: unknown register name {name!r}')
        return names[name]
    return addr


def is_gated_write(addr):
    return any(lo <= addr <= hi for lo, hi in GATED_WRITE_RANGES)


def validate(op, values, *, allow_clk_rst):
    """Whitelist fields, normalize addr/name, enforce the write gate.

    Returns canonical parameters: {addr, ...} with optional data/strobe/expect.
    """
    allowed = {'csr_write': {'addr', 'name', 'data', 'strobe'},
               'csr_read': {'addr', 'name', 'expect'}}[op]
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f'{op}: unknown field(s) {sorted(unknown)} (TB reports csr_field_error)')
    addr = resolve_address(values, op)
    if not 0 <= addr < 1 << 32:
        raise ValueError(f'{op}: addr out of 32-bit range')
    out = {'addr': addr}
    if op == 'csr_write':
        if 'data' not in values:
            raise ValueError('csr_write: data required')
        data = values['data']
        if type(data) is not int or not 0 <= data < 1 << 32:
            raise ValueError('csr_write: data must be 32-bit unsigned')
        out['data'] = data
        strobe = values.get('strobe')
        if strobe is not None:
            if type(strobe) is not int or not 1 <= strobe <= 0xF:
                raise ValueError('csr_write: strobe must be 4-bit mask 0x1..0xF')
            out['strobe'] = strobe
        if is_gated_write(addr) and not allow_clk_rst:
            raise ValueError(
                f'csr_write {addr:#010x} ({_by_addr().get(addr, "unmapped")}): gated clk/reset region; '
                'declare csr_clk_rst=1 in .case to allow (int/en regions are always writable)')
    else:
        expect = values.get('expect')
        if expect is not None:
            if type(expect) is not int or not 0 <= expect < 1 << 32:
                raise ValueError('csr_read: expect must be 32-bit unsigned')
            out['expect'] = expect
    return out


def canonical_text(op, params):
    parts = [f'addr=0x{params["addr"]:08X}']
    for key in ('data', 'strobe', 'expect'):
        if key in params:
            parts.append(f'{key}=0x{params[key]:X}')
    return f'{op} ' + ', '.join(parts)
