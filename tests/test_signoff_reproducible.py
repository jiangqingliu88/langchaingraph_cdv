"""签核结论可复现 —— 证据包里的判定必须能从同一份证据重新算出来。

这防的是“audit 逻辑改了，但 report / manifest 没重新生成”的漂移：
pytest 里直接调用 Tier A 重算，而不是手动跑 `vagent evidence replay`。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.layers.l2_orchestration.evidence.signoff_package import (
    load_recipe,
    replay_tier_a,
    validate_recipe,
    write_package,
)


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "run_pkg"
    _write(root / "coverage" / "tp_matrix.json", {
        "rows": [], "total": 10,
        "counts": {"HIT": 10, "MISS": 0, "OBSERVED": 0, "UNOBSERVED": 0,
                   "BACKDOOR_HIT": 0, "BACKDOOR_MISS": 0, "UNMAPPED": 0},
    })
    _write(root / "sim" / "coverage" / "coverage_result.json", {
        "plan_coverage": {"functional_pct": 95.0, "overall_pct": 70.0},
    })
    _write(root / "signoff_evidence.json", {"schema": "signoff_evidence_v1"})
    _write(root / "report.json", {"verdict": "READY", "caveats": []})
    return root


def _manifest(root: Path):
    return {
        "run": root.name,
        "coverage": {"plan_pct": 95.0, "single_test_pct": 60.0},
        "tp_matrix": {"counts": {
            "HIT": 10, "MISS": 0, "OBSERVED": 0, "UNOBSERVED": 0,
            "BACKDOOR_HIT": 0, "BACKDOOR_MISS": 0, "UNMAPPED": 0,
        }, "total": 10},
        "verdict": {"hard_ok": True, "raw_caveats": [],
                    "accepted_codes": [], "effective_codes": [],
                    "verdict": "READY"},
        "seeds": [1, 2],
    }


def test_tier_a_recomputes_the_recorded_verdict(tmp_path):
    root = _run_dir(tmp_path)
    write_package(root, _manifest(root))
    pkg = root / "signoff_evidence"

    result = replay_tier_a(pkg)
    assert result["ok"] is True
    assert result["recorded_verdict"] == result["recomputed_verdict"] == "READY"
    assert {c["check"] for c in result["checks"]} == {
        "tp_matrix_counts", "plan_coverage_pct"}
    assert all(c["ok"] for c in result["checks"])

    # report.json 是 audit 的对外结论，必须与重算一致
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    assert report["verdict"] == result["recomputed_verdict"]


def test_evidence_drift_is_detected(tmp_path):
    """只改包里的 TP 矩阵、不改 manifest → 回放必须拒绝。"""
    root = _run_dir(tmp_path)
    write_package(root, _manifest(root))
    pkg = root / "signoff_evidence"
    tp_path = pkg / "execution" / "coverage" / "tp_matrix.json"
    doc = json.loads(tp_path.read_text(encoding="utf-8"))
    doc["counts"] = {**doc["counts"], "HIT": 9, "MISS": 1}
    _write(tp_path, doc)

    result = replay_tier_a(pkg)
    assert result["ok"] is False
    assert result["integrity"]["ok"] is False          # 文件哈希对不上
    counts_check = next(c for c in result["checks"]
                        if c["check"] == "tp_matrix_counts")
    assert counts_check["ok"] is False


def test_recipe_is_structured_and_schema_valid(tmp_path):
    root = _run_dir(tmp_path)
    write_package(root, _manifest(root))
    recipe = load_recipe(root / "signoff_evidence")

    assert validate_recipe(recipe) == []
    assert recipe["schema"] == "signoff_replay_recipe_v2"
    assert recipe["tier_a"]["requires_eda"] is False
    assert recipe["tier_a"]["command"].endswith("replay.py")
    assert recipe["tier_b"]["requires_eda"] is True
    assert recipe["tier_b"]["eda_tools"] == ["vsim", "vcover"]
    assert [s["name"] for s in recipe["tier_b"]["steps"]] == [
        "regression", "coverage_merge"]
    assert recipe["seeds"] == [1, 2]


def test_recipe_validation_names_missing_fields():
    issues = validate_recipe({"schema": "v1", "tier_a": "python x",
                              "tier_b": {"requires_eda": False}})
    joined = " ".join(issues)
    assert "schema" in joined
    assert "tier_a" in joined
    assert "tier_b.requires_eda" in joined
