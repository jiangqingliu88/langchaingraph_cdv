"""Explicit ISA contracts; directory names must not silently change encoding."""
from __future__ import annotations

LEGACY_REVISION = 'ISA_VERSION_V1.4'
# The v0.3 reviewed-XLSX contract was retired on 2026-11-07; V1.4 is the sole contract.
DEFAULT_REVISION = LEGACY_REVISION
REVISION_ALIASES = {
    'v1.4': LEGACY_REVISION,
    LEGACY_REVISION: LEGACY_REVISION,
    # Retired 2026-11-07 label; accepted so already-resolved seq.ir files stay
    # readable. Operand encodings are still revalidated against the V1.4 table.
    'xlsx_v0.3_reviewed': LEGACY_REVISION,
}
REVISION_CHOICES = tuple(REVISION_ALIASES)
ADDRESS_SCHEMAS = {
    LEGACY_REVISION: 'GLOBAL48_V1.4',
}
ADDRESS_SCHEMA_ALIASES = {
    'global48_xlsx_v0.3_reviewed': 'GLOBAL48_V1.4',
}


def normalize_revision(value=None):
    value = DEFAULT_REVISION if value is None else value
    if not isinstance(value, str) or value not in REVISION_ALIASES:
        raise ValueError(f'UNSUPPORTED_ISA_REVISION: {value!r}; only ISA_VERSION_V1.4 is available')
    return REVISION_ALIASES[value]


def address_schema(revision=None):
    return ADDRESS_SCHEMAS[normalize_revision(revision)]


def normalize_address_schema(value):
    return ADDRESS_SCHEMA_ALIASES.get(value, value)


def version_metadata(revision=None):
    revision = normalize_revision(revision)
    return {'isa_revision': revision, 'address_schema': address_schema(revision)}
