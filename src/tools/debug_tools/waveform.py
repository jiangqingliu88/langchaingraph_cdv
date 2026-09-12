"""
波形结构化 —— 把 QuestaSim WLF 波形转成可比较的信号时间线。

让 DUT 信号时间线真正可用（而不是 raw 文本），供信号级诊断做三方对比：
  compare_signal_values(dut_trace, model_trace, expected_trace)

实现：
  wlf2log 把 WLF 转成文本 → parse_wlf_text 解析成 {signal_path: [(time, value)]}
  extract_signal_trace 按信号名（basename）过滤，值转 int（x/z → None）

用法:
    from src.tools.debug_tools.waveform import extract_signal_trace
    traces = extract_signal_trace("output/xx/vsim.wlf", ["result", "opcode"])
    # → {"result": [(0.0, 0), (5.0, 0), ...], "opcode": [...]}
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _questa_win64() -> str:
    """QuestaSim 目录（含 wlf2log.exe）—— 统一走 config.settings，再回落 PATH。"""
    from config.settings import questa_home
    root = questa_home()
    for c in (os.path.join(root, "win64"), root):
        if os.path.exists(os.path.join(c, "wlf2log.exe")):
            return c
    # PATH 搜索
    import shutil
    for cmd in ["wlf2log.exe", "wlf2log"]:
        found = shutil.which(cmd)
        if found:
            return str(Path(found).parent)
    return os.path.join(root, "win64")


def wlf_to_text(wlf_path: str | Path) -> str:
    """用 wlf2log 把 WLF 转成文本。"""
    wlf2log = os.path.join(_questa_win64(), "wlf2log.exe")
    if not os.path.exists(wlf2log):
        return ""
    try:
        r = subprocess.run([wlf2log, str(wlf_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
        return r.stdout
    except Exception:
        return ""


def parse_wlf_text(text: str) -> Dict[str, List[tuple]]:
    """解析 wlf2log 文本，返回 {signal_path: [(time_ns, value_int)]}。

    文本格式（QuestaSim WLF）:
        D /tb/top/opcode 3 [0] net     ← 信号声明: 路径 id [range] 类型
        S 3 ['000...']                 ← 信号值: id value
        T 5.000                        ← 时间戳（单位见 P timestep，默认 1ps）
    """
    signals: Dict[str, str] = {}   # id → path
    result: Dict[str, List[tuple]] = {}
    current_time_ns = 0.0

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        # P timestep / # Resolution —— WLF 内部精度元数据（时间戳单位见下）
        if line.startswith("P timestep") or line.startswith("# Resolution"):
            continue

        # D <path> <id> [range] <type>
        if line.startswith("D "):
            parts = line.split()
            if len(parts) >= 3:
                path, sig_id = parts[1], parts[2]
                signals[sig_id] = path
                result.setdefault(path, [])
            continue

        # S <id> <value>
        if line.startswith("S "):
            parts = line.split(None, 2)
            if len(parts) >= 3:
                sig_id, value_str = parts[1], parts[2]
                path = signals.get(sig_id)
                if path:
                    val = _parse_wlf_value(value_str)
                    if val is not None:
                        result[path].append((current_time_ns, val))
            continue

        # T <time> —— 经验：QuestaSim WLF 的 T 值在 timescale 1ns 下直接是纳秒
        if line.startswith("T "):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    current_time_ns = float(parts[1])
                except ValueError:
                    pass
            continue

    return result


def _parse_wlf_value(value_str: str) -> Optional[int]:
    """把 WLF 值字符串转成 int（x/z 未知态返回 None）。"""
    s = value_str.strip()
    # 去掉 ['...'] 或 '...' 包裹
    if s.startswith("['") and s.endswith("']"):
        s = s[2:-2]
    elif s.startswith("'") and s.endswith("'"):
        s = s[1:-1]
    s = s.strip()
    if not s:
        return None
    # 未知态（x/z）
    if any(c in s.lower() for c in "xz"):
        return None
    # 纯 bit 串（0/1）→ 二进制
    if all(c in "01" for c in s):
        return int(s, 2)
    # 十进制（含负数）
    try:
        return int(s)
    except ValueError:
        return None


def extract_signal_trace(wlf_path: str | Path, signal_names: List[str]) -> Dict[str, List[tuple]]:
    """从 WLF 波形提取指定信号的时间线。

    Args:
        wlf_path: WLF 文件路径
        signal_names: 信号名列表（basename，如 ["result", "opcode"]）

    Returns:
        {signal_name: [(time_ns, value_int), ...]}
        信号按 basename 匹配（/tb/top/result → result），值转 int。
    """
    wlf = Path(wlf_path)
    if not wlf.exists():
        return {}

    text = wlf_to_text(wlf)
    if not text:
        return {}

    all_traces = parse_wlf_text(text)
    wanted = set(signal_names)
    result = {}
    for path, trace in all_traces.items():
        base = path.rsplit("/", 1)[-1]
        # 去掉 hierarchy 前缀（:: 等）
        base = base.split("::")[-1]
        if base in wanted:
            result.setdefault(base, []).extend(trace)
    # 按时间排序
    for k in result:
        result[k].sort(key=lambda x: x[0])
    return result
