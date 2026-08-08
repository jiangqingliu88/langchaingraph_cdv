#!/usr/bin/env python3
import os
import json
import struct

def generate_hex_file(filepath, values, dtype):
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    content = ["00000000"] # 模拟地址行
    
    if dtype.upper() == 'FP32':
        for v in values: content.append(struct.pack('>f', v).hex().upper())
    elif dtype.upper() == 'INT16':
        for v in values: content.append(f"{v & 0xFFFF:04X}")
    else:
        return
    with open(filepath, 'w') as f: f.write("\n".join(content))
    print(f"  -> [OK] Generated: {filepath}")

# === 路径规划 ===
BASE_DIR = os.getcwd()
GOLDEN_ROOT = os.path.join(BASE_DIR, "test_case", "in_out_hex_txt", "data_out_hex")
OUTPUT_DIR = os.path.join(BASE_DIR, "test_case_output", "20260718_123456", "in_out_hex", "data_out_hex")
os.makedirs(GOLDEN_ROOT, exist_ok=True); os.makedirs(OUTPUT_DIR, exist_ok=True)

# === 生成完全匹配您截图格式的 JSON ===
tensors = [
    {
        "name": "out_0",
        "address": "0x00004000",
        "dtypename": "FP32",
        "dimension": {"dim2": 1, "dim1": 4, "dim0": 16},
        "stride": {"stride2": 8, "stride1": 2}
    },
    {
        "name": "wt_int_0",
        "address": "0x0000c000",
        "dtypename": "INT16",
        "dimension": {"dim2": 1, "dim1": 32, "dim0": 16},
        "stride": {"stride2": 32, "stride1": 1}
    }
]
json_path = os.path.join(GOLDEN_ROOT, "output_tensor.json")
with open(json_path, "w") as f: json.dump(tensors, f, indent=4)
print(f"  -> [OK] Generated: {json_path}")

# === 生成测试 Hex 数据 ===
# Golden: [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 4.0] (带有Padding)
# Output: [1.0, 2.0, 3.0001, 4.0] (Compact, 且含有微小误差)
generate_hex_file(os.path.join(GOLDEN_ROOT, "golden_out_0.hex"), [1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 0.0, 4.0], "FP32")
generate_hex_file(os.path.join(OUTPUT_DIR, "dv_out_0.hex"), [1.0, 2.0, 3.0001, 4.0], "FP32")

# Golden Int: [10, 20, 30, 40, 50], Output Int: [10, 20, 30, 40, 50]
generate_hex_file(os.path.join(GOLDEN_ROOT, "golden_wt_int_0.hex"), [10, 20, 30, 40, 50], "INT16")
generate_hex_file(os.path.join(OUTPUT_DIR, "dv_wt_int_0.hex"), [10, 20, 30, 40, 50], "INT16")

print("\n✅ 测试环境准备完毕！")