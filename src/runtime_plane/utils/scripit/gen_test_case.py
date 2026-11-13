#!/usr/bin/env python3
import os
import json
import struct
import numpy as np  # 需要安装: pip install numpy

def float_to_hex_fp32(val):
    """将 Python float 转为 FP32 的大端 Hex 字符串"""
    return struct.pack('>f', val).hex().upper()

def float_to_hex_fp16(val):
    """将 Python float 转为 FP16 的大端 Hex 字符串"""
    return struct.pack('>e', val).hex().upper()

def generate_hex_file(filepath, data_list, dtype):
    """根据数据类型生成 .hex 文件"""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    lines = ["00000000"]  # 模拟脚本需要的地址行
    
    if dtype.upper() == 'FP32':
        for v in data_list:
            lines.append(float_to_hex_fp32(v))
    elif dtype.upper() == 'FP16':
        for v in data_list:
            lines.append(float_to_hex_fp16(v))
    elif dtype.upper() == 'INT16':
        for v in data_list:
            # 转为补码 16位
            lines.append(f"{v & 0xFFFF:04X}")
    else:
        raise ValueError(f"不支持的数据类型: {dtype}")

    with open(filepath, 'w') as f:
        f.write("\n".join(lines))
    print(f"  -> 已生成数据文件: {filepath}")

# ==========================================
# 1. 配置定义：这里模拟您底层的 C 算子 vv_v add
# ==========================================

class VV_V_Add_TestGen:
    def __init__(self, case_name, shape, dtype='FP32', input_seed=42):
        self.case_name = case_name
        self.dtype = dtype
        self.shape = shape  # 例如 [16, 1, 4] (对应 dim0, dim1, dim2)
        self.total_len = shape[0] * shape[1] * shape[2]
        self.seed = input_seed
        np.random.seed(self.seed)

    def generate_files(self, output_dir):
        # 构造路径
        dir_path = os.path.join(output_dir, self.case_name, "in_out_hex_txt", "data_out_hex")
        os.makedirs(dir_path, exist_ok=True)

        # ================================
        # 步骤 1: 生成输入数据
        # ================================
        # 模拟从 HW 读入的源数据 input0 和 input1
        # 这里用随机浮点数模拟
        input0 = np.random.uniform(-10.0, 10.0, self.total_len).astype(np.float32)
        input1 = np.random.uniform(-10.0, 10.0, self.total_len).astype(np.float32)

        generate_hex_file(os.path.join(dir_path, "input0.hex"), input0, self.dtype)
        generate_hex_file(os.path.join(dir_path, "input1.hex"), input1, self.dtype)

        # ================================
        # 步骤 2: 生成 Golden 输出数据 (C 级计算)
        # ================================
        # 模拟底层算子 vv_v add 的计算逻辑：
        # golden_out = input0 + input1
        golden_out = input0 + input1
        generate_hex_file(os.path.join(dir_path, "golden_out_0.hex"), golden_out, self.dtype)

        # ================================
        # 步骤 3: 生成 JSON 配置文件
        # ================================
        json_payload = [
            {
                "name": "out_0",
                "address": "0x00004000",
                "dtypename": self.dtype,
                "dimension": {
                    "dim2": self.shape[2],
                    "dim1": self.shape[1],
                    "dim0": self.shape[0]
                },
                "stride": {
                    "stride2": 8,   # 仅作示例，非实际值
                    "stride1": 2    # 仅作示例，非实际值
                }
            },
            {
                "name": "input0",
                "address": "0x00000000",
                "dtypename": self.dtype,
                "dimension": {
                    "dim2": self.shape[2],
                    "dim1": self.shape[1],
                    "dim0": self.shape[0]
                },
                "stride": {"stride2": 8, "stride1": 2}
            },
            {
                "name": "input1",
                "address": "0x00002000",
                "dtypename": self.dtype,
                "dimension": {
                    "dim2": self.shape[2],
                    "dim1": self.shape[1],
                    "dim0": self.shape[0]
                },
                "stride": {"stride2": 8, "stride1": 2}
            }
        ]

        json_path = os.path.join(dir_path, "output_tensor.json")
        with open(json_path, 'w') as f:
            json.dump(json_payload, f, indent=4)
        print(f"  -> 已生成配置 JSON: {json_path}")

# ==========================================
# 2. 执行生成
# ==========================================

if __name__ == "__main__":
    # 定义测试用例参数
    CASE_NAME = "test_vv_v_add"
    TENSOR_SHAPE = [16, 4, 1]  # dim0=16, dim1=4, dim2=1 (对应 64 个元素)
    DATA_TYPE = "FP32"
    OUTPUT_BASE_DIR = os.path.join(os.getcwd(), "generated_cases")

    # 执行生成器
    generator = VV_V_Add_TestGen(CASE_NAME, TENSOR_SHAPE, dtype=DATA_TYPE)
    generator.generate_files(OUTPUT_BASE_DIR)

    print(f"\n✅ 用例生成完毕！目录结构: {OUTPUT_BASE_DIR}/{CASE_NAME}")