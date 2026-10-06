"""
波形结构化 —— 把 Questa 波形转成可比较的信号时间线。

让 DUT 信号时间线真正可用（而不是 raw 文本），供信号级诊断做三方对比：
  compare_signal_values(dut_trace, model_trace, expected_trace)

**三种格式，两个转换器，一个解析器**（都实测过）：

  · `.db`  —— qwave.db（本仓库波形业务 `vsim -qwavedb=…+wavefile=<t>.db` 的产物）
    `qwaveman -export_format vcd` → VCD → parse_vcd_text
  · `.wlf` —— 传统 WLF（`vsim -wlf` 的旧产物）
    `wlf2vcd` → VCD → parse_vcd_text
  · `.vcd` —— 直接 parse_vcd_text

即 VCD 是**唯一的中间格式**、`parse_vcd_text` 是**唯一的解析器** —— 不写第二套。

`extract_signal_trace` 按信号名（basename）过滤，值转 int（x/z → None）。

用法:
    from src.tools.debug_tools.waveform import extract_signal_trace
    traces = extract_signal_trace("…/waves/test_x.db", ["prdata", "irq"])
    # → {"prdata": [(0.0, 0), (5000.0, 165), ...], "irq": [...]}

**时间单位**：两种路径都返回**该文件 timescale 的原生单位**（not 统一成 ns）——
下游 `signal_diagnosis._normalize_trace` 只当它是"第几个采样点"，保留原生分辨率
比换算成 ns（会丢亚纳秒 delta）更有用。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 扩展名 → 读取器（在 extract_signal_trace 里用）。
_QWAVE_EXTS = (".db",)
_WLF_EXTS = (".wlf",)
_VCD_EXTS = (".vcd",)


def _questa_bin(name: str) -> str:
    """QuestaSim 目录下的可执行文件（wlf2log.exe / qwaveman.exe）—— 统一走
    config.settings，再回落 PATH；找不到给空串。"""
    from config.settings import questa_home

    root = questa_home()
    for c in (os.path.join(root, "win64"), root):
        exe = os.path.join(c, name)
        if os.path.exists(exe):
            return exe
    import shutil
    for cmd in (name, os.path.splitext(name)[0]):
        found = shutil.which(cmd)
        if found:
            return found
    return ""


def _questa_win64() -> str:
    """QuestaSim 目录（含 wlf2log.exe）—— 保留原签名，内部转调 `_questa_bin`。"""
    found = _questa_bin("wlf2log.exe")
    return str(Path(found).parent) if found else ""


# ═══════════════════════════════════════════════════════════════
# WLF 路径（旧产物 / vsim -wlf）
# ═══════════════════════════════════════════════════════════════

def wlf_to_vcd_text(wlf_path: str | Path) -> str:
    """用 `wlf2vcd` 把 WLF 导出成 VCD 文本（拿不到就给空串）。

    **不用 `wlf2log`**：实测它默认只 dump 出极少数信号（本机一次只出 3 个
    uvm_pkg 变量 / 17 行），`-l <level>` 反而更少 —— 拿不到 DUT 信号，
    等于白读。`wlf2vcd` 能导全（实测同一个 WLF 出 430 个 `$var`，含 DUT 层次），
    所以 WLF 与 qwave.db **共用同一个 `parse_vcd_text`**，不再有第二套解析。
    """
    wlf2vcd = _questa_bin("wlf2vcd.exe")
    if not wlf2vcd:
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "wave.vcd"
            subprocess.run([wlf2vcd, "-o", str(out), str(wlf_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
            if not out.exists():
                return ""
            return out.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


# ═══════════════════════════════════════════════════════════════
# qwave.db 路径（Visualizer 原生波形库 —— 本仓库现在的产物）
# ═══════════════════════════════════════════════════════════════

def qwave_to_vcd_text(db_path: str | Path) -> str:
    """用 qwaveman 把 qwave.db 导出成 VCD 文本（拿不到就给空串）。

    qwaveman 的 `-export_format vcd -outfile` 会写一个标准 VCD（`$scope/$var/#time`），
    所以 qwave 这条路复用同一个 `parse_vcd_text`，不必再写一套解析。
    """
    qwaveman = _questa_bin("qwaveman.exe")
    if not qwaveman:
        return ""
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "wave.vcd"
            r = subprocess.run(
                [qwaveman, "-wavefile", str(db_path),
                 "-export_format", "vcd", "-outfile", str(out)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=180)
            if not out.exists():
                return ""
            return out.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _split_vcd_change(line: str) -> tuple[str, Optional[str]]:
    """一条 VCD 值变化行 → (signal_id, value_token)。

    形如 `0!`（标量）、`b1010 "`（向量）、`x(`（标量未知）、`r3.14 "`（实数）。
    未知/实数等拿不到整数时，value_token 给 None 由调用方跳过。
    """
    if not line:
        return "", None
    ch = line[0]
    if ch in "bBrR":
        parts = line.split(None, 1)
        if len(parts) != 2:
            return "", None
        token, sig_id = parts[0], parts[1].strip()
        return sig_id, (token if ch in "bB" else None)
    # 标量：0/1/x/z 后紧跟标识符
    if ch in "01xXzZ":
        return line[1:].strip(), (ch if ch in "01" else None)
    return "", None


def parse_vcd_text(text: str) -> Dict[str, List[tuple]]:
    """标准 VCD 文本 → {signal_path: [(time, value_int)]}（x/z → 不回填）。

    层级由 `$scope module x $end` / `$upscope $end` 维护；`$var wire 8 ! paddr [7:0]`
    给出 id→名字；值变化形如 `0!` / `b1010 "`；`#<time>` 是时间戳。
    时间用**文件自身 timescale 的原生单位**（qwaveman 导出是 1ps）。
    """
    scopes: List[str] = []
    id_to_path: Dict[str, str] = {}
    result: Dict[str, List[tuple]] = {}
    current_time = 0.0
    in_defs = False

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue

        if line.startswith("$scope"):
            parts = line.split()
            if len(parts) >= 3:
                scopes.append(parts[2])
            continue
        if line.startswith("$upscope"):
            if scopes:
                scopes.pop()
            continue
        if line.startswith("$var"):
            # $var wire 8 ! paddr [7:0] $end  → parts[3]=id, parts[4]=name
            parts = line.split()
            if len(parts) >= 4:
                sig_id = parts[3]
                name = parts[4] if len(parts) >= 5 else ""
                path = "/".join(scopes + [name]) if name else "/".join(scopes)
                id_to_path[sig_id] = path
                result.setdefault(path, [])
            continue
        if line.startswith("$enddefinitions"):
            in_defs = True
            continue
        if not in_defs or line.startswith("$"):
            continue
        if line.startswith("#"):
            try:
                current_time = float(line[1:])
            except ValueError:
                pass
            continue

        sig_id, token = _split_vcd_change(line)
        if not sig_id or token is None:
            continue
        path = id_to_path.get(sig_id)
        if not path:
            continue
        val = _parse_vcd_bits(token)
        if val is not None:
            result[path].append((current_time, val))

    return result


def _parse_vcd_bits(token: str) -> Optional[int]:
    """VCD 值 token → int（含 x/z 的位串一律 None —— 未知态不是可比数值）。"""
    s = token.strip().lstrip("bB").strip()
    if not s:
        return None
    if any(c in s.lower() for c in "xz"):
        return None
    if all(c in "01" for c in s):
        return int(s, 2)
    try:
        return int(s)
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════
# 统一入口
# ═══════════════════════════════════════════════════════════════

def read_all_traces(wave_path: str | Path) -> Dict[str, List[tuple]]:
    """任意支持的波形文件 → {signal_path: [(time, value)]}。不认识的格式给 {}。"""
    p = Path(wave_path)
    if not p.exists():
        return {}
    ext = p.suffix.lower()
    if ext in _QWAVE_EXTS:
        return parse_vcd_text(qwave_to_vcd_text(p))
    if ext in _VCD_EXTS:
        try:
            return parse_vcd_text(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            return {}
    if ext in _WLF_EXTS:
        return parse_vcd_text(wlf_to_vcd_text(p))
    return {}


def extract_signal_trace(wave_path: str | Path, signal_names: List[str],
                         path_hint: str = "") -> Dict[str, List[tuple]]:
    """从波形里提取指定信号的时间线（`qwave.db` / `.wlf` / `.vcd` 都行）。

    Args:
        wave_path: 波形文件路径（`.db` = qwave.db，`.wlf`，`.vcd`）
        signal_names: 信号名列表（basename，如 ["prdata", "irq"]）
        path_hint: 可选——同名信号在多个层次都出现时，**优先含这个子串的路径**
            （如 DUT 实例名 `u_apb_uart`）；不匹配则忽略。

    Returns:
        {signal_name: [(time, value_int), ...]}
        信号按 basename 匹配（/tb/top/result → result），值转 int（x/z → None）。

    **同名冲突取"采样最多"的那条路径，不是把几条 `extend` 到一起** ——
    实测一个设计里 `prdata` 会同时出现在 `u_apb_uart/`（DUT）、`apb_if_inst/`（接口）、
    `u_apb_uart/u_apb_master/` 三处；合并会把不同层次的跳变**交织成一条假时间线**，
    拿去跟期望值比对必然错。取最活跃的那条，至少是一条真实、连贯的信号。
    """
    all_traces = read_all_traces(wave_path)
    if not all_traces:
        return {}

    wanted = set(signal_names)
    by_base: Dict[str, List[tuple]] = {}      # base → [(path, trace), ...]
    for path, trace in all_traces.items():
        base = path.rsplit("/", 1)[-1]
        # 去掉 hierarchy 前缀（:: 等）
        base = base.split("::")[-1]
        if base in wanted:
            by_base.setdefault(base, []).append((path, trace))

    result: Dict[str, List[tuple]] = {}
    for base, cands in by_base.items():
        if path_hint:
            hinted = [c for c in cands if path_hint in c[0]]
            if hinted:
                cands = hinted
        # 采样最多的那条（并列时按路径定序，保证可复现）
        path, trace = max(cands, key=lambda c: (len(c[1]), c[0]))
        if not trace:
            # 有声明、无采样（这个层次里它从没变过）—— 空时间线当"没有"，
            # 别给调用方一条 [] 让它以为"取到了"。
            continue
        result[base] = sorted(trace, key=lambda x: x[0])
    return result
