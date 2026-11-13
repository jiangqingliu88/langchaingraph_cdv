"""Export small, human-checkable golden payloads for tensor_gen review."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .core import generate_tensor
from .formats import byte_hex, memh


TOOL_ROOT = Path(__file__).resolve().parent
OUT = TOOL_ROOT / "artifacts" / "tensor_gen_golden"


def numeric(name, dtype, values, shape=None, layout=None, **extra):
    return {
        "name": name,
        "dtype": dtype,
        "shape": shape or [1, 1, len(values)],
        "generation": {"mode": "numeric", "pattern": {"kind": "explicit", "values": values}, **extra},
        **({"layout": layout} if layout else {}),
    }


def raw(name, dtype, values, shape=None, layout=None):
    return {
        "name": name,
        "dtype": dtype,
        "shape": shape or [1, 1, len(values)],
        "generation": {"mode": "raw_bits", "values": values},
        **({"layout": layout} if layout else {}),
    }


CASES = [
    numeric("int4_low_nibble", "int4", [-8, -1, 0, 7], layout={"int4_nibble_order": "low_index_low_nibble"}),
    numeric("int4_high_nibble", "int4", [-8, -1, 0, 7], layout={"int4_nibble_order": "low_index_high_nibble"}),
    raw("int4_odd_tail", "int4", ["0x1", "0x2", "0x3"], shape=[1, 1, 3]),
    numeric("int8_boundaries", "int8", [-128, -1, 0, 1, 127]),
    numeric("int16_boundaries", "int16", [-32768, -1, 0, 1, 32767]),
    numeric("int32_boundaries", "int32", [-2147483648, -1, 0, 1, 2147483647]),
    numeric("fp16_values", "fp16", [0.0, -0.0, 1.0, -2.0]),
    numeric("bf16_values", "bf16", [0.0, -0.0, 1.0, -2.0]),
    numeric("fp32_values", "fp32", [0.0, -0.0, 1.0, -2.0]),
    raw("bf16_raw_special", "bf16", ["0x0000", "0x8000", "0x7f80", "0xff80", "0x7fff", "0x0001"]),
    numeric("bf16_special_injection", "bf16", [1.0] * 8),
    numeric("int8_two_rows", "int8", [1, 2, 3, 4, 5, 6], shape=[1, 2, 3]),
    numeric("int4_two_rows", "int4", [1, 2, 3, 4, 5, 6], shape=[1, 2, 3]),
    numeric("int16_stride_view", "int16", list(range(32)), shape=[1, 2, 16], layout={"stride_dim1": 2, "stride_dim2": 4}),
]

# Replace the special injection case separately so the JSON remains obvious.
CASES[10] = numeric(
    "bf16_special_injection", "bf16", [1.0] * 8,
    denormal_policy="allow",
    special_values=[
        {"kind": "-0", "positions": [0]},
        {"kind": "+inf", "positions": [1]},
        {"kind": "nan", "positions": [2]},
        {"kind": "denormal", "positions": [3]},
    ],
)


# Source tensors for Top-level TMU alignment tests. No software exponent
# extraction: each element retains its complete FP encoding at the DUT input.
def tmu_source(name, dtype, transpose=False):
    values = []
    for row in range(32):
        for col in range(32):
            # Different maxima per reduction group; dyadic values encode exactly
            # in both FP16 and BF16. Signs do not obscure exponent comparisons.
            exponent = ((row + 2 * col) % 9) - 4 + row // 16 + col // 16
            fraction = 1 + ((3 * row + col) % 8) / 8
            sign = -1 if (row + col) % 3 == 0 else 1
            values.append(sign * fraction * 2 ** exponent)
    return {
        "spec": numeric(name, dtype, values, shape=[1, 32, 32]),
        "intent": {
            "input_representation": "original fp",
            "operation": "transpose_align" if transpose else "align",
            "trans_en": transpose,
            "align_en": True,
            "reduction_axis_in_source": "dim0" if transpose else "dim1",
            "exponent_owner": "dut_tmu",
            "output_representation": "dut internal mantissa and cimc exp",
            "note": "Test intent only; instruction/address binding is external. No shared-exponent input file or software TMU oracle is generated.",
        },
    }


TMU_SOURCES = [
    tmu_source("tmu_bf16_align_source", "bf16"),
    tmu_source("tmu_fp16_align_source", "fp16"),
    tmu_source("tmu_bf16_transpose_align_source", "bf16", transpose=True),
]


def main(argv=()):
    parser = argparse.ArgumentParser(
        description="Export 14 ordinary and 3 TMU original-FP review cases.",
        epilog="Output: artifacts/tensor_gen_golden relative to the project root. "
               "Existing sample files are replaced directly; this is not the production CLI publisher.")
    parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    case_manifest = {"schema": "tensor_golden_v1", "generator": "isa_ir_tools.expot_golden", "tensors": []}
    intents = {item["spec"]["name"]: item["intent"] for item in TMU_SOURCES}
    for spec in CASES + [item["spec"] for item in TMU_SOURCES]:
        result = generate_tensor(spec, case_seed=20261015)
        folder = OUT / spec["name"]
        folder.mkdir(parents=True, exist_ok=True)
        case_spec = {"schema_version": "tensor_spec_v1", "case_seed": 20261015, "tensors": [spec]}
        (folder / "spec.json").write_text(json.dumps(case_spec, indent=2) + "\n", encoding="utf-8", newline="\n")
        payload = result["payload"]
        (folder / "data.bin").write_bytes(payload)
        (folder / "data.hex").write_text(byte_hex(payload), encoding="ascii", newline="\n")
        (folder / "data.memh").write_text(memh(payload), encoding="ascii", newline="\n")
        entry = {
            "name": spec["name"], "dtype": result["dtype"], "shape": result["shape"],
            "layout": result["layout"], "codec": result["codec"],
            "bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
            "files": {"bin": "data.bin", "hex": "data.hex", "memh": "data.memh", "spec": "spec.json"},
        }
        if spec["name"] in intents:
            entry["verification_intent"] = intents[spec["name"]]
        (folder / "manifest.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8", newline="\n")
        case_manifest["tensors"].append(entry)
    (OUT / "README.md").write_text(
        "# Tensor Generator Golden Data\n\n"
        "每个子目录包含 `spec.json`、`data.bin`、`data.hex`、`data.memh` 和 `manifest.json`。\n"
        "`data.hex` 每行16字节；`data.memh` 每行一个32字节 atom。两者都可还原为 `data.bin`。\n\n"
        "**INT4** `low_index_low_nibble` 预期前两字节 `f8 70`；`low_index_high_nibble` 预期 `8f 07`。\n"
        "**BF16** `1.0` 为小端字节 `80 3f`；canonical NaN 为 `ff 7f`。\n\n"
        "**TMU Top source cases:** `tmu_bf16_align_source`, `tmu_fp16_align_source`, `tmu_bf16_transpose_align_source`。\n"
        "Each case contains 32x32 original FP elements (2048 bytes), mixed signs and varied exponents.\n"
        "The DUT TMU extracts exponents and aligns mantissas. No shared exponent input is required.\n\n"
        "`verification_intent` in each manifest describes the intended operation; instruction and address binding remain external.\n"
        "These files validate source encoding, not the numerical correctness of DUT TMU output.\n",
        encoding="utf-8", newline="\n")
    (OUT / "manifest.json").write_text(json.dumps(case_manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"Generated {len(CASES)} ordinary + {len(TMU_SOURCES)} TMU top-source golden cases in {OUT}")


if __name__ == "__main__":
    main(None)
