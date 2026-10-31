"""pragma custom 区域注入 —— 渲染层的独立件。

从 `tool_uvm/gen_uvm.py` 搬出；行为与常量保持不变，`gen_uvm` 继续 re-export
这些名字，外部调用点无需改动。只依赖标准库：不 import 生成器、不读 YAML。

生成文件带 BANNER 签名；`-c/--clean` 只删带签名的文件，绝不碰手写文件。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

TOOL_VERSION = "0.1.0"


def _make_banner(prefix: str = "// ") -> str:
    """生成文件签名 banner（按目标文件类型选注释前缀：SV/filelist 用 //，Makefile 用 #）。"""
    return "\n".join([
        f"{prefix}════════════════════════════════════════════════════════════════",
        f"{prefix}自动生成 (tool_uvm v{TOOL_VERSION}) — 请勿直接修改；"
        f"自定义代码写入 pragma custom 区域",
        f"{prefix}════════════════════════════════════════════════════════════════",
    ]) + "\n"


BANNER = _make_banner("// ")
BANNER_MARKER = "自动生成 (tool_uvm"

REGION_MARKER = re.compile(r"^\s*//\s*pragma\s+custom\s+(\w+)\s+(begin|end)\s*$")


class RegionError(Exception):
    """pragma custom 区域错误（未闭合 / 嵌套 / 同名重复 / 旧源无匹配）。"""


@dataclass
class MergeBlockInfo:
    slot: str
    source: str   # "yaml" | "merged" | "default"
    lines: int


@dataclass
class MergeFileReport:
    relpath: str
    blocks: List[MergeBlockInfo] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


class RegionInjector:
    """pragma custom 区域注入器。

    模板静态写空区域（slot 文件内唯一）；渲染后按优先级回填。
    -m/--merge_source 时预提取旧文件区域表，按目标相对路径索引。
    """

    def __init__(self, merge_source: Optional[Path] = None,
                 skip_missing: bool = False,
                 debug_dir: Optional[Path] = None,
                 report: Optional[List[MergeFileReport]] = None) -> None:
        self.merge_source = Path(merge_source) if merge_source else None
        self.skip_missing = skip_missing
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.report: List[MergeFileReport] = report if report is not None else []
        self.load_errors: List[str] = []   # merge_source 中区域解析失败的文件（不参与合并）
        self._old_blocks: Dict[str, Dict[str, str]] = {}
        if self.merge_source:
            self._load_merge_source(self.merge_source)

    # ── 提取 ──
    @staticmethod
    def extract_blocks(text: str) -> Dict[str, str]:
        """提取 text 中全部 pragma custom 区域 → {slot: 内容}。

        未闭合 / 嵌套 / 同名重复 → RegionError。
        """
        blocks: Dict[str, str] = {}
        current: Optional[str] = None
        buf: List[str] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            m = REGION_MARKER.match(line)
            if m:
                slot, kind = m.group(1), m.group(2)
                if kind == "begin":
                    if current is not None:
                        raise RegionError(
                            f"line {lineno}: region '{slot}' nested inside '{current}'")
                    if slot in blocks:
                        raise RegionError(f"line {lineno}: duplicate region '{slot}'")
                    current = slot
                    buf = []
                else:
                    if current != slot:
                        raise RegionError(
                            f"line {lineno}: region end '{slot}' without begin "
                            f"(open: '{current}')")
                    blocks[slot] = "\n".join(buf)
                    current = None
            elif current is not None:
                buf.append(line)
        if current is not None:
            raise RegionError(f"region '{current}' not closed")
        return blocks

    def _load_merge_source(self, root: Path) -> None:
        """扫描 merge_source 目录，提取每个文件的区域表（按目标相对路径索引）。"""
        if not root.is_dir():
            raise RegionError(f"merge source directory not found: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".sv", ".svh"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                blocks = self.extract_blocks(text)
            except RegionError as exc:
                self.load_errors.append(f"[{path.relative_to(root)}] {exc}")
                continue  # 坏区域文件不参与合并（错误记录进报告）
            if blocks:
                self._old_blocks[str(path.relative_to(root))] = blocks

    # ── 注入 ──
    def inject(self, rendered: str, defaults: Dict[str, str],
               relpath: str, add_banner: bool = True,
               banner_prefix: str = "// ") -> Tuple[str, MergeFileReport]:
        """渲染产物 → 注入后文本。

        defaults = 外部提供的区域内容（非空 → "yaml" 源，每次生成覆盖）。
        生成流程已不再从 YAML 取值（custom_code 下线），该形参仅保留给程序化调用。
        模板区域内已有的默认内容作为最后兜底（"default" 源）。
        """
        report = MergeFileReport(relpath=relpath)
        old = self._old_blocks.get(relpath, {})
        out: List[str] = []
        current: Optional[str] = None
        inner: List[str] = []
        seen: List[str] = []

        for lineno, line in enumerate(rendered.splitlines(), 1):
            m = REGION_MARKER.match(line)
            if m:
                slot, kind = m.group(1), m.group(2)
                if kind == "begin":
                    if current is not None:
                        raise RegionError(
                            f"line {lineno}: region '{slot}' nested inside '{current}'")
                    if slot in seen:
                        raise RegionError(f"line {lineno}: duplicate region '{slot}'")
                    current = slot
                    inner = []
                    out.append(line)
                else:
                    if current != slot:
                        raise RegionError(
                            f"line {lineno}: region end '{slot}' without begin "
                            f"(open: '{current}')")
                    yaml_val = (defaults.get(slot) or "").strip() if defaults else ""
                    old_val = old.get(slot, "")
                    if yaml_val:
                        content, source = yaml_val, "yaml"
                    elif old_val:
                        content, source = old_val, "merged"
                    else:
                        content, source = "\n".join(inner), "default"
                    out.extend(content.splitlines())
                    out.append(line)
                    report.blocks.append(
                        MergeBlockInfo(slot, source, len(content.splitlines())))
                    seen.append(slot)
                    current = None
            elif current is not None:
                inner.append(line)
            else:
                out.append(line)
        if current is not None:
            raise RegionError(f"region '{current}' not closed")

        # 旧文件多出的区域（新模板没有对应槽）
        for slot in sorted(old):
            if slot not in seen:
                if not self.skip_missing:
                    raise RegionError(
                        f"[{relpath}] block '{slot}' found in old source has no "
                        f"matching region in new output "
                        f"(use --merge_skip_missing_blocks to continue)")
                report.missing.append(slot)

        text = "\n".join(out) + "\n"
        if add_banner and BANNER_MARKER not in text:
            text = _make_banner(banner_prefix) + "\n" + text
        if self.debug_dir is not None:
            debug_path = self.debug_dir / relpath
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(rendered + "\n", encoding="utf-8")
        self.report.append(report)
        return text, report


