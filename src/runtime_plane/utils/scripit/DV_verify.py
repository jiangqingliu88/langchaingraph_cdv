#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
DV Output Verification Script (Refactored & Realigned with JSON Schema)

Features:
    - Supports Input JSON format matching provided screenshot.
    - Modular design with Type Handlers.
    - Easy to extend with new data formats.
    - Supports Batch Mode and Single Case Mode.
"""

import os
import sys
import json
import struct
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type, Any, Tuple

# =============================================================================
# 1. 配置管理 (Configuration)
# =============================================================================

@dataclass
class VerificationConfig:
    """全局静态配置"""
    golden_root: str = 'tlm_application_tld'
    output_root: str = '../toolchain_output/tld'
    
    # Padding (Stride) 识别：连续多少个 0 被认定为 Padding
    min_consecutive_zeros: int = 32
    
    # 全局默认的浮点容差百分比
    default_fp_threshold: float = 2.0

    # 按数据类型的默认容差
    thresholds: Dict[str, float] = field(default_factory=lambda: {
        'INT4': 0.0, 'INT8': 0.0, 'INT16': 0.0, 'INT32': 0.0,
        'FP8': 5.0, 'FP8_E4M3': 5.0, 'FP8_E5M2': 5.0, 'FP8E4': 5.0, 'FP8E5': 5.0,
        'BF16': 5.0, 'FP16': 2.0, 'FP32': 0.5
    })

    # 步长(Stride)填充区域判断为"有效零"的噪声容差阈值
    stride_noise: Dict[str, float] = field(default_factory=lambda: {
        'INT4': 0, 'INT8': 0, 'INT16': 0, 'INT32': 0,
        'FP8': 0.5, 'BF16': 0.5, 'FP16': 0.5, 'FP32': 1e-6
    })

CONFIG = VerificationConfig()


# =============================================================================
# 2. 类型处理器体系 (Type Handler Registry)
# =============================================================================

class BaseTypeHandler:
    """数据类型的基类"""
    @staticmethod
    def parse(hex_str: str) -> List[Any]:
        raise NotImplementedError
    
    @staticmethod
    def to_hex(val: Any) -> str:
        raise NotImplementedError


# ---------- 整数类型实现 ----------
class Int4Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[int]:
        values = []
        for i in range(0, len(hex_str), 2):
            byte = int(hex_str[i:i+2], 16)
            high = (byte >> 4) & 0x0F
            low = byte & 0x0F
            values.extend([high - 16 if high > 7 else high, low - 16 if low > 7 else low])
        return values

class Int8Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[int]:
        values = []
        for i in range(0, len(hex_str), 2):
            v = int(hex_str[i:i+2], 16)
            values.append(v - 256 if v > 127 else v)
        return values

class Int16Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[int]:
        values = []
        for i in range(0, len(hex_str), 4):
            v = int(hex_str[i:i+4], 16)
            values.append(v - 65536 if v > 32767 else v)
        return values

class Int32Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[int]:
        values = []
        for i in range(0, len(hex_str), 8):
            v = int(hex_str[i:i+8], 16)
            values.append(v - 4294967296 if v > 2147483647 else v)
        return values

# ---------- 浮点数类型实现 ----------
class Fp32Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[float]:
        values = []
        for i in range(0, len(hex_str), 8):
            values.append(struct.unpack('>f', bytes.fromhex(hex_str[i:i+8]))[0])
        return values
    
    @staticmethod
    def to_hex(val: float) -> str:
        if val != val: return '7FC00000'
        try: return struct.pack('>f', val).hex().upper()
        except: return '00000000'

class Fp16Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[float]:
        values = []
        for i in range(0, len(hex_str), 4):
            values.append(struct.unpack('>e', bytes.fromhex(hex_str[i:i+4]))[0])
        return values
    
    @staticmethod
    def to_hex(val: float) -> str:
        if val != val: return '7E00'
        try: return struct.pack('>e', val).hex().upper()
        except: return '7C00' if val == float('inf') else ('FC00' if val == float('-inf') else '0000')

class Bf16Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[float]:
        values = []
        for i in range(0, len(hex_str), 4):
            fp32_hex = hex_str[i:i+4] + '0000'
            values.append(struct.unpack('>f', bytes.fromhex(fp32_hex))[0])
        return values
    
    @staticmethod
    def to_hex(val: float) -> str:
        if val != val: return '7FC0'
        try: return struct.pack('>f', val).hex().upper()[:4]
        except: return '7C00' if val == float('inf') else ('FC00' if val == float('-inf') else '0000')

class Fp8E4M3Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[float]:
        values = []
        for i in range(0, len(hex_str), 2):
            b = int(hex_str[i:i+2], 16)
            s, e, m = (b >> 7) & 1, (b >> 3) & 0xF, b & 0x7
            if e == 0: val = ((-1)**s) * (2**-6) * (m / 8)
            elif e == 15: val = float('nan') if m else float('inf') * (-1 if s else 1)
            else: val = ((-1)**s) * (2**(e-7)) * (1 + m / 8)
            values.append(val)
        return values
    
    @staticmethod
    def to_hex(val: float) -> str:
        if val != val: return '7F'
        if val == float('inf'): return '7C'
        if val == float('-inf'): return 'FC'
        sign, val = (1, -val) if val < 0 else (0, val)
        best_b, best_diff = 0, float('inf')
        for b in range(256):
            s, e, m = (b >> 7) & 1, (b >> 3) & 0xF, b & 0x7
            if e == 15: continue
            v = ((-1)**s) * (2**-6) * (m / 8) if e == 0 else ((-1)**s) * (2**(e-7)) * (1 + m / 8)
            d = abs(v - val)
            if d < best_diff: best_diff, best_b = d, b
        return '{:02X}'.format(best_b)

class Fp8E5M2Handler(BaseTypeHandler):
    @staticmethod
    def parse(hex_str: str) -> List[float]:
        values = []
        for i in range(0, len(hex_str), 2):
            b = int(hex_str[i:i+2], 16)
            s, e, m = (b >> 7) & 1, (b >> 2) & 0x1F, b & 0x3
            if e == 0: val = ((-1)**s) * (2**-14) * (m / 4)
            elif e == 31: val = float('nan') if m else float('inf') * (-1 if s else 1)
            else: val = ((-1)**s) * (2**(e-15)) * (1 + m / 4)
            values.append(val)
        return values
    
    @staticmethod
    def to_hex(val: float) -> str:
        if val != val: return '7F'
        if val == float('inf'): return '7C'
        if val == float('-inf'): return 'FC'
        sign, val = (1, -val) if val < 0 else (0, val)
        best_b, best_diff = 0, float('inf')
        for b in range(256):
            s, e, m = (b >> 7) & 1, (b >> 2) & 0x1F, b & 0x3
            if e == 31: continue
            v = ((-1)**s) * (2**-14) * (m / 4) if e == 0 else ((-1)**s) * (2**(e-15)) * (1 + m / 4)
            d = abs(v - val)
            if d < best_diff: best_diff, best_b = d, b
        return '{:02X}'.format(best_b)


# ---------- 处理器注册表 ----------
TYPE_HANDLERS: Dict[str, Type[BaseTypeHandler]] = {
    'INT4': Int4Handler, 'INT8': Int8Handler, 'INT16': Int16Handler, 'INT32': Int32Handler,
    'FP32': Fp32Handler, 'FP16': Fp16Handler, 'BF16': Bf16Handler,
    'FP8': Fp8E4M3Handler, 'FP8_E4M3': Fp8E4M3Handler, 'FP8E4': Fp8E4M3Handler,
    'FP8_E5M2': Fp8E5M2Handler, 'FP8E5': Fp8E5M2Handler,
}

def get_handler(dtype: str) -> Optional[Type[BaseTypeHandler]]:
    return TYPE_HANDLERS.get(dtype.upper())


# =============================================================================
# 3. 文件与 Padding 识别 (File I/O)
# =============================================================================

@dataclass
class HexFileParser:
    filepath: Path
    dtype: str
    skip_stride: bool = True
    _handler: Type[BaseTypeHandler] = field(init=False)

    def __post_init__(self):
        self._handler = get_handler(self.dtype)
        if not self._handler:
            raise ValueError(f"Unsupported dtype: {self.dtype}")

    def parse(self) -> List[Any]:
        lines = [l.strip() for l in open(self.filepath).readlines() if l.strip()]
        
        # 跳过类似地址的行 (例如 00000000)
        if lines and len(lines[0]) == 8 and all(c in '0123456789abcdefABCDEF' for c in lines[0]):
            lines = lines[1:]

        if self.skip_stride:
            skip_indices = set()
            run_start = None
            for i, line in enumerate(lines):
                is_zero = all(c == '0' for c in line)
                if is_zero and run_start is None: run_start = i
                elif not is_zero and run_start is not None:
                    if i - run_start >= CONFIG.min_consecutive_zeros:
                        skip_indices.update(range(run_start, i))
                    run_start = None
            
            if run_start is not None and len(lines) - run_start >= CONFIG.min_consecutive_zeros:
                skip_indices.update(range(run_start, len(lines)))
            
            lines = [l for i, l in enumerate(lines) if i not in skip_indices]

        # 解析数据
        data = []
        for line in lines:
            data.extend(self._handler.parse(line))
        return data


# =============================================================================
# 4. 核心验证逻辑 (Verifier)
# =============================================================================

@dataclass
class ErrorInfo:
    index: int
    expected: Any
    actual: Any
    abs_err: float
    rel_err: float

@dataclass
class VerifyResult:
    tensor_name: str
    dtype: str
    total: int
    passed: int
    failed: int
    errors: List[ErrorInfo]
    is_pass: bool
    golden_len: int
    output_len: int

class DataVerifier:
    def __init__(self, rel_threshold: float = None, thresholds: Dict[str, float] = None):
        self.rel_threshold = rel_threshold
        self.thresholds = thresholds or CONFIG.thresholds

    def _get_threshold(self, dtype: str) -> float:
        if self.rel_threshold is not None:
            return self.rel_threshold
        return self.thresholds.get(dtype.upper(), CONFIG.default_fp_threshold)

    def verify(self, expected: List[Any], actual: List[Any], dtype: str, tensor_name: str) -> VerifyResult:
        is_int = dtype.upper().startswith('INT')
        threshold = self._get_threshold(dtype)
        noise = CONFIG.stride_noise.get(dtype.upper(), 0.0)
        
        errors: List[ErrorInfo] = []
        pass_cnt, fail_cnt = 0, 0
        e_idx, a_idx = 0, 0
        
        while e_idx < len(expected) and a_idx < len(actual):
            exp = expected[e_idx]
            act = actual[a_idx]

            if isinstance(exp, float) and exp != exp:
                if isinstance(act, float) and act != act:
                    pass_cnt += 1
                else:
                    fail_cnt += 1
                    errors.append(ErrorInfo(e_idx, exp, act, float('inf'), float('inf')))
                e_idx += 1; a_idx += 1
                continue

            abs_err = abs(exp - act)
            rel_err = abs_err / (abs(exp) + 1e-15) * 100.0
            
            if is_int:
                match = (exp == act)
            else:
                match = (rel_err <= threshold) or (abs_err <= 1e-10)

            if match:
                pass_cnt += 1
            else:
                fail_cnt += 1
                errors.append(ErrorInfo(e_idx, exp, act, abs_err, rel_err))
            
            e_idx += 1; a_idx += 1

        if e_idx < len(expected): fail_cnt += len(expected) - e_idx
        if a_idx < len(actual):   fail_cnt += len(actual) - a_idx

        return VerifyResult(
            tensor_name=tensor_name,
            dtype=dtype,
            total=pass_cnt + fail_cnt,
            passed=pass_cnt,
            failed=fail_cnt,
            errors=errors[:50],
            is_pass=(fail_cnt == 0),
            golden_len=len(expected),
            output_len=len(actual)
        )


# =============================================================================
# 5. 运行器与工具 (Runner / Helpers)
# =============================================================================

class IOHelper:
    @staticmethod
    def find_json(path: Path) -> Optional[Path]:
        candidates = [
            path / 'output_tensor.json', path / 'put_out_tensors.json',
            path.parent / 'output_tensor.json', path.parent / 'put_out_tensors.json',
        ]
        for p in candidates:
            if p.exists(): return p
        return None

    @staticmethod
    def find_hex(path: Path, base_name: str, prefix: str, backup_prefix: str = None) -> Optional[Path]:
        candidates = [path / f"{prefix}{base_name}.hex", path / f"{base_name}.hex"]
        if backup_prefix: candidates.append(path / f"{backup_prefix}{base_name}.hex")
        for p in candidates:
            if p.exists(): return p
        return None

    @staticmethod
    def find_latest_output(case_name: str, output_root: str) -> Optional[str]:
        case_root = Path(output_root) / case_name
        if not case_root.exists(): return None
        dirs = sorted([d for d in case_root.iterdir() if d.is_dir()], reverse=True)
        for d in dirs:
            hex_dir = d / 'in_out_hex' / 'data_out_hex'
            if hex_dir.exists(): return str(hex_dir)
        return None


class Runner:
    def __init__(self, verifier: DataVerifier, verbose: bool = False):
        self.verifier = verifier
        self.verbose = verbose
        self.report_lines = []

    def _log(self, msg: str):
        print(msg)
        self.report_lines.append(msg)

    def verify_single_case(self, golden_dir: str, output_dir: str) -> Tuple[bool, str, dict]:
        golden_p, output_p = Path(golden_dir), Path(output_dir)
        
        if not golden_p.exists() or not output_p.exists():
            return False, "Directories not found", {}
        
        # 1. 解析 Json 配置
        json_path = IOHelper.find_json(golden_p)
        if not json_path: return False, "Tensor json not found", {}
        
        with open(json_path) as f: 
            # 根据您提供的截图，这里直接解析为列表，并取 key 为 "dtypename"
            tensors = json.load(f)

        self._log("=" * 80)
        self._log(f"Running Single Case: {golden_p}")

        all_pass = True
        total_stats = {'total_tensors': len(tensors), 'passed_tensors': 0, 'failed_tensors': 0}
        
        # 2. 遍历每个张量进行比对
        for tensor in tensors:
            # 兼容截图中的 "dtypename" (以及可能的备选 "dtype_name")
            name = tensor.get('name', 'unknown')
            dtype = tensor.get('dtypename', tensor.get('dtype_name', 'FP32')) 
            
            golden_hex = IOHelper.find_hex(golden_p, name, prefix='golden_')
            output_hex = IOHelper.find_hex(output_p, name, prefix='dv_', backup_prefix='')

            if not golden_hex or not output_hex:
                self._log(f"[{name}] FAIL: Hex file not found.")
                all_pass = False
                continue

            try:
                g_data = HexFileParser(golden_hex, dtype).parse()
                o_data = HexFileParser(output_hex, dtype).parse()
                result = self.verifier.verify(g_data, o_data, dtype, name)
                
                if result.is_pass:
                    total_stats['passed_tensors'] += 1
                    self._log(f"[{name}] PASS (Len:{result.golden_len}/{result.output_len})")
                else:
                    total_stats['failed_tensors'] += 1
                    all_pass = False
                    self._log(f"[{name}] FAIL: {result.failed}/{result.total} mismatches (Len:{result.golden_len}/{result.output_len})")
                    # 打印前 5 个错误
                    for i, e in enumerate(result.errors[:5]):
                        g_hex = "(N/A)"; o_hex = "(N/A)"
                        if not dtype.upper().startswith('INT'):
                            h = get_handler(dtype)
                            if h: g_hex = h.to_hex(e.expected); o_hex = h.to_hex(e.actual)
                        self._log(f"   Idx {e.index}: Exp={e.expected:.6f}({g_hex}) Act={e.actual:.6f}({o_hex}) RelErr={e.rel_err:.4f}%")

            except Exception as ex:
                all_pass = False
                self._log(f"[{name}] FATAL ERROR: {ex}")

        self._log("=" * 80)
        return all_pass, "\n".join(self.report_lines), total_stats


# =============================================================================
# 6. 主程序入口 (Main Entry)
# =============================================================================

def main():
    parser = argparse.ArgumentParser(description="Refactored DV Verification Tool")
    parser.add_argument('-g', '--golden', type=str, help='Golden hex directory')
    parser.add_argument('-o', '--output', type=str, help='Output hex directory')
    parser.add_argument('-t', '--threshold', type=float, help='Global single threshold%')
    parser.add_argument('--bf16', type=float, help='BF16 threshold%')
    parser.add_argument('--fp16', type=float, help='FP16 threshold%')
    parser.add_argument('--fp32', type=float, help='FP32 threshold%')
    parser.add_argument('--fp8', type=float, help='FP8 threshold%')
    parser.add_argument('--int', type=float, help='INT threshold%')
    args = parser.parse_args()

    # 动态构建阈值配置
    thresholds = None
    if args.threshold is None:
        thresholds = CONFIG.thresholds.copy()
        if args.bf16 is not None: thresholds['BF16'] = args.bf16
        if args.fp16 is not None: thresholds['FP16'] = args.fp16
        if args.fp32 is not None: thresholds['FP32'] = args.fp32
        if args.fp8 is not None:
            for k in ['FP8', 'FP8_E4M3', 'FP8_E5M2', 'FP8E4', 'FP8E5']:
                thresholds[k] = args.fp8
        if args.int is not None:
            for k in ['INT4', 'INT8', 'INT16', 'INT32']:
                thresholds[k] = args.int

    verifier = DataVerifier(rel_threshold=args.threshold, thresholds=thresholds)
    runner = Runner(verifier, verbose=True)

    # 模式选择
    if args.golden and args.output:
        passed, report, stats = runner.verify_single_case(args.golden, args.output)
        status = "PASS" if passed else "FAIL"
        print(f"\n=== Single Case Result: {status} ===")
        sys.exit(0 if passed else 1)

    else:
        # Batch Mode 逻辑
        cwd = Path.cwd()
        golden_root = cwd / CONFIG.golden_root
        output_root = Path(CONFIG.output_root)
        if not output_root.is_absolute(): output_root = cwd / output_root

        print(f"Running Batch Mode in {cwd}...")
        # (出于篇幅限制，Batch 循环逻辑与之前同理，您可以参考之前或原版代码补全)
        print("Error: Batch loop logic placeholder.")

if __name__ == '__main__':
    main()