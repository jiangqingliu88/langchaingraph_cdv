"""Resolve tensor-backed preload operations; no simulation memory access."""
from __future__ import annotations
from .ir_isa import ISAError, global_address_parts
from .isa_versions import version_metadata


class MemInitError(ValueError):
    pass


def resolve_mem_init(flow, fields, generated, line):
    """Return executable metadata, or None for explicitly external TB loads."""
    if fields.get('resolve') is False or 'file' in fields or 'map file' in fields:
        return None
    ref = fields.get('ref')
    if not isinstance(ref, str) or (ref not in flow.tensors and ref not in flow.views):
        raise MemInitError('unknown tensor/view ref; supply file/map file or resolve=false for an external TB operation')
    context = flow._context_for(ref, line)
    root = context['source_tensor']
    items = {item['name']: item for item in generated}
    if root not in items:
        raise MemInitError('ref has no generated payload; reserve_output is not initial data')
    tensor = items[root]
    root_shape = tensor['shape']
    source_row = tensor['layout']['row_bytes']
    source_plane = root_shape[1] * source_row
    file_offset = 0
    current = ref
    while current in flow.views:
        view = flow.views[current]
        if view.get('kind') == 'transform':
            raise MemInitError('transform view has no transformed payload; initialize its source before DUT transfer')
        if view.get('kind') == 'slice':
            selection = view['slice']
            file_offset += selection.get('dim2', 0) * source_plane + selection.get('dim1', 0) * source_row
            current = view['parent']
        else:
            # Allocation views may change destination strides, but cannot
            # reinterpret the file's logical axes without an explicit map.
            if flow._context_for(current, line)['shape'] != root_shape:
                raise MemInitError('reshaped allocation requires an explicit file/map file load')
            break
    shape = context['shape']
    layout = context['layout']
    if context['dtype'] != tensor['dtype'] or layout['row_bytes'] != source_row:
        raise MemInitError('view dtype/row width differs from payload; use an explicit load map')
    if layout.get('int4_nibble_order') != tensor['layout'].get('int4_nibble_order'):
        raise MemInitError('view INT4 nibble order differs from payload; initialize its source before DUT conversion')
    placement = context['placement']
    region = placement.get('region')
    base = placement.get('base', placement.get('address'))
    if not isinstance(region, str) or not region:
        raise MemInitError('target region is required')
    if type(base) is not int or not 0 <= base < 1 << 48:
        raise MemInitError('target base must be an unsigned 48-bit byte address')
    fmt = fields.get('format', 'bin')
    if fmt not in ('bin', 'hex'):
        raise MemInitError('tensor-backed mem_init supports format=bin or hex')
    payload = next((p for p in tensor['payloads'] if p['format'] == fmt), None)
    if payload is None:
        raise MemInitError(f'generated {fmt} payload is unavailable')
    endpoint = {}
    if region.startswith('lmem_'):
        address_kind = 'local'
        place = placement.get('place', {})
        for name, width in (('chip', 9), ('die', 2), ('cluster', 2), ('core', 4)):
            value = place.get(name, flow.profile.get(name + '_id', 0))
            if type(value) is not int or not 0 <= value < 1 << width:
                raise MemInitError(f'invalid endpoint {name}')
            endpoint[name] = value
    else:
        # All DRAM descriptors emit a full global48 base so the Player has a
        # single addressing convention. A `.bind` may still give a local
        # 29-bit alias for dram_common; it is expanded here using place/profile.
        address_kind = 'global48'
        expected_mem = {'dram_share': 1, 'dram_common': 2}[region]
        if (base >> 33) & 3 != expected_mem:
            if region == 'dram_share':
                raise MemInitError(
                    'dram_share mem_init requires a full global48 base; a local share alias is not defined')
            if base >> 29:
                raise MemInitError(
                    f'dram_common base 0x{base:x}: upper bits are set but Full_addr[34:33] '
                    f'!= {expected_mem}; use either a full global48 address or a plain 29-bit local alias')
            place = placement.get('place', {})
            endpoint_parts = {}
            for name, width in (('chip', 9), ('die', 2), ('cluster', 2), ('core', 4)):
                value = place.get(name, flow.profile.get(name + '_id', 0))
                if type(value) is not int or not 0 <= value < 1 << width:
                    raise MemInitError(f'invalid endpoint {name}')
                endpoint_parts[name] = value
            base = ((endpoint_parts['chip'] << 39) | (endpoint_parts['die'] << 37)
                    | (endpoint_parts['cluster'] << 35) | (expected_mem << 33)
                    | (endpoint_parts['core'] << 29) | base)
    try:
        global_address_parts(base, region, placement.get('place'), flow.profile)
    except ISAError as exc:
        raise MemInitError(f'{exc.code}: {exc}') from exc
    count = shape[0] * shape[1]
    last_file_byte = file_offset + (shape[0] - 1) * source_plane + (shape[1] - 1) * source_row + source_row
    if last_file_byte > tensor['layout']['payload_bytes']:
        raise MemInitError('selected rows exceed tensor payload')
    result = {
        'schema': 'mem_init_v1', 'ref': ref, 'source_tensor': root,
        **version_metadata(getattr(flow, 'isa_revision', None)),
        'path': fields.get('path', 'backdoor'),
        'file': payload['file'], 'format': fmt,
        'region': region, 'address_kind': address_kind, 'base': base,
        **({'endpoint': endpoint} if endpoint else {}),
        'shape': shape, 'dtype': context['dtype'],
        'element_bits': layout['element_bits'],
        'byte_order': tensor['codec']['byte_order'],
        'file_offset_bytes': file_offset,
        'file_row_stride_bytes': source_row,
        'file_plane_stride_bytes': source_plane,
        'dst_row_stride_bytes': 32 * layout['stride_dim1'],
        'dst_plane_stride_bytes': 32 * layout['stride_dim2'],
        'copy_row_bytes': source_row, 'copy_bytes': count * source_row,
        'span_bytes': layout['span_bytes'],
        'payload_bytes': tensor['layout']['payload_bytes'],
        'file_size_bytes': payload['bytes'], 'file_sha256': payload['sha256'],
        'content_sha256': tensor['content_digest'],
        'tail_policy': layout['tail_policy'], 'gap_policy': 'untouched',
    }
    if fmt == 'hex':
        result['hex_encoding'] = 'byte_tokens_low_address_first'
    if layout.get('int4_nibble_order'):
        result['int4_nibble_order'] = layout['int4_nibble_order']
    # A symbolic mapping annotation is consumed, never sent as a TB dependency.
    for key, value in fields.items():
        if key in {'format', 'ref', 'mapping', 'resolve'}:
            continue
        if key in result and result[key] != value:
            raise MemInitError(f'{key} conflicts with tensor/view metadata; change the bind/view instead')
        result[key] = value
    return result
