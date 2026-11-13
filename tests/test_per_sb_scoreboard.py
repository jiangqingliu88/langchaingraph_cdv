"""逐条 scoreboard 收口的两条硬规则（真 pass 的"比对"半边）。

1. **判据锚点**：pass 不能只 grep `mismatched=0`。env 会为每条 SB 打
   `[SCB <id>] … mismatched=0`，子串匹配会让"某条干净、聚合脏"的日志也过；
   只认聚合收口行（`[SCB_DUT]` / `Scoreboard:`）。
2. **归属不猜**：模型的 `scoreboards[].rules` 名字**真对得上**才发逐条行；
   `evidence: aggregate` 的 SB 明确只要聚合行。
"""
from __future__ import annotations

import re

from src.engine.verify.dut_checker import _per_sb_rules
from src.layers.l2_orchestration.regression_tools.backend_profiles import (
    QUESTA_TEMPLATE,
)

ANCHOR = r"(\[SCB_DUT\]|Scoreboard:).*mismatched=0"


def test_pass_anchor_is_not_a_bare_mismatched_check():
    assert ANCHOR in QUESTA_TEMPLATE
    # 只有某条 SB 干净、没有聚合行 → 不算 pass（这正是子串匹配会骗过的情况）
    assert not re.search(ANCHOR, "[SCB cg_scb] expected=9 matched=9 mismatched=0")
    # 聚合行干净 → pass
    assert re.search(ANCHOR, "[SCB_DUT] expected=9 matched=9 mismatched=0")
    assert re.search(ANCHOR, "Scoreboard: top.env.scb matched=9 mismatched=0")


def test_scoreboard_ownership_is_declared_not_guessed():
    rules = [{"name": "raw_never_issues"}, {"name": "issue_needs_no_blocker"}]
    owned = _per_sb_rules(
        [{"id": "SB-DUT", "rules": ["raw_never_issues"]}], rules)
    assert owned == [{"id": "SB-DUT", "rules": ["raw_never_issues"]}]
    # 名字对不上 → 不发（静默取一条会让签核看到假的逐条证据）
    assert _per_sb_rules([{"id": "SB-X", "rules": ["misspelled"]}], rules) == []
    # 明确要聚合行 → 不发逐条
    assert _per_sb_rules(
        [{"id": "SB-AGG", "rules": ["raw_never_issues"], "evidence": "aggregate"}],
        rules) == []
