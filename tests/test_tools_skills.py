"""Native Skills —— 工具知识要能被 LLM 读到。

每个 SKILL.md 是**给模型读的契约**，不是 README。固定骨架：
什么时候用 / 不要用 / 正确调用 / 常见错误 / 日志里看什么 / 产物。
"""
from __future__ import annotations

from pathlib import Path

import pytest

SKILLS = (
    Path("src/layers/l3_decision/evidence/SKILL.md"),
    Path("src/tools/generation/casemodel_tools/SKILL.md"),
)

REQUIRED = ("什么时候用我", "不要用我", "正确调用方式", "常见错误", "产物")


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_skill_has_the_contract_sections(path):
    assert path.is_file(), f"缺 SKILL.md：{path}"
    text = path.read_text(encoding="utf-8")
    for section in REQUIRED:
        assert section in text, f"{path} 缺段落：{section}"


def test_skills_live_under_their_board_directory():
    """技能文件跟着工具板块走，不放在仓库根散着。"""
    for path in SKILLS:
        assert "/checking/" in path.as_posix() or "/generation/" in path.as_posix()
