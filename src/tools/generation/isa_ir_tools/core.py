"""Validated deterministic tensor generation and explicit storage layouts."""
from __future__ import annotations
import copy
import hashlib
import json
import math
import re
import struct
from bisect import bisect_left
from functools import lru_cache

VERSION = '0.5.0'
BITS = {'int4':4, 'int8':8, 'int16':16, 'int32':32, 'fp16':16, 'bf16':16, 'fp32':32,
        'fp8_e5m2':8, 'fp8_e4m3':8, 'fp4_e2m1':4, 'fp4_e1m2':4}
SUPPORTED = set(BITS)
FLOATS = {'fp16':(5,10), 'bf16':(8,7), 'fp32':(8,23), 'fp8_e5m2':(5,2), 'fp8_e4m3':(4,3),
          'fp4_e2m1':(2,1), 'fp4_e1m2':(1,2)}
FINITE_FLOATS = frozenset(('fp8_e5m2', 'fp8_e4m3', 'fp4_e2m1', 'fp4_e1m2'))


@lru_cache(maxsize=None)
def finite_table(dtype):
    """Signed-zero magnitude is reserved; every other code is normal finite.

    Design clarification: exponent zero/nonzero fraction uses a hidden one,
    as does the maximum exponent. Bias follows 2**(E-1)-1.
    """
    e, f = FLOATS[dtype]; bias=1<<(e-1)-1
    return (0.0,) + tuple(math.ldexp(1+fraction/(1<<f), exponent-bias)
                          for code in range(1, 1<<(e+f))
                          for exponent, fraction in (divmod(code, 1<<f),))


MAX_OBJECT_BYTES = 256*1024**2
MAX_CASE_BYTES = 1024**3
MAX_WORKING_BYTES = 512*1024**2
NIBBLES = ('low_index_low_nibble', 'low_index_high_nibble')


class TensorGenError(ValueError):
    def __init__(self, code, message):
        super().__init__(f'{code}: {message}')
        self.code = code


def fail(code, path, message):
    raise TensorGenError(code, f'{path}: {message}')


def obj(value, allowed, path):
    if not isinstance(value, dict):
        fail('INVALID_SPEC', path, 'must be an object')
    unknown = set(value) - set(allowed)
    if unknown:
        fail('INVALID_PARAMETER', path, 'unknown fields ' + ', '.join(sorted(unknown)))


def integer(value, path, lo=0, hi=None, code='INVALID_PARAMETER'):
    if type(value) is not int or value < lo or (hi is not None and value > hi):
        fail(code, path, f'must be integer in [{lo}, {hi}]')
    return value


def number(value, path):
    if type(value) not in (int, float):
        fail('INVALID_VALUE', path, 'finite number required, not bool/string')
    try: valid = math.isfinite(value)
    except OverflowError: valid = False
    if not valid:
        fail('VALUE_OUT_OF_RANGE', path, 'must be finite')
    return value


def enum(value, choices, path, code='INVALID_PARAMETER'):
    if not isinstance(value, str) or value not in choices:
        fail(code, path, f'expected one of {choices}')
    return value


def raw_code(value, width, path):
    if isinstance(value, str):
        if not re.fullmatch(r'0[xX][0-9a-fA-F]+', value):
            fail('INVALID_VALUE', path, 'raw strings require hexadecimal 0x prefix')
        value = int(value, 16)
    return integer(value, path, 0, (1 << width) - 1, 'VALUE_OUT_OF_RANGE')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def u64_stream(seed, name, role, purpose=None):
    key = {'case seed': seed, 'name': name, 'role': role, 'stream version': 2}
    if purpose: key['purpose'] = purpose
    key = canonical(key)
    counter = 0
    while True:
        block = hashlib.sha256(key + counter.to_bytes(8, 'big')).digest()
        for off in range(0, 32, 8): yield int.from_bytes(block[off:off+8], 'big')
        counter += 1


def uniform_int(lo, hi, stream):
    width = hi - lo + 1
    if not 1 <= width <= 2**64:
        fail('INVALID_RANGE', 'pattern', 'integer interval width must be in [1, 2**64]')
    limit = (2**64 // width) * width
    while True:
        word = next(stream)
        if word < limit: return lo + word % width


def build_layout(shape, dtype, request):
    obj(request, ('profile', 'stride_unit', 'stride_dim1', 'stride_dim2', 'int4_nibble_order', 'tail_policy', 'gap_policy'), 'layout')
    for key, default in (('profile', 'linear_atom32'), ('stride_unit', 'atom32'), ('tail_policy', 'zero'), ('gap_policy', 'untouched')):
        enum(request.get(key, default), (default,), 'layout.' + key)
    width = BITS[dtype]
    if width == 4:
        nibble = enum(request.get('int4_nibble_order', NIBBLES[0]), NIBBLES, 'layout.int4_nibble_order')
    else:
        nibble = None
        if 'int4_nibble_order' in request:
            fail('INVALID_PARAMETER', 'layout.int4_nibble_order', 'only applies to 4-bit elements')
    d2, d1, d0 = shape; atoms = (d0*width + 255) // 256
    s1 = integer(request.get('stride_dim1', atoms), 'layout.stride_dim1', 1, code='INVALID_STRIDE')
    if s1 < atoms:
        fail('INVALID_STRIDE', 'layout', 'requires S1 >= row atoms')
    if 'stride_dim2' in request:
        s2 = integer(request['stride_dim2'], 'layout.stride_dim2', 1, code='INVALID_STRIDE')
        if s2 < d1*s1 or s2 % s1:
            fail('INVALID_STRIDE', 'layout', 'requires S2 >= D1*S1, S2 % S1 == 0')
        if s2 % 2:
            # RTL glsu cfg error monitor (excep_en[11]/[12]) raises shape error on
            # odd stride dim2 and TLD completes silently, so it must not be emitted.
            fail('INVALID_STRIDE', 'layout.stride_dim2', 'GLSU requires even stride_dim2 (RTL glsu_cfg_error_monitor excep_en[11]/[12])')
    else:
        s2 = d1 * s1
        # ISA 2.9.1 allows odd S2; the RTL GLSU cfg validator does not.
        # Auto-derived default: round up to the next even multiple of S1.
        if s2 % 2: s2 += s1
    return {'profile': 'linear_atom32', 'version': 1, 'stride_unit': 'atom32', 'stride_dim1': s1, 'stride_dim2': s2,
            'element_bits': width, 'row_atoms': atoms, 'row_bytes': 32*atoms, 'logical_elements': d2*d1*d0,
            'logical_bytes': d2*d1*d0*width, 'payload_bytes': d2*d1*atoms*32,
            'span_bytes': 32*(d2-1)*s2+(d1-1)*s1+atoms, 'rem_dim0': d0%(256//width),
            'tail_policy': 'zero', 'gap_policy': 'untouched', 'int4_nibble_order': nibble if width==4 else None,
            'valid_bits_per_row': d0*width, 'valid_bit_order': nibble if width==4 else 'low_address_first',
            'row_mapping': {'profile': 'scatter_rows_v1', 'shape': shape, 'file_row_stride_bytes': atoms*32,
                            'target_dim1_stride_bytes': 32*s1, 'target_dim2_stride_bytes': 32*s2, 'copy_length': atoms*32}}


def _validate_fields(fields, dtype, path):
    if dtype not in FLOATS: fail('INVALID_PARAMETER', path, 'floating dtype required')
    obj(fields, ('sign', 'exponent', 'fraction'), path)
    e, f = FLOATS[dtype]
    sign = fields.get('sign', {'values': [0, 1]})
    obj(sign, ('values',), path + '.sign')
    signs = sign.get('values')
    if not isinstance(signs, list) or not signs: fail('INVALID_PARAMETER', path + '.sign.values', 'nonempty array required')
    for value in signs: integer(value, path + '.sign.values', 0, 1)
    result = {'sign': {'values': list(signs)}}
    for key, bits in (('exponent', e), ('fraction', f)):
        field = fields.get(key, {'min': 0, 'max': (1 << bits) - 1})
        obj(field, ('min', 'max'), path + '.' + key)
        lo = integer(field.get('min'), path + '.' + key + '.min', 0, (1 << bits) - 1)
        hi = integer(field.get('max'), path + '.' + key + '.max', lo, (1 << bits) - 1)
        result[key] = {'min': lo, 'max': hi}
    return result


def validate_specials(entries, dtype, count):
    if not isinstance(entries, list): fail('INVALID_PARAMETER', 'special_values', 'array required')
    if entries and dtype not in FLOATS: fail('INVALID_PARAMETER', 'special_values', 'floating dtype required')
    result = []; occupied = set(); total = 0
    for index, original in enumerate(entries):
        path = f'generation.special_values[{index}]'
        obj(original, ('kind', 'positions', 'count', 'ratio', 'sign', 'payload_policy', 'payload', 'fraction'), path)
        item = copy.deepcopy(original)
        kind = enum(item.get('kind'), ('+0', '-0', '+inf', '-inf', 'nan', 'denormal'), path + '.kind')
        if sum(key in item for key in ('positions', 'count', 'ratio')) != 1:
            fail('INVALID_PARAMETER', path, 'exactly one of positions/count/ratio required')
        if 'positions' in item:
            if not isinstance(item['positions'], list): fail('INVALID_PARAMETER', path, 'positions array required')
            for pos in item['positions']:
                integer(pos, path + '.positions', 0, count-1)
                if pos in occupied: fail('INVALID_PARAMETER', path, 'duplicate/overlapping position')
                occupied.add(pos)
            amount = len(item['positions'])
        elif 'count' in item: amount = integer(item['count'], path + '.count', 0, count)
        else:
            ratio = number(item['ratio'], path + '.ratio')
            if not 0 <= ratio <= 1: fail('INVALID_PARAMETER', path + '.ratio', 'must be in [0,1]')
            amount = math.floor(count * ratio)
        if kind == 'nan':
            if 'sign' in item or 'fraction' in item: fail('INVALID_PARAMETER', path, 'NaN sign belongs in explicit payload')
            policy = enum(item.get('payload_policy', 'canonical'), ('canonical', 'explicit'), path + '.payload_policy')
            item['payload_policy'] = policy
            if policy == 'explicit':
                code = raw_code(item.get('payload'), BITS[dtype], path + '.payload'); e, f = FLOATS[dtype]
                if (code >> f) & ((1 << e) - 1) != (1 << e) - 1 or not code & ((1 << f) - 1):
                    fail('INVALID_PARAMETER', path + '.payload', 'must encode NaN')
                item['payload'] = code
            elif 'payload' in item: fail('INVALID_PARAMETER', path, 'payload requires explicit policy')
        elif kind == 'denormal':
            if 'payload' in item or 'payload_policy' in item: fail('INVALID_PARAMETER', path, 'NaN-only fields')
            item['sign'] = enum(item.get('sign', 'positive'), ('positive', 'negative', 'random'), path + '.sign')
            item['fraction'] = integer(item.get('fraction', 1), path + '.fraction', 1, (1 << FLOATS[dtype][1]) - 1)
        elif any(key in item for key in ('sign', 'fraction', 'payload', 'payload_policy')):
            fail('INVALID_PARAMETER', path, 'kind does not accept sign/payload/fraction')
        item['resolved_count'] = amount; total += amount; result.append(item)
    if total > count: fail('INVALID_PARAMETER', 'special_values', 'total count exceeds tensor size')
    return result


def _special_pattern(pattern, dtype):
    """Validate and normalize versioned diagnostic/distribution patterns."""
    kind = pattern.get('kind'); path = 'generation.pattern'
    if kind == 'atom_lane_tag':
        obj(pattern, ('kind', 'tag_id'), path)
        return {'kind': kind, 'tag_id': integer(pattern.get('tag_id', 0), path + '.tag_id', 0, 2**32-1)}
    if dtype not in FLOATS: fail('INVALID_PARAMETER', path, 'floating dtype required')
    if kind == 'exponent_sweep':
        obj(pattern, ('kind', 'min_exp', 'max_exp', 'axis', 'mantissa', 'sign'), path)
        # Exponents here are mathematical powers of two, not biased fields.
        minimum, maximum = {'fp16': (-24, 15), 'bf16': (-133, 127), 'fp32': (-149, 127),
                            'fp8_e5m2': (-14, 16), 'fp8_e4m3': (-6, 8),
                            'fp4_e2m1': (0, 2), 'fp4_e1m2': (1, 1)}[dtype]
        lo = integer(pattern.get('min_exp'), path + '.min_exp', minimum, maximum)
        hi = integer(pattern.get('max_exp'), path + '.max_exp', lo, maximum)
        mantissa = number(pattern.get('mantissa', 1.0), path + '.mantissa')
        if not 1 <= mantissa < 2: fail('INVALID_RANGE', path + '.mantissa', 'requires 1<=mantissa<2')
        return {'kind': kind, 'min_exp': lo, 'max_exp': hi, 'mantissa': mantissa,
                'axis': enum(pattern.get('axis', 'dim0'), ('dim0', 'dim1', 'dim2'), path + '.axis'),
                'sign': enum(pattern.get('sign', 'alternating'), ('positive', 'negative', 'alternating'), path + '.sign')}
    if kind == 'loguniform':
        obj(pattern, ('kind', 'min', 'max', 'sign'), path)
        lo = number(pattern.get('min'), path + '.min'); hi = number(pattern.get('max'), path + '.max')
        if not 0 < lo <= hi: fail('INVALID_RANGE', path, 'requires 0<min<=max')
        return {'kind': kind, 'min': lo, 'max': hi,
                'sign': enum(pattern.get('sign', 'positive'), ('positive', 'negative', 'alternating', 'random'), path + '.sign')}
    obj(pattern, ('kind', 'mean', 'stddev'), path)
    mean = number(pattern.get('mean', 0.0), path + '.mean')
    stddev = number(pattern.get('stddev', 1.0), path + '.stddev')
    if stddev <= 0: fail('INVALID_RANGE', path + '.stddev', 'must be positive')
    return {'kind': 'gauss', 'mean': mean, 'stddev': stddev}


def _pattern_value(pattern, t, index, stream):
    kind = pattern['kind']; d2, d1, d0 = t['shape']
    row, i0 = divmod(index, d0); i2, i1 = divmod(row, d1)
    if kind == 'atom_lane_tag':
        per_atom = 256 // BITS[t['dtype']]; atom, lane = divmod(i0, per_atom)
        # A full atom carries a sequence, rather than one narrow coordinate ID.
        key = {'profile': 'atom_lane_tag_v1', 'seed': t['generation']['seed'],
               'name': t['name'], 'role': t['role'], 'tag_id': pattern['tag_id'],
               'i2': i2, 'i1': i1, 'atom': atom, 'lane': lane}
        code = hashlib.sha256(canonical(key).digest())[0]
        # Keep numeric tags exactly representable even with FP8's short fraction.
        width = 2 if t['dtype'].startswith('fp4') else 4 if t['dtype'].startswith('fp8') else min(BITS[t['dtype']], 8)
        return (code & ((1 << width) - 1)) - (1 << (width - 1))
    if kind == 'exponent_sweep':
        coordinate = {'dim0': i0, 'dim1': i1, 'dim2': i2}[pattern['axis']]
        exponent = pattern['min_exp'] + coordinate % (pattern['max_exp'] - pattern['min_exp'] + 1)
        value = math.ldexp(pattern['mantissa'], exponent)
    elif kind == 'loguniform':
        u = (next(stream) >> 11) * 2**-53; lo, hi = pattern['min'], pattern['max']
        value = lo if lo == hi else math.exp((1-u)*math.log(lo) + u*math.log(hi))
        value = max(lo, min(value, math.nextafter(hi, lo))) if lo < hi else value
    else:
        # Box-Muller v1: consume two words per element, discard the sine member.
        u1 = (next(stream) >> 11) * 2**-53
        u2 = (next(stream) >> 11) * 2**-53
        value = pattern['mean'] + pattern['stddev'] * math.sqrt(-2*math.log(u1)) * math.cos(2*math.pi*u2)
        if not math.isfinite(value): fail('VALUE_OUT_OF_RANGE', 'pattern.gauss', 'nonfinite sample')
    sign = pattern['sign']
    negative = sign == 'negative' or sign == 'alternating' and index % 2 == 1
    if sign == 'random': negative = bool(next(stream) & 1)
    return -value if negative else value


def prepare_tensor(spec, case_seed=0, max_object_bytes=MAX_OBJECT_BYTES):
    obj(spec, ('name', 'shape', 'dtype', 'fp8_format', 'fp4_format', 'role', 'generation', 'layout', 'tensor'), 'tensor')
    name = spec.get('name')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', name):
        fail('INVALID_NAME', 'tensor.name', 'safe ASCII name required')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{prefix}{i}' for prefix in ('COM', 'LPT') for i in range(1, 10)}
    if name.endswith('.') or name.split('.')[0].upper() in reserved: fail('INVALID_NAME', name, 'nonportable name')
    dims = spec.get('shape')
    if not isinstance(dims, list) or len(dims) not in (1, 2, 3) or any(type(x) is not int or x <= 0 for x in dims):
        fail('INVALID_SHAPE', name + '.shape', 'one to three positive integers required')
    dims = [1] * (3 - len(dims)) + dims
    requested_dtype = spec.get('dtype')
    if requested_dtype in ('fp8', 'fp4'):
        key = requested_dtype + '_format'
        choices = ('e5m2', 'e4m3') if requested_dtype == 'fp8' else ('e2m1', 'e1m2')
        variant = enum(spec.get(key), choices, name + '.' + key)
        dtype = requested_dtype + '_' + variant
    else:
        dtype = enum(requested_dtype, SUPPORTED, name + '.dtype', 'UNSUPPORTED_FEATURE')
    for family, choices in (('fp8', ('e5m2', 'e4m3')), ('fp4', ('e2m1', 'e1m2'))):
        key = family + '_format'
        if key in spec:
            variant = enum(spec[key], choices, name + '.' + key)
            if dtype != family + '_' + variant:
                fail('INVALID_PARAMETER', name + '.' + key, 'requires matching ' + family.upper() + ' dtype')
    role = spec.get('role', 'input')
    if not isinstance(role, str) or not role: fail('INVALID_PARAMETER', name + '.role', 'nonempty string required')
    layout = build_layout(dims, dtype, spec.get('layout', {}))
    integer(max_object_bytes, max_object_bytes, 1)
    if layout['payload_bytes'] > max_object_bytes: fail('RESOURCE_LIMIT', name + '.shape', 'object payload exceeds budget')
    if layout['logical_elements'] * 64 + layout['payload_bytes'] * 3 > MAX_WORKING_BYTES:
        fail('RESOURCE_LIMIT', name + '.shape', 'materialized API exceeds 512MiB working estimate')
    gen = copy.deepcopy(spec.get('generation', {}))
    obj(gen, ('mode', 'pattern', 'seed', 'quantize_rm', 'overflow_policy', 'denormal_policy', 'special_values', 'values', 'raw_bits', 'fields'), name + '.generation')
    mode = enum(gen.get('mode', 'numeric'), ('numeric', 'raw_bits'), 'generation.mode', 'UNSUPPORTED_FEATURE')
    seed = integer(gen.get('seed', case_seed), 'generation.seed', 0, 2**64-1, 'INVALID_SEED')
    gen.update({'mode': mode, 'seed': seed}); count = layout['logical_elements']
    if mode == 'raw_bits':
        if any(key in gen for key in ('pattern', 'quantize_rm', 'overflow_policy', 'denormal_policy', 'special_values')):
            fail('INVALID_PARAMETER', 'generation', 'raw_bits cannot use numeric policies/pattern/injection')
        sources = [key for key in ('values', 'raw_bits', 'fields') if key in gen]
        if len(sources) != 1: fail('INVALID_PARAMETER', 'generation', 'choose exactly one values/raw_bits/fields')
        if sources[0] == 'fields': gen['fields'] = _validate_fields(gen['fields'], dtype, 'generation.fields')
        else:
            vals = gen.pop(sources[0])
            if not isinstance(vals, list) or len(vals) != count: fail('VALUE_COUNT_MISMATCH', 'generation.values', 'count differs from shape product')
            gen['values'] = [raw_code(v, BITS[dtype], f'{name}.generation.values[{i}]') for i, v in enumerate(vals)]
    else:
        if any(key in gen for key in ('values', 'raw_bits', 'fields')): fail('INVALID_PARAMETER', 'generation', 'numeric values belong in pattern.values')
        gen['quantize_rm'] = enum(gen.get('quantize_rm', 'RNE'), ('RNE',), 'generation.quantize_rm', 'UNSUPPORTED_FEATURE')
        gen['overflow_policy'] = enum(gen.get('overflow_policy', 'error'), ('error', 'inf', 'saturate'), 'generation.overflow_policy')
        gen['denormal_policy'] = enum(gen.get('denormal_policy', 'exclude'), ('allow', 'exclude', 'inject'), 'generation.denormal_policy')
        if dtype.startswith('int') and gen['overflow_policy'] == 'inf': fail('INVALID_PARAMETER', 'generation.overflow_policy', 'inf invalid for integers')
        pattern = gen.get('pattern', {'kind': 'zeros'})
        if isinstance(pattern, str): pattern = {'kind': pattern}
        if not isinstance(pattern, dict): fail('INVALID_SPEC', 'pattern', 'object required')
        kind = enum(pattern.get('kind'), ('zeros', 'ones', 'sign_alt', 'coordinate', 'explicit', 'integer_uniform', 'uniform', 'atom_lane_tag', 'exponent_sweep', 'loguniform', 'gauss'), 'pattern.kind', 'UNSUPPORTED_FEATURE')
        if kind in ('atom_lane_tag', 'exponent_sweep', 'loguniform', 'gauss'): special = _special_pattern(pattern, dtype)
        else:
            allowed = set(pattern) if kind == 'explicit' else {'kind'} | ({'values'} if kind == 'explicit' else {'min', 'max'} if kind in ('uniform', 'integer_uniform') else set())
            obj(pattern, allowed, 'pattern')
        if kind == 'explicit':
            vals = pattern.get('values')
            if not isinstance(vals, list) or len(vals) != count: fail('VALUE_COUNT_MISMATCH', 'pattern.values', 'count differs from shape product')
            for i, val in enumerate(vals):
                number(val, f'pattern.values[{i}]')
                if dtype.startswith('int') and type(val) is not int: fail('INVALID_VALUE', f'pattern.values[{i}]', 'integer required')
        if kind in ('uniform', 'integer_uniform'):
            lo = number(pattern.get('min'), 'pattern.min'); hi = number(pattern.get('max'), 'pattern.max')
            if lo > hi: fail('INVALID_RANGE', 'pattern', 'min must not exceed max')
            if kind == 'integer_uniform':
                if type(lo) is not int or type(hi) is not int or hi - lo + 1 > 2**64: fail('INVALID_RANGE', 'pattern', 'integer interval width <= 2**64 required')
            elif dtype.startswith('int'): fail('INVALID_PARAMETER', 'pattern', 'use integer_uniform for integers')
        gen['pattern'] = pattern
    gen['special_values'] = validate_specials(gen.get('special_values', []), dtype, count)
    if gen['denormal_policy'] == 'inject' and not any(x['kind'] == 'denormal' for x in gen['special_values']):
        fail('INVALID_PARAMETER', 'generation.denormal_policy', 'inject requires denormal entry')
    return {'name': name, 'shape': dims, 'dtype': dtype, 'role': role, 'generation': gen, 'layout': layout}


def prepare_case(case, max_object_bytes=MAX_OBJECT_BYTES, max_case_bytes=MAX_CASE_BYTES):
    obj(case, ('schema_version', 'case_seed', 'tensors'), 'case')
    enum(case.get('schema_version', 'tensor_spec_v1'), ('tensor_spec_v1',), 'case.schema_version')
    seed = integer(case.get('case_seed', 0), 'case.case_seed', 0, 2**64-1, 'INVALID_SEED')
    tensors = case.get('tensors')
    if not isinstance(tensors, list) or not tensors: fail('INVALID_SPEC', 'case.tensors', 'nonempty array required')
    prepared = [prepare_tensor(t, seed, max_object_bytes) for t in tensors]
    names = [t['name'].casefold() for t in prepared]
    if len(set(names)) != len(names): fail('INVALID_NAME', 'case.tensors', 'names must be unique, also ignoring case')
    integer(max_case_bytes, 'max_case_bytes', 1)
    if sum(t['layout']['payload_bytes'] for t in prepared) > max_case_bytes: fail('RESOURCE_LIMIT', 'case', 'case payload exceeds budget')
    return prepared


def _float_bits(dtype, value, policy):
    e, f = FLOATS[dtype]; sign = (1 << (e+f)) if value < 0 else 0
    maximum = {'fp16': 65504.0, 'bf16': float.fromhex('0x1.ffp127'), 'fp32': float.fromhex('0x1.fffffep127'),
               'fp8_e5m2': 114688.0, 'fp8_e4m3': 480.0,
               'fp4_e2m1': 6.0, 'fp4_e1m2': 3.5}[dtype]
    if abs(value) > maximum:
        if policy == 'error': fail('VALUE_OUT_OF_RANGE', 'numeric', 'value exceeds ' + dtype + ' finite range')
        if dtype in FINITE_FLOATS:
            return sign | ((1 << (e+f)) - 1)
        return sign | (((1 << e) - 2) << f) | ((1 << f) - 1) if policy == 'saturate' else ((1 << e) - 1) << f
    if dtype in FINITE_FLOATS:
        return _finite_bits(dtype, value)
    if dtype == 'bf16':
        bits = int.from_bytes(struct.pack('>f', value), 'big'); hi, lo = bits >> 16, bits & 0xffff
        return (hi + (lo > 0x8000 or (lo == 0x8000 and hi & 1))) & 0xffff
    return int.from_bytes(struct.pack('>e' if dtype == 'fp16' else '>f', value), 'big')


def _finite_bits(dtype, value):
    """RNE against the finite codebook, including the zero/minimum gap."""
    e, f = FLOATS[dtype]; sign = (1 << (e+f)) if math.copysign(1.0, value) < 0 else 0
    value = abs(value); table = finite_table(dtype)
    upper = bisect_left(table, value)
    if upper == 0: return sign
    if upper == len(table): return sign | (len(table) - 1)
    midpoint = (table[upper-1] + table[upper]) / 2
    code = upper if value > midpoint or (value == midpoint and upper % 2 == 0) else upper - 1
    return sign | code


def _encoded_values(t):
    gen = t['generation']; dtype = t['dtype']; n = t['layout']['logical_elements']
    stream = u64_stream(gen['seed'], t['name'], t['role'])
    if gen['mode'] == 'raw_bits':
        if 'values' in gen: return list(gen['values']), []
        fields = gen['fields']; e, f = FLOATS[dtype]; values = []
        for _ in range(n):
            signs = fields['sign']['values']; sign = signs[uniform_int(0, len(signs)-1, stream)]
            exp = uniform_int(fields['exponent']['min'], fields['exponent']['max'], stream)
            fraction = uniform_int(fields['fraction']['min'], fields['fraction']['max'], stream)
            values.append((sign << (e+f)) | (exp << f) | fraction)
        return values, []
    pattern = gen['pattern']; kind = pattern['kind']; values = []
    for i in range(n):
        if kind == 'explicit': value = pattern['values'][i]
        elif kind == 'zeros': value = 0
        elif kind == 'ones': value = 1
        elif kind == 'sign_alt': value = -1 if i & 1 else 1
        elif kind == 'coordinate': value = i
        elif kind in ('atom_lane_tag', 'exponent_sweep', 'loguniform', 'gauss'): value = _pattern_value(pattern, t, i, stream)
        elif kind == 'integer_uniform': value = uniform_int(pattern['min'], pattern['max'], stream)
        else:
            u = (next(stream) >> 11) * 2**-53; lo, hi = pattern['min'], pattern['max']
            value = (1-u)*lo + u*hi
            if lo < hi: value = min(value, math.nextafter(hi, lo))
        if dtype.startswith('int'):
            lo, hi = (-(1 << (BITS[dtype]-1)), (1 << (BITS[dtype]-1))-1)
            if not lo <= value <= hi:
                if gen['overflow_policy'] == 'error': fail('VALUE_OUT_OF_RANGE', f'{t["name"]}.numeric[{i}]', 'integer outside dtype range')
                value = max(lo, min(hi, value))
            code = value & ((1 << BITS[dtype]) - 1)
        else:
            code = _float_bits(dtype, value, gen['overflow_policy']); e, f = FLOATS[dtype]
            if dtype not in FINITE_FLOATS and gen['denormal_policy'] == 'allow' and code & (((1 << e) - 1) << f) == 0 and code & ((1 << f) - 1):
                fail('VALUE_OUT_OF_RANGE', f'{t["name"]}.numeric[{i}]', 'encoded subnormal excluded')
        values.append(code)
    return _inject(t, values)


def _inject(t, values):
    gen = t['generation']; entries = gen['special_values']
    if not entries: return values, []
    dtype = t['dtype']; e, f = FLOATS[dtype]; signbit = 1 << (e+f); exp = ((1 << e) - 1) << f
    stream = u64_stream(gen['seed'], t['name'], t['role'], 'injection')
    reserved = {p for item in entries for p in item.get('positions', [])}
    swaps = {}; cursor = 0; n = len(values)
    def next_position():
        nonlocal cursor
        while cursor < n:
            j = uniform_int(cursor, n-1, stream)
            selected = swaps.pop(j, j)
            if j != cursor: swaps[j] = swaps.pop(cursor, cursor)
            cursor += 1
            if selected not in reserved: return selected
        fail('INVALID_PARAMETER', 'special_values', 'not enough free positions')
    actual = []
    for item in entries:
        positions = item.get('positions')
        if positions is None: positions = [next_position() for _ in range(item['resolved_count'])]
        kind = item['kind']
        for pos in positions:
            if kind == 'nan': code = item.get('payload', exp | ((1 << f) - 1))
            elif kind == 'denormal':
                sign = item['sign']; negative = (next(stream) & 1) if sign == 'random' else sign == 'negative'
                code = (signbit if negative else 0) | item['fraction']
            else: code = {'+0': 0, '-0': signbit, '+inf': exp, '-inf': exp | signbit}[kind]
            values[pos] = code
        entry = {**item, 'positions': list(positions)}
        if dtype in FINITE_FLOATS:
            entry['interpretation'] = 'signed_zero' if kind in ('+0', '-0') else 'finite_boundary_bits'
        actual.append(entry)
    return values, actual


def _pack(values, dtype, nibble):
    if BITS[dtype] == 4:
        out = bytearray((len(values)+1)//2)
        for i, value in enumerate(values):
            shift = (i % 2) * 4 if nibble == NIBBLES[0] else (1 - i % 2) * 4
            out[i//2] |= value << shift
        return bytes(out)
    width = BITS[dtype] // 8
    return b''.join(value.to_bytes(width, 'little') for value in values)


def materialize(t):
    values, actual = _encoded_values(t); d0 = t['shape'][2]; layout = t['layout']; payload = bytearray()
    for start in range(0, len(values), d0):
        row = _pack(values[start:start+d0], t['dtype'], layout['int4_nibble_order'])
        payload.extend(row); payload.extend(bytes(layout['row_bytes'] - len(row)))
    payload = bytes(payload); generation = copy.deepcopy(t['generation']); generation['stream_version'] = 2
    if generation['mode'] == 'numeric' and generation['pattern']['kind'] in ('atom_lane_tag', 'exponent_sweep', 'loguniform', 'gauss'):
        generation['pattern_version'] = 1
    if generation['mode'] == 'numeric': generation['actual_special_values'] = actual
    codec = {'version': 'ordinary v2', 'element_bits': BITS[t['dtype']], 'byte_order': 'little',
             'int4_nibble_order': layout['int4_nibble_order'], 'quantize_rm': generation.get('quantize_rm'),
             'numeric_source': 'none' if generation['mode'] == 'raw_bits' else 'binary32' if t['dtype'] == 'bf16' else 'python_number'}
    if t['dtype'] in FINITE_FLOATS:
        e, f = FLOATS[t['dtype']]
        family = t['dtype'].split('_')[0]
        codec.update({family + '_format': t['dtype'][4:]})
        codec.update({'profile': 'hhm056_finite_normal_v1',
                      'exponent_bits': e, 'fraction_bits': f, 'exponent_bias': (1 << (e-1)) - 1,
                      'max_exponent_policy': 'finite', 'zero_exponent_policy': 'normal except signed zero',
                      'supports_inf': False, 'supports_nan': False, 'supports_subnormal': False,
                      'min_positive': finite_table(t['dtype'])[1], 'max_finite': finite_table(t['dtype'])[-1],
                      'underflow_policy': 'rne to zero or minimum',
                      'special_values_semantics': 'legacy boundary bits',
                      'overflow_inf_policy': 'saturate', 'version': 'finite_normal_v1'})
    content_digest = hashlib.sha256(payload).hexdigest()
    layout_digest = digest({'shape': t['shape'], 'dtype': t['dtype'], 'layout': layout})
    return {**t, 'generation': generation, 'values': values, 'payload': payload, 'codec': codec,
            'content_digest': content_digest, 'layout_digest': layout_digest,
            'stats': {'bound': 'None', 'comparisons': [],
                      'content_digest': content_digest, 'layout_digest': layout_digest}}


def generate_tensor(spec, case_seed=0, *, max_object_bytes=MAX_OBJECT_BYTES):
    integer(case_seed, 'case.seed', 0, 2**64-1, 'INVALID_SEED')
    return materialize(prepare_tensor(spec, case_seed, max_object_bytes))


def generate_case(case, *, max_object_bytes=MAX_OBJECT_BYTES, max_case_bytes=MAX_CASE_BYTES):
    prepared = prepare_case(case, max_object_bytes, max_case_bytes)
    if sum(t['layout']['logical_elements'] * 64 + t['layout']['payload_bytes'] * 3 for t in prepared) > MAX_WORKING_BYTES:
        fail('RESOURCE_LIMIT', 'case', 'materialized batch exceeds working memory estimate; use CLI')
    return [materialize(t) for t in prepared]
