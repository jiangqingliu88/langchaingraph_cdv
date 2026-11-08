"""Native Skills —— 工具知识要能被 LLM 读到。

每个 SKILL.md 是**给模型读的契约**，不是 README。固定骨架：
什么时候用 / 不要用 / 正确调用 / 常见错误 / 日志里看什么 / 产物。
"""
from __future__ import annotations

from pathlib import Path

import pytest

SKILLS = (
    Path("src/layers/l3_decision/evidence/SKILL.md"),
)

REQUIRED = ("什么时候用我", "不要用我", "正确调用方式", "常见错误", "产物")


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_has_the_contract_sections(path):
    assert path.is_file(), f"缺 SKILL.md：{path}"
    text = path.read_text(encoding="utf-8")
    for section in REQUIRED:
        assert section in text, f"{path} 缺段落：{section}"


def test_skills_live_with_the_module_they_document():
    """技能文件跟着**实现**走（同目录），不放仓库根散着。

    `evidence` 已迁进 l3 层，所以不再要求
    `checking/` 或 `generation/`；要求的是"实现旁边有它的技能"。
    """
    for path in SKILLS:
        posix = path.as_posix()
        assert posix.startswith(("src/layers/", "src/tools/")), posix
        assert any(path.parent.glob("*.py")), f"{path} 旁边没有实现文件"
