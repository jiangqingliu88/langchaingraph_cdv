"""轻量 secret 扫描 —— CI 的第一道闸，不依赖 gitleaks 安装。

只扫描 **git tracked 文件**（不看 venv/output/logs），对常见 token 前缀做高置信
匹配；命中即 exit 1。真正的历史泄露仍需轮换凭据 + `git filter-repo`，这里只能
阻止“新的明文凭据再进仓库”。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

#: 高置信前缀；宁可少报，也不要把普通示例字符串变成噪音。
PATTERNS = {
    "openai/deepseek-style": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "aws-access-key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "github-token": re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    "slack-token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
#: 文档里明确标注的占位符不算。
ALLOW = re.compile(r"(<your[-_ ]|example|placeholder|not-needed|xxx+)", re.I)
#: 二进制/大文件不扫。
SKIP_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".7z",
    ".bin", ".elf", ".db", ".ucdb", ".qpg", ".wlf", ".fsdb", ".vcd", ".pyc",
}


def _tracked_files() -> list[Path]:
    out = subprocess.check_output(["git", "ls-files"], text=True,
                                  encoding="utf-8", errors="replace")
    return [Path(line) for line in out.splitlines() if line.strip()]


def scan() -> list[str]:
    hits: list[str] = []
    for path in _tracked_files():
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if ALLOW.search(line):
                continue
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    hits.append(f"{path}:{lineno}: {name}")
    return hits


def main() -> int:
    hits = scan()
    if not hits:
        print("secret scan: clean")
        return 0
    print("secret scan: found potential credentials (values are not printed):")
    for hit in hits:
        print(f"  {hit}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
