"""Operand definitions for the ISA VERSION V1.4 contract.

Authority: [HMN057]-[ISA]-编程模型-修改版本-ALL.docx, 2026-10-22.
Page numbers are legacy PDF locators; Word table references take precedence.
This is an operand assembler, not an execution or data-content model.
The reviewed v0.3 XLSX contract was retired on 2026-11-07; V1.4 is the sole contract.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from .isa_versions import LEGACY_REVISION, normalize_revision, address_schema


class ISAError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class Instruction:
    funct7: int
    flags: str  # xd, xs1, xs2 (in that order)
    rs1: str
    rs2: str
    page: int
    # An internal ISA source contradiction must not be silently guessed.
    issue: str = ""
    opcode_issue: str = ""


INSTRUCTIONS: dict[str, Instruction] = {}

ISA_REVISION = LEGACY_REVISION  # exported compatibility constants
ADDRESS_SCHEMA = address_schema(ISA_REVISION)
REMOVED_INSTRUCTIONS = {
    'rd_csr_drv_xn', 'wr_csr_drv_xn', 'csr_rd_drv_xn', 'csr_wr_drv_xn',
    'csr_rd_drv', 'csr_wr_drv',
    'noc_dst_drv_xn', 'noc_src_drv_xn', 'noc_drv_dst_xn', 'noc_drv_src_xn',
    'gemm_sc_pre_xn', 'gemm_mx_sc_pre_xn',
}


def validate_opcode(name):
    if name in REMOVED_INSTRUCTIONS:
        raise ISAError('REMOVED_ISA_OPCODE', f'{name} was removed from Word v1.4; raw_cmd remains available for illegal encoding injection')


def _add(name, funct7, flags, rs1="-", rs2="-", page=0, issue=""):
    INSTRUCTIONS[name] = Instruction(funct7, flags, rs1, rs2, page, issue)


# Operand descriptors: kind:role. L=8-bit LMEM byte address,
# D=29-bit local DRAM byte address, G=full_addr[34:3],
# Q=local DRAM[28:3] (VNICE rs1), H=global DRAM[28:3], S=raw scalar.
# P1/P2=die/cluster pre; N1/N2/N0=compressed NoC fields.
_add("group_mask_drv_xn", 0x00, "010", "S:mask", page=34)
_add("npu_cfg_drv_xn", 0x01, "011", "S:cfg_rs1", "S:cfg_rs2", 35)
for suffix, write, read, in (("xn", 2, 3), ("vn01", 8, 10), ("vn11", 9, 11)):
    _add(f"wr_lmem_drv_{suffix}", write, "011", "L:dst", "S:value", 37)
    _add(f"rd_lmem_drv_{suffix}", read, "110", "L:src", page=38)
_add("sync_drv_xn", 4, "100", page=40)
_add("fast_sync_drv_xn", 4, "000", page=40)
_add("noc_drv_xn", 0x11, "011", "N0:src", "N3:dst", 45)
_add("noc_fence_drv_xn", 0x11, "100", page=47)
_add("fast_noc_fence_drv_xn", 0x11, "000", page=47)
for suffix, code in (("vn01", 0x10), ("vn11", 0x11)):
    _add(f"noc_drv_{suffix}", code, "011", "N1:src", "N4:dst", 48)

_add("die_cluster_rs2_pre_xn", 0x20, "001", "-", "P2:address", 56)
_add("die_cluster_rs2_pre_vn", 0x20, "001", "-", "P2:address", 57)
_add("die_cluster_rs1_pre_xn", 0x20, "010", "P1:address", page=64)
_add("die_cluster_rs1_pre_vn", 0x21, "010", "P1:address", page=65,
     issue="Word VNICE rs1 pre [35:29] overlaps the new die/cluster [38:35]; raw operands require software review")
for stem, code in (("tld", 0x21), ("ttld", 0x22), ("tst", 0x23),
                   ("gtld", 0x27), ("gttld", 0x28), ("gtst", 0x29)):
    store = stem.endswith("tst")
    _add(f"{stem}_drv_xn", code, "011", "L:src" if store else "L:dst",
         ("G:" if stem.startswith("g") else "D:") + ("dst" if store else "src"), 57)
for stem, codes in (("tld", (0x20, 0x21)), ("tst", (0x22, 0x23)),
                    ("gtld", (0x2a, 0x2b)), ("gtst", (0x2c, 0x2d))):
    for suffix, code in zip(("vn01", "vn11"), codes):
        store = stem.endswith("tst")
        _add(f"{stem}_drv_{suffix}", code, "011", "L:src" if store else "L:dst",
             ("G:" if stem.startswith("g") else "D:") + ("dst" if store else "src"), 57 if stem != "gtst" else 58)

_add("tmov_dram_drv_xn", 0x2c, "011", "D:dst", "D:src", 60)
_add("gtld_dram_drv_xn", 0x2a, "011", "D:dst", "G:src", 60)
_add("gtst_dram_drv_xn", 0x2b, "011", "D:src", "G:dst", 60)
for stem, codes in (("tmov_dram", (0x1e, 0x1f)), ("gtld_dram", (0x2e, 0x2f)),
                    ("gtst_dram", (0x1c, 0x1d))):
    for suffix, code in zip(("vn01", "vn11"), codes):
        store = stem.startswith("gtst")
        _add(f"{stem}_drv_{suffix}", code, "011", "Q:src" if store else "Q:dst",
             ("D:src" if stem == "tmov_dram" else "G:dst" if store else "G:src"), 60)
for stem, code, dst in (("gat2spad", 0x24, "L:dst"), ("gat2dram", 0x25, "D:dst"),
                        ("gat2gdram", 0x26, "G:dst")):
    _add(f"{stem}_drv_xn", code, "011", dst, "L:index", 65)
for stem, codes, dst in (("gat2spad", (0x24, 0x25), "L:dst"),
                         ("gat2dram", (0x26, 0x27), "Q:dst"),
                         ("gat2gdram", (0x18, 0x19), "H:dst")):
    for suffix, code in zip(("vn01", "vn11"), codes):
        issue = ("Word A.3.5 table uses [28:3], reconstruction still says [28:4]+4'b0; VNICE pre also retains obsolete [35:29]"
                 if stem == "gat2gdram" else "")
        _add(f"{stem}_drv_{suffix}", code, "011", dst, "L:index", 65, issue)

for stem, code in (("bc", 0x30), ("vbc", 0x31), ("trans_vbc", 0x32),
                   ("tmov", 0x33), ("ttmov", 0x34),
                   ("setCIMCexp", 0x35), ("getCIMCexp", 0x36)):
    _add(f"{stem}_drv_xn", code, "011", "L:dst", "S:scalar_in" if stem == "bc" else "L:src",
         {"bc": 68, "vbc": 70, "trans_vbc": 72, "tmov": 73, "ttmov": 74,
          "setCIMCexp": 77, "getCIMCexp": 77}[stem])
for suffix, code in (("vn01", 0x30), ("vn11", 0x31)):
    _add(f"bc_drv_{suffix}", code, "011", "L:dst", "S:scalar_in", 68)

for name, code, flags, left, right in [
    ("out_orig", 0x40, "011", "out", "orig"), ("out", 0x40, "010", "out", None),
    ("orig", 0x40, "001", None, "orig"), ("out_sc", 0x41, "011", "out", "scale"),
    ("mx_in", 0x42, "010", "mx_in", None), ("mx_out", 0x43, "011", "mx_in", "out"),
    ("mx_orig", 0x44, "011", "mx_in", "orig")]:
    _add(f"gemm_{name}_pre_xn", code, flags, "L:" + left if left else "",
         "L:" + right if right else "", 82)
for stem, code in (("gemm", 0x48), ("gemm_acc", 0x49), ("gemm_dq", 0x4c), ("gemm_dq_acc", 0x4b)):
    _add(f"{stem}_drv_xn", code, "011", "L:in", "L:wt", 82 if stem in ("gemm", "gemm_acc") else 83)

for name, code, flags, left, right, page in [
    ("vlv2_pre", 0x50, "011", "L:in1", "L:in2", 92),
    ("vls1_pre", 0x51, "011", "L:in1", "S:scalar_in1", 96),
    ("v2s2_pre", 0x52, "011", "L:in2", "S:scalar_in2", 96),
    ("f2m_pre", 0x52, "010", "L:out_mxexp", "-", 104),
    ("vv_v_drv", 0x58, "010", "L:out", "-", 92),
    ("vvv_v_drv", 0x58, "011", "L:out", "L:in3", 92),
    ("vs_v_drv", 0x59, "010", "L:out", "-", 96),
    ("vss_v_drv", 0x5a, "010", "L:out", "S:scalar_in2", 96),
    ("vssv_v_drv", 0x5a, "011", "L:out", "L:in3", 96),
    ("mv_m_drv", 0x5c, "010", "L:out", "-", 100),
    ("v_v_drv", 0x5b, "011", "L:out", "L:in1", 104),
    ("v_s_drv", 0x5b, "110", "L:in1", "-", 106),
    ("m_v_drv", 0x5c, "011", "L:out", "L:in1", 108)]:
    _add(f"{name}_xn", code, flags, left, right, page)
for stem, codes, flags, left, right, page in [
    ("vlv2_pre", (0x50, 0x51), "011", "L:in1", "L:in2", 92),
    ("vls1_pre", (0x52, 0x53), "011", "L:in1", "S:scalar_in1", 96),
    ("vv_v_drv", (0x58, 0x59), "010", "L:out", "-", 92),
    ("vs_v_drv", (0x5a, 0x5b), "010", "L:out", "-", 96),
    ("vss_v_drv", (0x58, 0x59), "011", "L:out", "S:scalar_in2", 96),
    ("mv_m_drv", (0x5c, 0x5d), "010", "L:out", "-", 100),
    ("v_s_drv", (0x58, 0x59), "110", "L:in1", "-", 106)]:
    for suffix, code in zip(("vn01", "vn11"), codes):
        _add(f"{stem}_{suffix}", code, flags, left, right, page)


# The reviewed v0.3 XLSX delta table was retired on 2026-11-07. The legacy
# table below is the sole contract; nothing here branches on a revision.


def instruction_table(isa_revision=None):
    return INSTRUCTIONS


def instruction(name, isa_revision=None):
    validate_opcode(name)
    table = instruction_table(isa_revision)
    if name not in table:
        raise ISAError("UNSUPPORTED_ISA_OPCODE", f"{name}: no encoding in ISA contract {normalize_revision(isa_revision)}")
    return table[name]


def catalog(isa_revision=None):
    return {name: asdict(spec) for name, spec in instruction_table(isa_revision).items()}


def unsigned(value, width, description):
    if type(value) is not int or not 0 <= value < 1 << width:
        raise ISAError("INVALID_OPERAND", f"{description} must be an unsigned {width}-bit integer")
    return value


def vector_variant(name):
    if name.endswith("_vn11"):
        return "vn11"
    if name.endswith("_vn01"):
        return "vn01"
    # A pre with xs1=0 has no rs1 vector, but its rs2 remains vector.
    if name == "die_cluster_rs2_pre_vn":
        return "vn01"
    if name == "die_cluster_rs1_pre_vn":
        return "vn11"
    return None


def mask_cores(mask):
    unsigned(mask, 6, "6b_grp_mask")
    return [4 * (mask >> 4) + lane for lane in range(4) if mask & (1 << lane)]


def selected_cores(name, fields, active, isa_revision=None):
    if not vector_variant(name):
        return sorted(active)
    if "core_ids" in fields:
        return fields["core_ids"]
    spec = instruction(name, isa_revision)
    operand = fields.get("rs1val" if spec.flags[1] == "1" else "rs2val")
    if operand is None:
        refs = [v for k, v in fields.items() if k in ("src", "dst", "index", "out", "in1", "in2") and isinstance(v, list)]
        if refs:
            return list(range(len(refs[0])))
        return [0]  # scalar single-core convenience; compiler still needs operands
    first = operand[0] if isinstance(operand, list) else operand
    return mask_cores(unsigned(first, 32, name) >> 26)


def _reference(fields, role, isa_revision=None):
    if role in fields:
        return fields[role]
    binding = fields.get("bind", {})
    if role in binding:
        return binding[role]
    aliases = {"out": "dst", "in": "src", "in1": "src", "index": "src", "scale": "dq"}
    alias = aliases.get(role)
    return fields.get(alias, binding.get(alias)) if alias else None


def _placement(flow, ref, line):
    place = flow._placement_for(ref, line)
    base = place.get("base", place.get("address"))
    if type(base) is not int or not 0 <= base < (1 << 48):
        raise ISAError("ADDRESS_OUT_OF_RANGE", f"{ref} byte address must fit 48 bits")
    return place, base


def global_address_parts(base, region='', endpoint=None, profile=None, *, carries_chip=False):
    """Decode/validate Word 2.7.3 global48; never translate a legacy address."""
    unsigned(base, 48, 'full addr')
    endpoint, profile = endpoint or {}, profile or {}
    chip, dc, mem = base >> 39, (base >> 35) & 15, (base >> 33) & 3
    if mem not in (1, 2):
        raise ISAError("INVALID_MEM_FLAG", f'g:global DRAM requires mem_flag=1 or 2, got {mem}')
    if region in ('dram_share', 'dram_common') and mem != {'dram_share': 1, 'dram_common': 2}[region]:
        raise ISAError("INVALID_REGION", 'region and Word Full_addr[34:33] disagree')
    core = (base >> 12 if mem == 1 else 29) & 15
    for name, actual in (('chip', chip), ('die', dc >> 2), ('cluster', dc & 3), ('core', core)):
        if name in endpoint and endpoint[name] != actual:
            raise ISAError("INVALID_PLACEMENT", f"{name} conflicts with Word Full_addr")
    if chip and not carries_chip and profile.get('chip_id') != chip:
        raise ISAError("UNBOUND_CHIP_ID", "nonzero Full_addr[47:39] requires matching .profile chip_id; operands do not carry chip_id")
    return dict(chip_id=chip, die_cluster=dc, mem_flag=mem, core_id=core)


def _operand(flow, action, descriptor, ref, core, state):
    kind, role = descriptor.split(':')
    fields, line = action['fields'], action['source']['line']
    revision = getattr(flow, 'isa_revision', ISA_REVISION)
    spec = instruction(action['op'], revision)
    if kind == "*":
        raise ISAError("ISA_SOURCE_CONFLICT", f"{action['op']}: {instruction(action['op']).issue}; supply raw operands until the PDF is clarified")
    if kind == "S":
        return unsigned(ref, 32, role)
    place, base = _placement(flow, ref, line)
    region = place.get("region", "")
    endpoint = place.get("place", {})
    if kind == "L":
        if region and not region.startswith("lmem_"):
            raise ISAError("INVALID_REGION", f"{ref} must be LMEM, got {region}")
        offset = fields.get("offset", 0) if "lmem_drv" in action['op'] else 0
        unsigned(offset, 32, "byte offset")
        if base + offset >= 1 << 18:
            raise ISAError("ADDRESS_OUT_OF_RANGE", f"{ref} LMEM address must fit 18 bits")
        address = base + offset
        if "lmem_drv" in action['op']:
            if address & 3:
                raise ISAError("MISALIGNED_ADDRESS", "LMEM word address must be 4-byte aligned")
            if address & (1 << 17) or region.endswith("cimc"):
                raise ISAError("INVALID_REGION", "wr/rd lmem supports SPAD only, not CIMC")
            if offset + 4 > flow._context_for(ref, line)["layout"]["span_bytes"]:
                raise ISAError("ADDRESS_OUT_OF_VIEW", "LMEM word exceeds the declared view span")
        return address
    if kind in ("D", "Q"):
        if region and region != "dram_common":
            raise ISAError("INVALID_REGION", f"{ref} must be local Common DRAM")
        # dram_common accepts either a plain 29-bit local alias or a full
        # global48 address. Both normalize down to the local 29-bit form that
        # the executing core's local TLD/TST operand expects. A base that is
        # larger than a 29-bit local alias but lacks the Common mem flag bits
        # is just an oversized local offset, not a malformed global; keep the
        # historic width-style error so callers can diagnose clearly.
        if base >> 29:
            if ((base >> 33) & 3) != 2:
                raise ISAError("INVALID_OPERAND",
                               f"{ref}: local DRAM byte address must fit 29 bits, got 0x{base:x}")
            parts = global_address_parts(base, region, endpoint, flow.profile)
            if parts['core_id'] != core:
                raise ISAError("INVALID_PLACEMENT",
                               f"{ref} Full_addr core_id={parts['core_id']} is not the executing core {core}")
            base &= (1 << 29) - 1
        unsigned(base, 29, f"{ref} local DRAM byte address")
        if kind == "Q" and base & 7:
            raise ISAError("MISALIGNED_ADDRESS", "VNICE local DRAM rs1 address must be 8-byte aligned ([28:3])")
        return base >> 3 if kind == "Q" else base
    if kind in ("G", "H", "P1", "P2", "P13"):
        # G/H/P operands take a FULL 48-bit address. An offset and endpoint
        # must not silently be confused with an already encoded Full addr.
        if base & 7:
            raise ISAError("MISALIGNED_ADDRESS", "global DRAM operand [34:3] requires 8-byte alignment")
        if region and not region.startswith("dram_"):
            raise ISAError("INVALID_REGION", f"{ref} must be DRAM")
        parts = global_address_parts(base, region, endpoint, flow.profile, carries_chip=kind == 'P13')
        dc = parts['die_cluster']
        if kind.startswith("P"):
            if kind == "P13":
                return base >> 35  # current XLSX F6: Full_addr[47:35]
            if kind == "P1" and vector_variant(action['op']):
                raise ISAError("ISA_SOURCE_CONFLICT", "Word 4.3.5 VNICE rs1 pre [35:29] overlaps die/cluster [38:35]; supply raw operands pending clarification")
            return dc
        pre_role = "rs1" if role == "dst" and action['op'].startswith("gat") else "rs2"
        required = {'die_cluster': dc}
        if kind == "H":
            required['mem_core'] = (base >> 29) & 127
        fields.setdefault("address_requirements", {}).setdefault(str(core), {})[pre_role] = {
            **required, 'chip_id': base >> 39, 'address_schema': address_schema(revision),
            "full_addr": base, "pre_observed": state.get((core, "glsu", pre_role)),
        }
        # chip id is NOT carried by any listed operand/pre. Its origin must
        # be supplied by the integration profile, never dropped silently.
        return (base >> 3) & 0xffffffff if kind == "G" else (base >> 3) & ((1 << 26) - 1)
    if kind.startswith("N"):
        unsigned(base, 18, f"{ref} NoC LMEM byte address")
        if region and not region.startswith("lmem_"):
            raise ISAError("INVALID_REGION", f"{ref} NoC endpoint must be LMEM")
        die, cluster = endpoint.get("die", flow.profile.get('die_id', 0)), endpoint.get("cluster", flow.profile.get('cluster_id', 0))
        dc = (unsigned(die, 2, "die_id") << 2) | unsigned(cluster, 2, "cluster_id")
        target_core = unsigned(endpoint.get("core", core), 4, "core_id")
        if kind == "N0":
            return (target_core << 22) | (dc << 18) | base
        if kind == "N1":
            return (dc << 18) | base
        result = (target_core << 18) | base
        if kind in ("N2", "N4"):
            result |= dc << 22
        if kind == "N4":
            flag = fields.get("src_dst_flag")
            if isinstance(flag, list):
                flag = flag[fields["core_ids"].index(core)]
            result |= unsigned(flag, 1, "src_dst_flag") << 31
        return result
    raise ISAError("UNSUPPORTED_OPERAND", descriptor)


def project_action(flow, action, active, state):
    """Resolve only missing operands; hand-encoded words remain unchanged.

    State is informational per-core pre state. Missing/mismatched state is
    reported in metadata; no forced pre/cfg insertion or produced-state check.
    """
    name, fields = action["op"], action["fields"]
    revision = getattr(flow, 'isa_revision', ISA_REVISION)
    validate_opcode(name)
    spec = instruction_table(revision).get(name)
    if spec is None or name == "npu_cfg_drv_xn":
        return
    explicit = {key for key in ("rs1val", "rs2val") if key in fields}
    for key in explicit:
        value = fields[key]
        for item in value if isinstance(value, list) else [value]:
            unsigned(item, 32, key)
    # Known instructions may have no projection inputs; leave missing operands
    # for the compiler to reject rather than guessing an address as zero.
    variant = vector_variant(name)
    cores = selected_cores(name, fields, active, revision) if variant else sorted(active)
    if variant:
        if not cores or len(cores) > 4 or any(type(c) is not int or not 0 <= c < 16 for c in cores) or len(set(cores)) != len(cores) or len({c // 4 for c in cores}) != 1:
            if cores:  # raw zero mask can be retained for negative stimulus
                raise ISAError("INVALID_CORE_IDS", "VNICE needs unique cores within one four-core group")
        fields.setdefault('core_ids', cores)
        # Dynamic transfer declarations must preserve the operation's shape/type.
        # Raw operand pairs intentionally bypass these semantic checks.
        if not {"rs1val", "rs2val"} <= explicit and "src" in fields and "dst" in fields and name.startswith(("tld_", "ttld_", "tst_", "gtld_", "gttld_", "gtst_", "noc_")):
            srcs, dsts = fields["src"], fields["dst"]
            srcs = srcs if isinstance(srcs, list) else [srcs] * len(cores)
            dsts = dsts if isinstance(dsts, list) else [dsts] * len(cores)
            if len(srcs) != len(cores) or len(dsts) != len(cores):
                raise ISAError("VECTOR_REFERENCE_LENGTH", "src/dst references must match selected cores")
            for src, dst in zip(srcs, dsts):
                sc, dc = flow._context_for(src, action["source"]["line"]), flow._context_for(dst, action["source"]["line"])
                if name.startswith("noc_"):
                    source_endpoint = sc["placement"].get("place", {})
                    destination_endpoint = dc["placement"].get("place", {})
                    for key in ("chip", "die", "cluster"):
                        default = flow.profile.get(key + '_id', 0)
                        if source_endpoint.get(key, default) != destination_endpoint.get(key, default):
                            raise ISAError("UNSUPPORTED_NOC_ROUTE", "Word v1.4 NoC supports transfers within one die/cluster only")
                shape = sc["shape"]
                expected = [shape[0], shape[2], shape[1]] if name.startswith(("ttld_", "gttld_")) else shape
                if dc["shape"] != expected or sc["dtype"] != dc["dtype"]:
                    raise ISAError("CFG_BIND_MISMATCH", f"{name} source/destination shape or dtype mismatch")
    generated = False
    for operand, descriptor in (("rs1val", spec.rs1), ("rs2val", spec.rs2)):
        if operand in explicit or descriptor == "-":
            continue
        kind, role = descriptor.split(':')
        ref = _reference(fields, role, revision)
        if name == "group_mask_drv_xn" and ref is None and "core_ids" in fields:
            ref = sum(1 << unsigned(c, 4, "core_id") for c in fields["core_ids"])
        if ref is None:
            continue
        refs = ref if isinstance(ref, list) else [ref] * len(cores)
        if len(refs) != len(cores):
            raise ISAError("VECTOR_REFERENCE_LENGTH", f"{role} must have one reference per selected core")
        values = [_operand(flow, action, descriptor, r, c, state) for r, c in zip(refs, cores)]
        if not values:
            continue
        if variant and (operand == "rs2val" or variant == "vn11"):
            value = [0, 0, 0, 0]
            for core, item in zip(cores, values):
                value[core % 4] = item
        else:
            if len(set(values)) != 1:
                raise ISAError("VN01_SHARED_RS1", f"{name} shared operand differs between selected cores")
            value = values[0]
        fields[operand] = value
        generated = True
    if variant and generated:
        mask = (cores[0] // 4 << 4) | sum(1 << (c % 4) for c in cores)
        mask_key = "rs1val" if spec.flags[1] == "1" else "rs2val"
        if mask_key not in explicit and mask_key in fields:
            if isinstance(fields[mask_key], list):
                fields[mask_key][0] |= mask << 26
            else:
                fields[mask_key] |= mask << 26
        fields.update(core_ids=cores, vector_operands=True, vn_group_id=cores[0] // 4,
                      vn_core_mask=mask & 15, vn_6b_grp_mask=mask, vn_operand_format=variant)
    fields['explicit_operands'] = True
    fields["vector_operand_cores"] = {str(c): {
        k: (fields[k][c % 4] if isinstance(fields.get(k), list) else fields.get(k, 0))
        for k in ("rs1val", "rs2val")} for c in cores}
    if name.startswith("noc_"):
        flags = fields["src_dst_flag"]
        flags = flags if isinstance(flags, list) else [flags] * len(cores)
        fields.update(noc_src_dst_flag=flags,
                      noc_dst_core_ids=[c for c, f in zip(cores, flags) if f == 0],
                      noc_src_core_ids=[c for c, f in zip(cores, flags) if f == 1])
    if generated:
        fields["operand_encoding"] = f"{revision}:{spec.rs1}:{spec.rs2}"
    for requirements in fields.get("address_requirements", {}).values():
        for required in requirements.values():
            observed = required["pre_observed"]
            required["status"] = ('source_contract_pending' if required.get('pre_contract') else
                                  'external_or_missing' if observed is None else
                                  'match' if all(observed.get(k) == required[k] for k in ("die_cluster", "mem_core") if k in required) else "mismatch")
    # Per-core pre shadow records the enabled fields only. Repeated drivers
    # retain these values; a partial pre write preserves its other fields.
    if "pre" in name:
        module = "mpu" if name.startswith("gemm") else "glsu" if name.startswith("die_cluster") else "vpu"
        updates = {}
        for core in cores:
            values = {}
            for key, descriptor in (("rs1val", spec.rs1), ("rs2val", spec.rs2)):
                if descriptor == "-" or key not in fields:
                    continue
                value = fields[key]
                value = value[core % 4] if isinstance(value, list) else value
                kind, role = descriptor.split(':')
                if kind == 'L':
                    # The pre register stores an address, not lane-0 group mask
                    # or reserved bits. Keep the original operand untouched.
                    value &= (1 << 18) - 1
                if kind in ("P1", "P2"):
                    role = "rs1" if kind == 'P1' else "rs2"
                    value = {'die_cluster': value & 15,
                             **({"mem_core": (value >> 8) & 127} if kind == 'P1' and variant else {})}
                state[(core, module, role)] = value
                values[role] = value
            updates[str(core)] = values
        fields['_pre_state_written'] = updates
    elif name.startswith(("gemm", "vv", "vs", "mv_m")):
        module = "mpu" if name.startswith("gemm") else "vpu"
        fields["_pre_state_observed"] = {str(core): {role: value for (c, m, role), value in state.items()
                                                     if c == core and m == module}
                                         for core in cores}


def instruction_fields(action, core=None, *, allow_operand_source_conflict=False, isa_revision=None):
    """Return logical fields, without assuming any CMD_SCH wire ordering."""
    name, fields = action["op"], action["fields"]
    spec = instruction(name, isa_revision)
    if spec.opcode_issue:
        raise ISAError("ISA_OPCODE_CONFLICT", spec.opcode_issue)
    if spec.issue and not allow_operand_source_conflict:
        raise ISAError("ISA_SOURCE_CONFLICT", f"{name}: {spec.issue}; explicit cmddata cannot resolve a spec conflict")
    result = {"funct7": spec.funct7, "instr_flag": int(vector_variant(name) is not None),
              **dict(zip(("xd", "xs1", "xs2"), map(int, spec.flags)))}
    for key, enable in (("rs1val", spec.flags[1]), ("rs2val", spec.flags[2])):
        if key not in fields and enable == "1":
            raise ISAError("UNRESOLVED_OPERAND", f"{name} requires {key}; supply raw operand or supported role/view binding")
        value = fields.get(key, 0)
        if isinstance(value, list):
            if core is None or len(value) != 4:
                raise ISAError("CORE_REQUIRED", "four-lane operand requires selecting the destination core")
            value = value[core % 4]
        result[key] = unsigned(value, 32, f"{name} {key}")
    for key in ("funct7", "xd", "xs1", "xs2", "instr_flag"):
        if key in fields and fields[key] != result[key]:
            raise ISAError("ISA_FIELD_CONFLICT", f"{name} {key} conflicts with PDF encoding")
    return result
