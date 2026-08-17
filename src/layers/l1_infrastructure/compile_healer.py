"""
编译失败自愈 —— 感知、诊断、处理编译失败

编译失败是比覆盖率不达标更常见、更紧急的问题。决策层必须先处理编译失败。

  编译失败 → 错误分类（10 类）→ 自愈策略 → 重试 → 通过或升级人工
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class CompileErrorType(str, Enum):
    """编译错误类型分类"""
    SUCCESS = "success"
    FILE_NOT_FOUND = "file_not_found"
    SYNTAX_ERROR = "syntax_error"
    MULTI_DRIVER = "multi_driver"
    UNDEFINED_SIGNAL = "undefined_signal"
    PORT_MISMATCH = "port_mismatch"
    ENV_ISSUE = "env_issue"
    LICENSE_ISSUE = "license_issue"
    TOOL_VERSION = "tool_version"
    MEMORY_ISSUE = "memory_issue"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class CompileResult:
    """编译结果"""
    success: bool = True
    error_type: CompileErrorType = CompileErrorType.SUCCESS
    error_message: str = ""
    error_line: Optional[int] = None
    error_file: Optional[str] = None
    retry_count: int = 0
    fix_applied: str = ""


class CompileErrorAnalyzer:
    """编译错误分析器：解析错误日志，分类错误类型"""

    # 错误模式匹配规则（复用 debug_tools 的分类，但更聚焦编译）
    PATTERNS = {
        CompileErrorType.FILE_NOT_FOUND: [
            r"cannot open\s+['\"]([^'\"]+)['\"]",
            r"file\s+['\"]([^'\"]+)['\"]\s+not found",
            r"No such file or directory:\s+(.+)",
            r"Module\s+[\"']([^\"']+)[\"']\s+not defined",
        ],
        CompileErrorType.SYNTAX_ERROR: [
            r"syntax error\s+(?:at|near)\s+['\"]([^'\"]+)['\"]",
            r"expecting\s+['\"]([^'\"]+)['\"]",
            r"unexpected\s+['\"]([^'\"]+)['\"]",
            r"near\s+[\"']([^\"']+)[\"']:\s*syntax error",
        ],
        # vopt-7033/7061/7045: 信号被多个进程/多个连续赋值驱动（多驱动，含组合块/时序块/多 assign 三种变体）
        CompileErrorType.MULTI_DRIVER: [
            r"Variable\s+'(\w+)'\s+driven in a combinational block",
            r"(\w+)\s+driven in a combinational block, may not be driven by any other process",
            r"Variable\s+'(\w+)'\s+driven in an always_ff block",
            r"'(\w+)'\s+is driven by more than one continuous assignment",
            r"multiple\s+driver",
        ],
        CompileErrorType.UNDEFINED_SIGNAL: [
            r"Undefined\s+(?:signal|variable|net|reg)\s+['\"]([^'\"]+)['\"]",
            r"not declared\s+['\"]([^'\"]+)['\"]",
            r"undeclared identifier",
        ],
        CompileErrorType.PORT_MISMATCH: [
            r"port\s+['\"]([^'\"]+)['\"]\s+(?:size|width|direction)\s+mismatch",
            r"incompatible\s+port",
            r"Port\s+['\"]([^'\"]+)['\"]\s+not found in module",
        ],
        CompileErrorType.ENV_ISSUE: [
            r"environment\s+variable\s+['\"]([^'\"]+)['\"]\s+not set",
            r"VCS_HOME\s+not set",
            r"QUESTA_HOME\s+not set",
        ],
        CompileErrorType.LICENSE_ISSUE: [
            r"license\s+(?:checkout|feature)\s+failed",
            r"license\s+server\s+not\s+available",
            r"Unable to checkout.*license",
        ],
        CompileErrorType.TOOL_VERSION: [
            r"version\s+['\"]([^'\"]+)['\"]\s+(?:not supported|incompatible)",
            r"requires\s+(?:version|tool)",
        ],
        CompileErrorType.MEMORY_ISSUE: [
            r"out of memory",
            r"memory\s+exhausted",
            r"cannot allocate",
        ],
        CompileErrorType.TIMEOUT: [
            r"timeout",
            r"cpu time limit exceeded",
            r"elapsed time limit exceeded",
        ],
    }

    @classmethod
    def analyze(cls, stderr: str = "", stdout: str = "") -> CompileResult:
        """分析编译输出，返回错误分类。先匹配错误模式，无匹配才判成功。"""
        combined = stderr + stdout

        # 1. 先尝试匹配已知错误模式
        for error_type, patterns in cls.PATTERNS.items():
            for pattern in patterns:
                m = re.search(pattern, combined, re.IGNORECASE)
                if m:
                    detail = m.group(1) if m.groups() else ""
                    return CompileResult(
                        success=False, error_type=error_type,
                        error_message=f"{error_type.value}: {detail}",
                        error_line=cls._extract_line(combined),
                        error_file=cls._extract_file(combined),
                    )

        # 2. 无匹配错误模式，但有 error 字样 → unknown
        #    （仍提取文件/行号，否则 LLM 兜底修复拿不到文件，只能"无文件名跳过"）
        if re.search(r"\*\*\s*Error|error", combined, re.IGNORECASE):
            return CompileResult(success=False, error_type=CompileErrorType.UNKNOWN,
                                 error_message=f"Unknown compile error: {combined[:200]}",
                                 error_line=cls._extract_line(combined),
                                 error_file=cls._extract_file(combined))

        # 3. 无任何错误 → 成功
        return CompileResult(success=True)

    @staticmethod
    def _extract_line(text: str) -> Optional[int]:
        m = re.search(r"line\s+(\d+)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # vopt 格式:  "...file.sv(NNN): (vopt-...) ... See ...file.sv(MMM)."
        # 冲突的另一处驱动是 "See ...sv(MMM)" 里的 MMM，指向要删的时序赋值行。
        m = re.search(r"See\s+[^\s()]+\.(?:v|sv|vh)\((\d+)\)", text, re.IGNORECASE)
        if m:
            return int(m.group(1))
        return None

    @staticmethod
    def _extract_file(text: str) -> Optional[str]:
        m = re.search(r"in\s+['\"]([^'\"]+\.(?:v|sv|vhd|vhdl))['\"]", text, re.IGNORECASE)
        if m:
            return m.group(1)
        # vopt 格式:  ".../rtl/uart_tx.sv(108): (vopt-7033) ..." —— 取 basename
        m = re.search(r"([A-Za-z0-9_]+\.(?:v|sv|vh))\((\d+)\)", text)
        if m:
            return m.group(1)
        return None


class CompileSelfHealer:
    """编译错误自愈引擎（真实修复，非 Mock）"""

    def __init__(self, work_dir: str = "."):
        self.work_dir = Path(work_dir)
        self.fix_history: List[Dict] = []

    def heal(self, error: CompileResult, rtl_files: List[str] = None) -> Dict:
        """根据错误类型尝试自愈，返回 {fixed, actions, new_files}。"""
        rtl_files = rtl_files or []
        actions = []
        fixed = False
        new_files = list(rtl_files)

        if error.error_type == CompileErrorType.FILE_NOT_FOUND:
            # 在项目中搜索缺失文件
            missing = self._extract_missing_name(error.error_message)
            actions.append(f"搜索缺失文件: {missing}")
            found = self._search_file(missing)
            if found:
                new_files.append(str(found))
                actions.append(f"找到: {found}")
                fixed = True
            else:
                actions.append(f"未找到 {missing}，需人工检查 filelist")

        elif error.error_type == CompileErrorType.UNDEFINED_SIGNAL:
            # 未定义信号 → 尝试在顶部模块加声明（真实文件编辑）
            signal = self._extract_missing_name(error.error_message)
            actions.append(f"未定义信号 {signal}，尝试添加声明")
            if error.error_file:
                fixed = self._add_signal_decl(error.error_file, signal)
                actions.append(f"{'已添加' if fixed else '添加失败'} logic {signal};")

        elif error.error_type == CompileErrorType.ENV_ISSUE:
            actions.append("环境变量缺失，尝试自动设置")
            fixed = self._fix_env(error.error_message)
            actions.append("环境已修复" if fixed else "需手动 source setup 脚本")

        elif error.error_type == CompileErrorType.LICENSE_ISSUE:
            actions.append("License 不可用，建议指数退避重试")
            fixed = False  # License 靠重试，不靠修复

        elif error.error_type == CompileErrorType.MEMORY_ISSUE:
            actions.append("内存不足，建议优化编译选项（-O0 / 增量编译）")
            fixed = False  # 内存靠改编译选项，这里标记为需外部处理

        elif error.error_type == CompileErrorType.TIMEOUT:
            actions.append("编译超时，建议增加超时时间")
            fixed = True

        elif error.error_type == CompileErrorType.SYNTAX_ERROR:
            actions.append(f"语法错误 line {error.error_line}，需 LLM 修复或人工介入")
            fixed = False  # 语法错误复杂，交给 LLM 或人工

        elif error.error_type == CompileErrorType.MULTI_DRIVER:
            # 确定性修复（不依赖 LLM）：分两类多驱动——
            #   vopt-7033（组合块 + 时序块）→ 删时序块 `sig <=`
            #   vopt-7045（多个连续赋值）→ 删显式 `assign sig =`，保留 IP 端口连接
            signal = self._extract_signal(error.error_message)
            fixed = self._remove_sequential_drive(error.error_file, signal)
            if not fixed:
                fixed = self._remove_continuous_assign(error.error_file, signal)
            actions.append(f"多驱动 {signal}：{'确定性已修' if fixed else '未定位到'}（{error.error_file}:{error.error_line}）")

        self.fix_history.append({
            "error_type": error.error_type.value, "actions": actions,
            "fixed": fixed, "error_message": error.error_message,
        })

        return {"fixed": fixed, "actions": actions, "new_files": new_files,
                "history": self.fix_history}

    def _extract_missing_name(self, msg: str) -> str:
        """从错误消息提取缺失的文件/信号名。"""
        return msg.split(":", 1)[-1].strip() if ":" in msg else msg.strip()

    def _extract_signal(self, msg: str) -> str:
        """从 error_message（形如 "multi_driver: tx_reg"）提取被多驱动的信号名。"""
        if ":" in msg:
            return msg.split(":", 1)[-1].strip()
        m = re.search(r"'(\w+)'", msg)
        return m.group(1) if m else msg.strip()

    def _remove_sequential_drive(self, file: str, signal: str) -> bool:
        """确定性修复：删除 `signal <= ...` 非阻塞赋值（时序驱动），保留组合块 `signal = ...`。

        返回是否实际删除了行。这是纯文本修复，不依赖 LLM。
        """
        if not signal:
            return False
        fpath = None
        if file:
            cand = self.work_dir / file
            fpath = cand if cand.exists() else self._search_file(file)
        if fpath is None:
            # 无文件名或按名没搜到 → 全量扫 *.sv 里含 "signal <=" 的文件
            try:
                for p in sorted(self.work_dir.rglob("*.sv")):
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    if re.search(r"^\s*" + re.escape(signal) + r"\s*<=", txt, re.MULTILINE):
                        fpath = p
                        break
            except Exception:
                pass
        if fpath is None:
            return False
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            # 保守：只有信号同时有组合块阻塞赋值 `sig =`（vopt-7033 组合+时序）才删时序驱动。
            # vopt-7061（时序+时序）/ vopt-7045（多 assign）删 `<=` 会删错，交给 LLM 兜底。
            # 词边界匹配，兼容 `IDLE: sig = ...` 这类 case 标签前缀。
            if not re.search(r"\b" + re.escape(signal) + r"\s*=(?!=)", text):
                return False
            lines = text.splitlines()
            pat = re.compile(r"^\s*" + re.escape(signal) + r"\s*<=")
            new_lines = [ln for ln in lines if not pat.search(ln)]
            if len(new_lines) == len(lines):
                return False
            fpath.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
                             encoding="utf-8")
            return True
        except Exception:
            return False

    def _remove_continuous_assign(self, file: str, signal: str) -> bool:
        """确定性修复 vopt-7045：删除显式 `assign sig = ...` 连续赋值（多 assign 驱动）。

        保留 IP 端口连接（`.port(sig)`），只删显式 assign 语句。纯文本修复，不依赖 LLM。
        """
        if not signal:
            return False
        fpath = None
        if file:
            cand = self.work_dir / file
            fpath = cand if cand.exists() else self._search_file(file)
        if fpath is None:
            try:
                for p in sorted(self.work_dir.rglob("*.sv")):
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    if re.search(r"^\s*assign\s+" + re.escape(signal) + r"\s*=", txt, re.MULTILINE):
                        fpath = p
                        break
            except Exception:
                pass
        if fpath is None:
            return False
        try:
            text = fpath.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            pat = re.compile(r"^\s*assign\s+" + re.escape(signal) + r"\s*=")
            new_lines = [ln for ln in lines if not pat.search(ln)]
            if len(new_lines) == len(lines):
                return False
            fpath.write_text("\n".join(new_lines) + ("\n" if text.endswith("\n") else ""),
                             encoding="utf-8")
            return True
        except Exception:
            return False

    def _search_file(self, filename: str) -> Optional[Path]:
        """在项目目录递归搜索文件。"""
        if not filename:
            return None
        for pattern in [f"**/{filename}", f"**/{filename}.*"]:
            for p in self.work_dir.rglob(pattern.split("/")[-1]):
                return p
        return None

    def _add_signal_decl(self, file: str, signal: str) -> bool:
        """在模块声明后添加信号声明。"""
        if not signal or signal in ("", "None"):
            return False
        fpath = self.work_dir / file
        if not fpath.exists():
            return False
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
            decl = f"  logic {signal};\n"
            # 在 module ... ); 后插入
            if decl.strip() not in content:
                new_content = re.sub(
                    r"(module\s+\w+\s*\([^)]*\)\s*;)",
                    r"\1\n" + decl, content, count=1)
                if new_content != content:
                    fpath.write_text(new_content, encoding="utf-8")
                    return True
            return False
        except Exception:
            return False

    def _fix_env(self, msg: str) -> bool:
        """尝试修复环境变量问题。"""
        env_map = {
            "VCS_HOME": "/usr/local/synopsys/vcs",
            "QUESTA_HOME": "f:/questasim64_2024.1/win64",
        }
        fixed = False
        for var, default in env_map.items():
            if var.lower() in msg.lower() and not os.getenv(var):
                os.environ[var] = default
                fixed = True
        return fixed
