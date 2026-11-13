"""Word v1.4 (2026-10-22) 4.1.3 and 4.2.2~4.6.2 row packing.

Each write contains 16 address bits, 16 independent rs1 payload bits and
32 rs2 payload bits. Tables here deliberately do not use the older XLSX.
"""
from __future__ import annotations

# name: (row, operand, lsb, width). Group is encoded separately in rs1[31:24].
TLD_FIELDS = {
    "cfg_num_dim0": (0, "rs2", 0, 19),
    "cfg_size_dim1": (0, "rs2", 19, 13),
    "cfg_size_dim2": (0, "rs1", 0, 13),
    "cfg_stride_dim2_in": (1, "rs2", 0, 25),
    "cfg_mx": (1, "rs2", 25, 1),
    "cfg_type": (1, "rs2", 26, 1),
    "cfg_mantissa": (1, "rs2", 27, 1),
    "cfg_wd": (1, "rs2", 28, 3),
    "cfg_exp_mode": (1, "rs2", 31, 1),
    "cfg_stride_dim1_in": (1, "rs1", 0, 13),
    "cfg_stride_dim2_out": (2, "rs2", 0, 25),
    "cfg_stride_dim1_out": (2, "rs1", 0, 13),
    "cfg_gat_base_addr": (3, "rs2", 0, 32),
    "cfg_gat_base_addr_id": (3, "rs1", 0, 4),
    "cfg_num_dim0_index": (4, "rs2", 0, 19),
}
NOC_FIELDS = {
    "cfg_num_dim0": (0, "rs2", 0, 19),
    "cfg_size_dim1": (0, "rs2", 19, 13),
    "cfg_size_dim2": (0, "rs1", 0, 13),
    "cfg_stride_dim2": (1, "rs2", 0, 25),
    "cfg_mx": (1, "rs2", 25, 1),
    "cfg_type": (1, "rs2", 26, 1),
    "cfg_mantissa": (1, "rs2", 27, 1),
    "cfg_stride_dim1": (1, "rs1", 0, 13),
    "cfg_wd": (1, "rs1", 13, 3),
}
TMU_FIELDS = {
    "cfg_num_dim0": (0, "rs2", 0, 19),
    "cfg_size_dim1": (0, "rs2", 19, 13),
    "cfg_size_dim2": (0, "rs1", 0, 13),
    "cfg_stride_dim2_in": (1, "rs2", 0, 25),
    "cfg_stride_dim1_in": (1, "rs1", 0, 13),
    "cfg_stride_dim2_out": (2, "rs2", 0, 25),
    "cfg_mx": (2, "rs2", 25, 1),
    "cfg_type": (2, "rs2", 26, 1),
    "cfg_mantissa": (2, "rs2", 27, 1),
    "cfg_wd": (2, "rs2", 28, 3),
    "cfg_stride_dim1_out": (2, "rs1", 0, 13),
    "cfg_num_dim0_out_bcast": (3, "rs2", 0, 19),
}
MPU_FIELDS = {
    "cfg_num_dim0_in": (0, "rs2", 0, 19),
    "cfg_mx_in": (0, "rs2", 19, 1),
    "cfg_type_in": (0, "rs2", 20, 1),
    "cfg_mantissa_in": (0, "rs2", 21, 1),
    "cfg_wd_in": (0, "rs2", 22, 3),
    "cfg_mx_wt": (0, "rs2", 25, 1),
    "cfg_type_wt": (0, "rs2", 26, 1),
    "cfg_mantissa_wt": (0, "rs2", 27, 1),
    "cfg_wd_wt": (0, "rs2", 28, 3),
    "cfg_satu": (0, "rs2", 31, 1),
    "cfg_stride_dim1_in": (0, "rs1", 0, 13),
    "cfg_denor_iso": (0, "rs1", 13, 1),
    "cfg_num_dim0_out": (1, "rs2", 0, 19),
    "cfg_mx_out": (1, "rs2", 19, 1),
    "cfg_type_out": (1, "rs2", 20, 1),
    "cfg_mantissa_out": (1, "rs2", 21, 1),
    "cfg_wd_out": (1, "rs2", 22, 3),
    "cfg_mx_dq": (1, "rs2", 25, 1),
    "cfg_type_dq": (1, "rs2", 26, 1),
    "cfg_mantissa_dq": (1, "rs2", 27, 1),
    "cfg_wd_dq": (1, "rs2", 28, 3),
    "cfg_act_fun": (1, "rs2", 31, 1),
    "cfg_size_dim1_in": (1, "rs1", 0, 13),
    "cfg_stride_dim1_out": (2, "rs2", 0, 13),
    "cfg_mx_orig": (2, "rs2", 13, 1),
    "cfg_type_orig": (2, "rs2", 14, 1),
    "cfg_mantissa_orig": (2, "rs2", 15, 1),
    "cfg_wd_orig": (2, "rs2", 16, 3),
    "cfg_stride_dim1_orig": (2, "rs1", 0, 13),
    # cfg_mx block size is struck through in the PDF and is not a field.
}
VPU_FIELDS = {
    "cfg_num_dim0": (0, "rs2", 0, 19),
    "cfg_mx_out": (0, "rs2", 19, 1),
    "cfg_type_out": (0, "rs2", 20, 1),
    "cfg_mantissa_out": (0, "rs2", 21, 1),
    "cfg_wd_out": (0, "rs2", 22, 3),
    "cfg_op_mode": (0, "rs2", 25, 6),
    "cfg_satu": (0, "rs2", 31, 1),
    "cfg_mx_in1": (0, "rs1", 0, 1),
    "cfg_type_in1": (0, "rs1", 1, 1),
    "cfg_mantissa_in1": (0, "rs1", 2, 1),
    "cfg_wd_in1": (0, "rs1", 3, 3),
    "cfg_mx_in2": (0, "rs1", 6, 1),
    "cfg_type_in2": (0, "rs1", 7, 1),
    "cfg_mantissa_in2": (0, "rs1", 8, 1),
    "cfg_wd_in2": (0, "rs1", 9, 3),
    "cfg_rm": (0, "rs1", 12, 3),
    "cfg_denor_iso": (0, "rs1", 15, 1),
    "cfg_size_dim1": (1, "rs2", 0, 13),
    "cfg_stride_dim1_in1": (1, "rs2", 13, 13),
    "cfg_mx_in3": (1, "rs2", 26, 1),
    "cfg_type_in3": (1, "rs2", 27, 1),
    "cfg_mantissa_in3": (1, "rs2", 28, 1),
    "cfg_wd_in3": (1, "rs2", 29, 3),
    "cfg_stride_dim1_out": (1, "rs1", 0, 13),
    "cfg_mv_m_type": (1, "rs1", 13, 1),
    "cfg_mx_an": (2, "rs2", 0, 1),
    "cfg_type_an": (2, "rs2", 1, 1),
    "cfg_mantissa_an": (2, "rs2", 2, 1),
    "cfg_wd_an": (2, "rs2", 3, 3),
    "cfg_iter_num": (2, "rs2", 6, 3),
    "cfg_poly_an_buf16_0": (3, "rs2", 0, 16),
    "cfg_poly_an_buf16_1": (3, "rs2", 16, 16),
    "cfg_poly_an_buf16_2": (3, "rs1", 0, 16),
    "cfg_poly_an_buf16_3": (4, "rs2", 0, 16),
    "cfg_poly_an_buf16_4": (4, "rs2", 16, 16),
    "cfg_poly_an_buf16_5": (4, "rs1", 0, 16),
    "cfg_poly_an_buf16_6": (5, "rs2", 0, 16),
    "cfg_poly_an_buf16_7": (5, "rs2", 16, 16),
    "cfg_poly_an_buf16_8": (5, "rs1", 0, 16),
    "cfg_poly_an_buf16_9": (6, "rs2", 0, 16),
    "cfg_poly_an_buf16_10": (6, "rs2", 16, 16),
    "cfg_poly_an_buf16_11": (6, "rs1", 0, 16),
}
MODULES = {
    "glsu": (0, TLD_FIELDS), "tld": (0, TLD_FIELDS),
    "gather": (0, TLD_FIELDS),
    "tst": (1, {k: v for k, v in TLD_FIELDS.items() if v[0] <= 2}),
    "tmu": (2, TMU_FIELDS), "mpu": (3, MPU_FIELDS),
    "vpu": (4, VPU_FIELDS),
    "noc": (5, NOC_FIELDS),
}
# PDF 2.7.3: (mx, type, mantissa, log2(element bits)).
DTYPE_CFG = {
    "int8": (0, 0, 0, 3),
    "int16": (0, 0, 0, 4), "int32": (0, 0, 0, 5),
    "fp8_e5m2": (0, 1, 0, 3), "fp8_e4m3": (0, 1, 0, 3),
    "fp4_e2m1": (0, 1, 0, 2), "fp4_e1m2": (0, 1, 1, 2),
    "fp16": (0, 1, 0, 4), "bf16": (0, 1, 1, 4),
    "fp32": (0, 1, 0, 5),
}


class CfgError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def module_spec(module):
    name = str(module).lower().removesuffix(".cfg")
    if name not in MODULES:
        raise CfgError("UNSUPPORTED_CFG_MODULE", str(module))
    return MODULES[name]


def tensor_fields(module, src, dst):
    """Project ordinary tensor layout; contexts are normalized by ir_flow.

    Transfer-mode controls below are flow defaults, not reset-value assumptions.
    Gather base/index are always supplied explicitly, never guessed from data.
    """
    group, _ = module_spec(module)
    if group in (2, 3, 4):
        raise CfgError("CFG_BIND_UNSUPPORTED", f"{module} requires explicit with fields; operation-specific tensor role binding is not implemented")
    if src["dtype"] != dst["dtype"]:
        raise CfgError("CFG_BIND_MISMATCH", "transfer src/dst dtype must match")
    if src["dtype"] not in DTYPE_CFG:
        raise CfgError("UNSUPPORTED_CFG_DTYPE", src["dtype"])
    d2, d1, d0 = src["shape"]
    values = dict(zip(("cfg_mx", "cfg_type", "cfg_mantissa", "cfg_wd"), DTYPE_CFG[src["dtype"]]))
    values.update(cfg_num_dim0=d0, cfg_size_dim1=d1, cfg_size_dim2=d2)
    sl, dl = src["layout"], dst["layout"]
    if group == 5:
        if src["shape"] != dst["shape"] or any(sl[k] != dl[k] for k in ("stride_dim1", "stride_dim2")):
            raise CfgError("CFG_BIND_MISMATCH", "one NoC cfg write has one layout; configure each core separately for different layouts")
        values.update(cfg_stride_dim1=sl["stride_dim1"], cfg_stride_dim2=sl["stride_dim2"])
        controls = {}
    else:
        values.update(cfg_stride_dim1_in=sl["stride_dim1"], cfg_stride_dim2_in=sl["stride_dim2"],
                      cfg_stride_dim1_out=dl["stride_dim1"], cfg_stride_dim2_out=dl["stride_dim2"])
        controls = {"cfg_exp_mode": 0}
    return values, controls


def bind_cfg_fields(module, contexts, operation=None):
    """Derive tensor-owned cfg fields; return values, flow controls, origins.

    Contexts are resolved from generated tensor metadata plus view layouts.
    Control fields for compute modules must be supplied via `with`. This
    projects registers, not the complete instruction/precision legality model.
    """
    group, _ = module_spec(module)
    values, origins = {}, {}
    def put(name, value, role, attribute):
        values[name] = value
        origins[name] = {"role": role, "ref": contexts[role]["ref"], "attribute": attribute}

    def precision(role, suffix=""):
        dtype = contexts[role]["dtype"]
        if dtype not in DTYPE_CFG:
            raise CfgError("UNSUPPORTED_CFG_DTYPE", dtype)
        for name, value in zip(("cfg_mx", "cfg_type", "cfg_mantissa", "cfg_wd"), DTYPE_CFG[dtype]):
            put(name + suffix, value, role, "dtype")

    def stride(role, axis, name):
        put(name, contexts[role]["layout"][axis], role, "layout." + axis)

    def dimension(role, axis, name):
        put(name, contexts[role]["shape"][axis], role, f"shape[{axis}]")

    def check_shape(role, expected):
        if contexts[role]["shape"] != list(expected):
            raise CfgError("CFG_BIND_MISMATCH", f"{role} shape {contexts[role]['shape']} must be {list(expected)}")

    def matrix(role):
        if contexts[role]["shape"][0] != 1:
            raise CfgError("CFG_BIND_MISMATCH", f"{role} has dim2 > 1; bind a dim2 slice for this module")

    roles = set(contexts)
    if group in (0, 1, 5):
        if roles not in ({"src", "dst"}, {"ref"}):
            raise CfgError("INVALID_CFG_BIND", "transfer bind requires src/dst or ref")
        sr, dr = ("ref", "ref") if roles == {"ref"} else ("src", "dst")
        if group in (0, 1):
            op = operation or ("tst" if group == 1 else "tld")
            if op not in (("tst",) if group == 1 else ("tld", "ttld")):
                raise CfgError("UNSUPPORTED_CFG_BIND_OPERATION", f"{module} operation={op}")
            d2, d1, d0 = contexts[sr]["shape"]
            expected = [d2, d0, d1] if op == "ttld" else [d2, d1, d0]
            if contexts[dr]["shape"] != expected:
                raise CfgError("CFG_BIND_MISMATCH", f"{op} destination shape must be {expected}")
            values, controls = tensor_fields(module, contexts[sr], contexts[dr])
            for name in values:
                role = dr if name.endswith("_out") else sr
                attribute = "dtype" if name in ("cfg_mx", "cfg_type", "cfg_mantissa", "cfg_wd") else "shape/layout"
                origins[name] = {"role": role, "ref": contexts[role]["ref"], "attribute": attribute}
            return values, controls, origins
        if group == 2:
            op = operation or "tmov"
            if op not in ("tmov", "ttmov", "bc", "vbc", "trans_vbc"):
                raise CfgError("UNSUPPORTED_CFG_BIND_OPERATION", f"TMU operation={op}")
            expected_roles = {"dst"} if op == "bc" else {"src", "dst"}
            if roles != expected_roles:
                raise CfgError("INVALID_CFG_BIND", f"TMU {op} requires {sorted(expected_roles)}")
            precision("dst")
            if "src" in contexts and contexts["src"]["dtype"] != contexts["dst"]["dtype"]:
                raise CfgError("CFG_BIND_MISMATCH", "TMU ordinary src/dst dtype must match")
            stride("dst", "stride_dim1", "cfg_stride_dim1_out")
            stride("dst", "stride_dim2", "cfg_stride_dim2_out")
            if op in ("tmov", "ttmov"):
                d2, d1, d0 = contexts["src"]["shape"]
                check_shape("dst", (d2, d1, d0) if op == "tmov" else (d2, d0, d1))
                for axis, name in enumerate(("cfg_size_dim2", "cfg_size_dim1", "cfg_num_dim0")):
                    dimension("src", axis, name)
                stride("src", "stride_dim1", "cfg_stride_dim1_in")
                stride("src", "stride_dim2", "cfg_stride_dim2_in")
            elif op == "bc":
                dimension("dst", 0, "cfg_size_dim2")
                dimension("dst", 1, "cfg_size_dim1")
                dimension("dst", 2, "cfg_num_dim0_out_bcast")
                # Ignored cfg_num_dim0 is deliberately left to with, not guessed.
            else:
                n = contexts["src"]["shape"][2]
                check_shape("src", (1, 1, n))
                dimension("src", 2, "cfg_num_dim0")
                dimension("dst", 0, "cfg_size_dim2")
                if op == "vbc":
                    if contexts["dst"]["shape"][2] != n:
                        raise CfgError("CFG_BIND_MISMATCH", "vbc output dim0 must equal input length")
                    dimension("dst", 1, "cfg_size_dim1")
                else:
                    if contexts["dst"]["shape"][1] != n:
                        raise CfgError("CFG_BIND_MISMATCH", "trans_vbc output dim1 must equal input length")
                    dimension("dst", 2, "cfg_num_dim0_out_bcast")
                    # cfg_size_dim1 is ignored by this primitive; supply in with.
            return values, {}, origins

        allowed = {"in", "wt", "out", "dq", "orig"} if group == 3 else {"in1", "in2", "in3", "out", "an"}
        if not roles or roles - allowed:
            raise CfgError("INVALID_CFG_BIND", f"{module} accepts roles {sorted(allowed)}")
        for role in sorted(roles):
            precision(role, "_" + role)
        if group == 3:
            for role in roles - {"wt"}:
                matrix(role)
            if "in" in contexts:
                dimension("in", 2, "cfg_num_dim0_in")
                dimension("in", 1, "cfg_size_dim1_in")
                stride("in", "stride_dim1", "cfg_stride_dim1_in")
            if "out" in contexts:
                dimension("out", 2, "cfg_num_dim0_out")
                stride("out", "stride_dim1", "cfg_stride_dim1_out")
                if "in" in contexts and contexts["in"]["shape"][1] != contexts["out"]["shape"][1]:
                    raise CfgError("CFG_BIND_MISMATCH", "GEMM input/output M must match")
            if "dq" in contexts:
                n = contexts["out"]["shape"][2] if "out" in contexts else contexts["dq"]["shape"][2]
                check_shape("dq", (1, 1, n))
            if "orig" in contexts:
                stride("orig", "stride_dim1", "cfg_stride_dim1_orig")
                if "out" in contexts:
                    check_shape("orig", contexts["out"]["shape"])
        else:
            # Input dim0 remains the cfg traversal length for reductions/topk too.
            # Output and secondary operand shapes depend on the selected primitive;
            # do not impose an elementwise-add shape rule on every VPU operation.
            if "in1" in contexts:
                matrix("in1")
                dimension("in1", 2, "cfg_num_dim0")
                dimension("in1", 1, "cfg_size_dim1")
                stride("in1", "stride_dim1", "cfg_stride_dim1_in1")
            if "out" in contexts:
                matrix("out")
                stride("out", "stride_dim1", "cfg_stride_dim1_out")
        return values, {}, origins


def pack_cfg(module, explicit, derived=None, controls=None):
    """Return complete rows only. Missing sibling fields are errors, not zeroes.

    No register shadow is shared across cores/masks. For a standalone explicit
    row the caller must provide every defined field in that row. Untouched rows
    are not emitted. Reserved bits are zero.
    """
    group, layout = module_spec(module)
    if not isinstance(explicit, dict):
        raise CfgError("INVALID_CFG_VALUE", "with must be an object")
    removed = set(explicit) & {"cfg_mcast_mode", "cfg_add"}
    if removed:
        raise CfgError("REMOVED_CFG_FIELD", ", ".join(sorted(removed)) + ": removed by Word v1.4; omit even when zero, use raw operands for deliberate illegal/reserved bits")
    unknown = set(explicit) - set(layout)
    if unknown:
        raise CfgError("UNKNOWN_CFG_FIELD", ", ".join(sorted(unknown)))
    values = dict(derived or {})
    for key, value in explicit.items():
        if key in values and (type(value) is not int or value != values[key]):
            raise CfgError("CFG_BIND_CONFLICT", f"{key}={value!r} conflicts with bound tensor value {values[key]}")
        values.update({key: value})
    values.update(explicit)
    if not values:
        raise CfgError("MISSING_CFG_FIELD", "with or bind is required")
    rows = sorted({layout[k][0] for k in values})
    packs = []
    for row in rows:
        names = [k for k, spec in layout.items() if spec[0] == row]
        missing = set(names) - set(values)
        if missing:
            raise CfgError("INCOMPLETE_CFG_ROW", f"group {group} row {row}: {', '.join(sorted(missing))}")
        rs1, rs2 = (group << 24) | (row << 16), 0
        for name in names:
            value = values[name]
            operand, lsb, width = layout[name]
            if type(value) is not int or not 0 <= value < (1 << width):
                raise CfgError("INVALID_CFG_VALUE", f"{name} must be an unsigned {width}-bit integer")
            if (name.startswith(("cfg_num_", "cfg_size_", "cfg_stride_"))
                    and name != "cfg_num_dim0_out_bcast") and value == 0:
                raise CfgError("INVALID_CFG_VALUE", f"{name} must be positive")
            if name.startswith("cfg_wd") and value not in (2, 3, 4, 5):
                raise CfgError("INVALID_CFG_VALUE", f"{name} must be 2, 3, 4 or 5 (PDF 2.7.3)")
            if name == "cfg_rm" and value != 5:
                raise CfgError("INVALID_CFG_VALUE", "cfg_rm currently supports only RNE (5)")
            if operand == "rs1":
                if lsb + width > 16:
                    raise CfgError("UNREPRESENTABLE_CFG_FIELD", f"{name}: PDF rs1[{lsb + width - 1}:{lsb}] overlaps cfg register address; clarification required")
                rs1 |= value << lsb
            else:
                rs2 |= value << lsb
        packs.append({"cfg_group": group, "cfg_row": row, "cfg_reg_addr": (group << 8) | row,
                      "rs1val": rs1, "rs2val": rs2, "fields": {k: values[k] for k in names}})
    return packs
