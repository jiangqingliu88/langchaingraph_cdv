"""`validate_regress` 必须认得**分级回归**的报告位置。

历史坑：判据只看 `regression_run/report.json`（单级回归才写），而分级回归
（`run_regression_staged`）只写每级 `regression_run/<stage>/` + 根目录
`regression_stages.json`。于是每轮都报 `regression report not found`，
ops 的分一直被压着 —— 一条**永远为假**的红灯。

另一个坑在反方向：停在人工节点时汇总里 `passed=total=4`（只跑了 loopback），
"全过"是假象 —— 必须按"没跑完"报出来。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.layers.l2_orchestration.governance.quality_guard import (
    Verdict, validate_regress,
)


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def test_staged_aggregate_is_recognised(tmp_path):
    """`regression_stages.json`（分级回归汇总）就是这份校验要看的报告。"""
    _write(tmp_path / "regression_stages.json",
           {"status": "PASS", "blocked_at": "", "passed": 273,
            "failed": 0, "unknown": 0, "total": 273, "stages": []})
    result = validate_regress({}, str(tmp_path))
    assert result.verdict is Verdict.PASS, result.issues
    assert result.issues == []


def test_flat_single_stage_report_still_works(tmp_path):
    """不分级的回归（`regression_run/report.json`）不能因为改了判据就丢。"""
    _write(tmp_path / "regression_run" / "report.json",
           {"total": 25, "stats": {"pass": 25, "fail": 0, "unknown": 0}})
    result = validate_regress({}, str(tmp_path))
    assert result.verdict is Verdict.PASS, result.issues


def test_blocked_stage_is_not_a_pass(tmp_path):
    """停在人工节点：只跑了 loopback，`4/4` 不等于"回归全过"。"""
    _write(tmp_path / "regression_stages.json",
           {"status": "WAITING_APPROVAL", "blocked_at": "loopback",
            "passed": 4, "failed": 0, "unknown": 0, "total": 4, "stages": []})
    result = validate_regress({}, str(tmp_path))
    assert result.verdict is Verdict.FALLBACK
    assert any("blocked at loopback" in i for i in result.issues)


def test_failed_stage_is_reported(tmp_path):
    _write(tmp_path / "regression_stages.json",
           {"status": "FAIL", "blocked_at": "", "passed": 9,
            "failed": 3, "unknown": 0, "total": 12, "stages": []})
    result = validate_regress({}, str(tmp_path))
    assert result.verdict is Verdict.FALLBACK
    assert any("9/12" in i for i in result.issues)


def test_no_report_at_all_is_reported(tmp_path):
    result = validate_regress({}, str(tmp_path))
    assert result.verdict is Verdict.FALLBACK
    assert any("not found" in i for i in result.issues)
