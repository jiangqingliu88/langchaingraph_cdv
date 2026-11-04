"""一次运行的**总覆盖率** —— 数字 + 合并库 + 报告在哪。

「逐条用例的覆盖率」和「整个环境的覆盖率」是两件事，这是后者。人对不上账时两边
都要看：「每条都挺高、总的就是上不去」和「某一条特别低」是完全不同的结论。

三件容易搞错的事：

  · **没有数据 ≠ 0**。覆盖率阶段还没跑到（或收集中断）时 `coverage_result.json`
    根本不存在 —— 那时给 `None` 并**说清原因**，不能报 0.0%。报 0 会被读成
    "覆盖率很差"，而事实是"还没测"。
  · **报告优先用覆盖率阶段留下的那份**（`reports/index.html`）：它已经在了、
    就是当时 agent 看的那一份。只有它不在才现生成（那是分钟级里的一次性代价）。
  · 文件只报**事实**（在不在/多大/什么时候写的）—— 解析与出报告是
    `coverage_tools` 的事，这里不重跑。
"""
from __future__ import annotations

import json

from src.app.services.flow.api import run_coverage


def _run(tmp_path, coverage=None, *, db=True, report=True):
    run = tmp_path / "run_x"
    cov = run / "sim" / "coverage"
    cov.mkdir(parents=True)
    if coverage is not None:
        (cov / "coverage_result.json").write_text(
            json.dumps({"coverage": coverage}), encoding="utf-8")
    if db:
        (cov / "merged.ucdb").write_bytes(b"m" * 2048)
    if report:
        (cov / "reports").mkdir()
        (cov / "reports" / "index.html").write_text("<html></html>", encoding="utf-8")
    return run


class TestNumbers:

    def test_reads_overall_and_functional(self, tmp_path):
        run = _run(tmp_path, {"overall_pct": 89.2, "functional_pct": 51.72})
        out = run_coverage(str(run))
        assert out["overall"] == 89.2 and out["functional"] == 51.72

    def test_lists_the_per_type_fields(self, tmp_path):
        """分项也要列出来 —— "总覆盖率上不去"到底是哪一项拖的，这才是要看的。"""
        run = _run(tmp_path, {"overall_pct": 89.2, "branch_pct": 87.5,
                              "statement_pct": 90.9})
        fields = {f["key"]: f["pct"] for f in run_coverage(str(run))["fields"]}
        assert fields["branch_pct"] == 87.5 and fields["statement_pct"] == 90.9
        assert fields["overall_pct"] == 89.2

    def test_missing_data_is_none_not_zero(self, tmp_path):
        """**没数据不是 0** —— 报 0 会被读成"覆盖率很差"，事实是"还没测"。"""
        run = _run(tmp_path, None)                # 不写 coverage_result.json
        out = run_coverage(str(run))
        assert out["overall"] is None
        assert any("不是 0" in n for n in out["notes"])

    def test_notes_when_the_agent_report_is_missing(self, tmp_path):
        """有库没报告 → 打开时要现生成，先把话说在前面。"""
        run = _run(tmp_path, {"overall_pct": 50.0}, report=False)
        out = run_coverage(str(run))
        assert out["report"]["exists"] is False
        assert any("现生成" in n for n in out["notes"])

    def test_error_when_the_run_dir_is_missing(self, tmp_path):
        out = run_coverage(str(tmp_path / "nope"))
        assert out.get("error")


class TestFiles:

    def test_reports_the_merged_db_and_the_report(self, tmp_path):
        run = _run(tmp_path, {"overall_pct": 89.2})
        out = run_coverage(str(run))
        assert out["db"]["exists"] and out["db"]["path"].endswith("merged.ucdb")
        assert out["db"]["kb"] == 2.0
        assert out["report"]["exists"]
        assert out["report"]["path"].endswith("index.html")

    def test_no_artifacts_at_all(self, tmp_path):
        run = _run(tmp_path, None, db=False, report=False)
        out = run_coverage(str(run))
        assert out["db"]["exists"] is False and out["report"]["exists"] is False
        assert any("没有合并覆盖率库" in n for n in out["notes"])
