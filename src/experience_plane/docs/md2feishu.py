"""md2feishu —— 把 GitHub 风 Markdown 转成飞书云文档能正确识别的 Markdown。

飞书对手写 Markdown 的几处不兼容（其余语法都兼容）：

  1. ``$...$`` 被当 LaTeX 公式 —— 正文里裸露的 ``$`` 会吞掉成对文本
  2. 标题内的行内代码标记（反引号）会被丢掉，反引号原样显示
  3. 裸露的 ``<xxx`` 被当 HTML 标签吞掉，吃掉该行后半截
  4. 相对链接变成死链（飞书文档里没有仓库上下文）

本工具自动处理的：

  - 标题：去掉行内代码标记
  - 链接：``[文本](相对路径)`` 降级为行内代码；``http(s)://`` 绝对链接原样保留
  - 文件头插入「本文件是飞书专用版」说明（``--no-note`` 关闭）

本工具只报告、不擅自改的（``--check`` 下退出码 1）：

  - 标题 / 正文里裸露的 ``$`` 或 ``<xxx`` —— 改法取决于语义（是把变量名写成
    中文说明，还是把字面量包成行内代码），工具猜不出来，交给人定。

用法::

    python -m src.experience_plane.docs.md2feishu -i userguide.md
    python -m src.experience_plane.docs.md2feishu -i userguide.md -o userguide.feishu.md
    python -m src.experience_plane.docs.md2feishu -i userguide.md --check

契约：产出必须能被飞书「导入文档」和「直接粘贴」两种方式正确识别；
      转换是幂等的（对已转换的输入再跑一次结果不变）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

# 围栏代码块起止（``` 或 ~~~，允许前导空白与语言标注）
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")
# ATX 标题
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
# 行内代码（含多反引号形式 `x` / ``x``）
_CODE_SPAN_RE = re.compile(r"`+[^`]*`+")
# 链接：[文本](目标)
_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)\s]+)\)")
# 疑似 HTML 标签起始。刻意放宽到「< 后面不是空白或 >」：严格按 HTML 规则
# 标签名须以字母开头（`<3.13` 不算标签），但飞书的解析器未必规矩，
# 与其赌它规矩，不如把可疑的都报出来让人定夺。
_ANGLE_RE = re.compile(r"<[^\s>]")
_ABSOLUTE_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.I)

# 说明块的识别标记（幂等用：已转换过的文件不再叠加说明）
_NOTE_MARKER = "的飞书专用版"

_NOTE = (
    "> 本文件是 {src} 的飞书专用版：只调整了飞书不认的 Markdown 写法\n"
    "> （`$` 会被当公式、标题内的反引号会被吞、裸露的 `<` 会被当 HTML 标签、\n"
    "> 相对链接会变成死链），正文内容与原文一致。由 `md2feishu` 自动生成，\n"
    "> 请勿直接编辑 —— 改 {src} 后重新跑一次即可。\n"
)


def _segments(line: str) -> List[Tuple[str, bool]]:
    """把一行切成 [(片段, 是否行内代码)] —— 行内代码里的 $ 和 < 是安全的。"""
    parts: List[Tuple[str, bool]] = []
    pos = 0
    for m in _CODE_SPAN_RE.finditer(line):
        if m.start() > pos:
            parts.append((line[pos:m.start()], False))
        parts.append((m.group(0), True))
        pos = m.end()
    if pos < len(line):
        parts.append((line[pos:], False))
    return parts


def _delink(text: str) -> str:
    """[文本](相对路径) → `文本`；绝对链接原样保留。"""
    def repl(m: "re.Match[str]") -> str:
        label, target = m.group(1), m.group(2)
        if _ABSOLUTE_RE.match(target):
            return m.group(0)
        return f"`{label or target}`"

    return _LINK_RE.sub(repl, text)


def _convert_line(line: str, warnings: List[str], lineno: int) -> str:
    heading = _HEADING_RE.match(line)
    if heading:
        # 标题：飞书丢掉行内代码格式，反引号会原样显示 —— 直接去掉
        return f"{heading.group(1)} {heading.group(2).replace('`', '')}"

    out: List[str] = []
    for text, is_code in _segments(line):
        if is_code:
            out.append(text)
            continue
        text = _delink(text)
        # 剥掉本次降级刚加上的行内代码，再查未受保护的 $ 与 <
        bare = _CODE_SPAN_RE.sub("", text)
        if "$" in bare:
            warnings.append(f"  L{lineno}: 正文有裸露的 $ —— {line.strip()[:70]}")
        if _ANGLE_RE.search(bare):
            warnings.append(f"  L{lineno}: 正文有裸露的 <xxx —— {line.strip()[:70]}")
        out.append(text)
    return "".join(out)


def convert(text: str, src_name: str = "源文件", note: bool = True) -> Tuple[str, List[str]]:
    """返回 (转换后的文本, warning 列表)。"""
    lines = text.split("\n")
    warnings: List[str] = []
    out: List[str] = []
    in_fence = False

    for i, line in enumerate(lines, 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)          # 代码块内原样保留
            continue
        converted = _convert_line(line, warnings, i)
        # 标题里的裸露 $ / < 同样要报（_convert_line 只查正文）
        if _HEADING_RE.match(line):
            body = converted.split(" ", 1)[1]
            if "$" in body:
                warnings.append(f"  L{i}: 标题有裸露的 $ —— {line.strip()[:70]}")
            if _ANGLE_RE.search(body):
                warnings.append(f"  L{i}: 标题有裸露的 <xxx —— {line.strip()[:70]}")
        out.append(converted)

    if note:
        out = _insert_note(out, src_name)

    return "\n".join(out), warnings


def _insert_note(lines: List[str], src_name: str) -> List[str]:
    """在首个 H1 之后的第一段正文后面插入飞书版说明（已存在则不重复插）。"""
    if any(_NOTE_MARKER in l for l in lines):
        return lines          # 幂等：已是转换产物，不再叠加说明
    h1 = next((i for i, l in enumerate(lines) if _HEADING_RE.match(l)), None)
    if h1 is None:
        return lines
    # 找 H1 之后第一段的结束（第一个空行之后再遇到空行，即段末）
    i = h1 + 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    while i < len(lines) and lines[i].strip():
        i += 1
    return lines[:i] + ["", _NOTE.format(src=src_name).rstrip("\n")] + lines[i:]


def _process(src: Path, dst: Path, note: bool) -> List[str]:
    text = src.read_text(encoding="utf-8")
    converted, warnings = convert(text, src_name=src.name, note=note)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(converted, encoding="utf-8")
    return warnings


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="md2feishu",
        description="把 Markdown 转成飞书云文档能正确识别的 Markdown")
    ap.add_argument("-i", "--input", required=True, type=Path,
                    help="输入 .md（或目录，递归处理 *.md）")
    ap.add_argument("-o", "--output", type=Path,
                    help="输出文件（单文件时；缺省 <输入>.feishu.md）")
    ap.add_argument("--no-note", action="store_true",
                    help="不在文件头插入「飞书专用版」说明")
    ap.add_argument("--check", action="store_true",
                    help="只检查不写文件；有 warning 则退出码 1")
    ap.add_argument("-q", "--quiet", action="store_true", help="静默")
    args = ap.parse_args(argv)

    if not args.input.exists():
        print(f"输入不存在: {args.input}", file=sys.stderr)
        return 2

    if args.input.is_dir():
        if args.output:
            print("-o 仅用于单文件输入", file=sys.stderr)
            return 2
        targets = sorted(p for p in args.input.rglob("*.md")
                         if not p.name.endswith(".feishu.md"))
        pairs = [(p, p.with_suffix(".feishu.md")) for p in targets]
    else:
        dst = args.output or args.input.with_suffix(".feishu.md")
        pairs = [(args.input, dst)]

    all_warnings: List[str] = []
    for src, dst in pairs:
        if args.check:
            converted, warnings = convert(src.read_text(encoding="utf-8"),
                                          src_name=src.name, note=not args.no_note)
        else:
            warnings = _process(src, dst, note=not args.no_note)
            if not args.quiet:
                print(f"  {src} -> {dst}")
        if warnings:
            all_warnings += warnings
            print(f"[WARNING] {src}: {len(warnings)} 处需人工处理", file=sys.stderr)
            for w in warnings:
                print(w, file=sys.stderr)

    if not args.quiet:
        print(f"转换 {len(pairs)} 个文件，{len(all_warnings)} 条 warning")
    return 1 if all_warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())
