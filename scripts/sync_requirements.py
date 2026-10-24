"""从 pyproject.toml 生成 requirements.txt —— **依赖只有一个真相源**。

用法：
    python scripts/sync_requirements.py

`pyproject.toml` 是权威；本脚本把：
  · `[project].dependencies`        → 运行依赖（取消注释）
  · `[project.optional-dependencies].gui` → GUI（取消注释，保持完整环境）
  · 其余 extras / dev               → 注释形式，按需安装

不要手改 requirements.txt —— 下一次同步会覆盖。
"""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
REQUIREMENTS = ROOT / "requirements.txt"


def main() -> int:
    doc = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    project = doc.get("project") or {}
    core = list(project.get("dependencies") or [])
    extras = project.get("optional-dependencies") or {}

    lines = [
        "# AUTO-GENERATED from pyproject.toml — do not edit by hand.",
        "# Regenerate: python scripts/sync_requirements.py",
        "",
        "# ── 运行依赖 ─────────────────────────────────────────────",
        *core,
        "",
        "# ── GUI（可选；本文件默认装，纯 CLI 可删）──────────────",
        *(extras.get("gui") or []),
        "",
    ]
    labels = {
        "docs": "更多规格格式（python-docx / pypdf）",
        "anthropic": "Anthropic 提供商",
        "integrations": "Slack / 工具市场 / 数据脚本",
        "api": "HTTP API 与认证（CLI 不需要）",
        "dev": "开发/测试",
    }
    for name, deps in extras.items():
        if name == "gui" or not deps:
            continue
        lines.append(f"# ── 可选：{labels.get(name, name)} ──")
        lines.extend(f"# {dep}" for dep in deps)
        lines.append("")

    REQUIREMENTS.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"wrote {REQUIREMENTS} ({len(core)} core deps)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
