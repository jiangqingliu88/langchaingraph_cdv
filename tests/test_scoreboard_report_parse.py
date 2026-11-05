"""`env_arch_check` 读 scoreboard 结算报告 —— 解析必须对上**真的打出来的格式**。

## 为什么要专门钉这个

`tool_check_env_arch` 原先只认一句

    Scoreboard: total=N matched=M mismatched=K

而全仓没有任何 scoreboard 打过这个形状（`grep 'total='` 在 `base_pkg/` 里一个都
搜不到）。`in_order_scoreboard.get_report_string()` 打的是**每行一个字段**的块
（Expected items / Actual items / Matches / Mismatches / Missing / Extra）。

两边对不上，正则永远不命中，于是每一轮 env_arch_check 都报
「未找到 scoreboard 结果（仿真可能超时/崩溃）」—— 把**解析不上**说成**仿真崩了**。

所以这组测试用**scoreboard 自己那份格式的原文**当输入，不再是"照着我以为的
格式编一个"。只要有人改了 `.svh` 里的报告文案而忘了改这边，这里就红。
"""
from src.tools.generation.uvm_tools.checking.tool_check_env_arch.main import (
    _parse_scoreboard_report,
    _scoreboard_passed,
)


def _report(*, expected, actual, matches, mismatches, missing, extra,
            name="uvm_test_top.env.scb"):
    """按 `in_order_scoreboard.get_report_string()` 的**逐字**格式拼一份报告。"""
    return (
        "UVM_INFO @ 100: reporter [RNTST] Running test ...\n"
        "===========================================================\n"
        f"Scoreboard: {name}\n"
        "===========================================================\n"
        f"  Expected items : {expected}\n"
        f"  Actual items   : {actual}\n"
        f"  Matches        : {matches}\n"
        f"  Mismatches     : {mismatches}\n"
        f"  Missing        : {missing}\n"
        f"  Extra          : {extra}\n"
        "  Match Rate     : 100.00%\n"
        "===========================================================\n"
    )


class TestParsesTheRealFormat:
    def test_all_matched(self):
        total, matched, mismatched = _parse_scoreboard_report(
            _report(expected=12, actual=12, matches=12, mismatches=0,
                    missing=0, extra=0))
        assert (total, matched, mismatched) == (12, 12, 0)
        assert _scoreboard_passed(total, matched, mismatched)

    def test_mismatch_is_a_failure(self):
        total, matched, mismatched = _parse_scoreboard_report(
            _report(expected=12, actual=12, matches=11, mismatches=1,
                    missing=0, extra=0))
        assert (total, matched, mismatched) == (12, 11, 1)
        assert not _scoreboard_passed(total, matched, mismatched)

    def test_missing_counts_as_a_failure(self):
        """**这条是这次修复的核心**：expected 侧少给了几条 —— mismatch 仍是 0，
        但比对并没有全对上。只数 mismatch 会把它读成满分。"""
        total, matched, mismatched = _parse_scoreboard_report(
            _report(expected=12, actual=9, matches=9, mismatches=0,
                    missing=3, extra=0))
        assert mismatched == 3, "missing 必须计入失败数"
        assert not _scoreboard_passed(total, matched, mismatched)

    def test_extra_counts_as_a_failure(self):
        total, matched, mismatched = _parse_scoreboard_report(
            _report(expected=9, actual=12, matches=9, mismatches=0,
                    missing=0, extra=3))
        assert mismatched == 3, "extra 必须计入失败数"
        assert not _scoreboard_passed(total, matched, mismatched)

    def test_nothing_compared_is_not_a_pass(self):
        """一条都没比过 ≠ 零 mismatch 的满分。"""
        total, matched, mismatched = _parse_scoreboard_report(
            _report(expected=0, actual=0, matches=0, mismatches=0,
                    missing=0, extra=0))
        assert (total, matched, mismatched) == (0, 0, 0)
        assert not _scoreboard_passed(total, matched, mismatched)

    def test_total_takes_the_larger_side(self):
        """expected/actual 不等时，拿大者当分母 —— 别把"实际比过更多"藏掉。"""
        total, _, _ = _parse_scoreboard_report(
            _report(expected=4, actual=7, matches=4, mismatches=0,
                    missing=0, extra=3))
        assert total == 7


class TestStillAcceptsTheLegacyShape:
    """老形状照旧认 —— 外部/自定义 scoreboard 可能按那句打。"""

    def test_legacy_line(self):
        out = "some log\nScoreboard: total=20 matched=20 mismatched=0\ndone\n"
        assert _parse_scoreboard_report(out) == (20, 20, 0)
        assert _scoreboard_passed(20, 20, 0)

    def test_legacy_failure(self):
        out = "Scoreboard: total=20 matched=18 mismatched=2\n"
        assert _parse_scoreboard_report(out) == (20, 18, 2)


class TestHonestWhenThereIsNothingToParse:
    def test_no_report_at_all(self):
        """仿真崩了 / 用例根本没接 scoreboard → None（调用方据此说"没有报告"，
        而不是假装比对失败）。"""
        assert _parse_scoreboard_report("UVM_FATAL [TEST] boom\n") is None

    def test_partial_block_without_matches_is_none(self):
        """块残缺到没有 Matches 行 → 不猜，给 None。"""
        assert _parse_scoreboard_report(
            "  Expected items : 5\n  Actual items   : 5\n") is None

    def test_mismatches_label_does_not_satisfy_the_matches_label(self):
        """`Mismatches` 里含 `matches` 子串 —— 行首锚定保证它不会被当成 `Matches`。"""
        out = ("  Expected items : 5\n  Actual items   : 5\n"
               "  Mismatches     : 2\n  Missing        : 0\n  Extra          : 0\n")
        assert _parse_scoreboard_report(out) is None
