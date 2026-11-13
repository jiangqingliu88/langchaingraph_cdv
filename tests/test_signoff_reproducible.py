"""签核结论可复现 —— 证据包里的判定必须能从同一份证据重新算出来。

这防的是“audit 逻辑改了，但 report / manifest 没重新生成”的漂移：
pytest 里直接调用 Tier A 重算，而不是手动跑 `vagent evidence replay`。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.orchestration_plane.l2.evidence.signoff_package import (
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


def test_check_package_summarises_integrity_replay_and_recipe(tmp_path):
    from src.orchestration_plane.l2.evidence.signoff_package import check_package

    root = _run_dir(tmp_path)
    write_package(root, _manifest(root))
    result = check_package(root / "signoff_evidence")
    assert result["available"] is True
    assert result["verify"]["ok"] is True
    assert result["replay"]["ok"] is True
    assert result["recipe"]["schema"] == "signoff_replay_recipe_v2"
    assert result["recipe_issues"] == []


def test_check_package_is_honest_when_package_is_missing(tmp_path):
    from src.orchestration_plane.l2.evidence.signoff_package import check_package

    result = check_package(tmp_path / "no_pkg")
    assert result["available"] is False
    assert "manifest.json" in result["note"]


def test_workbench_binding_points_at_check_package():
    """GUI 的「校验证据包」按钮经绑定表调用 —— 路径写错要在这里红。"""
    from src.workbench.bridge.catalog import by_name
    from src.workbench.loader import resolve

    binding = by_name("evidence.check_package")
    assert binding is not None and binding.pure
    target = resolve(binding.target)
    assert callable(target)


def test_effective_policy_snapshot_is_carried_and_checked(tmp_path):
    root = _run_dir(tmp_path)
    (root / "effective_policy.yaml").write_text(
        "schema: signoff_policy_v1\n"
        "policy_hash: abc123\n"
        "effective:\n"
        "  require_baseline: {value: true, source: default}\n",
        encoding="utf-8")
    manifest = _manifest(root)
    manifest["policy"] = {"policy_hash": "abc123"}
    write_package(root, manifest)
    pkg = root / "signoff_evidence"
    rels = {f["path"] for f in json.loads(
        (pkg / "manifest.json").read_text(encoding="utf-8"))["files"]}
    assert "inputs/effective_policy.yaml" in rels

    result = replay_tier_a(pkg)
    check = next(c for c in result["checks"]
                 if c["check"] == "policy_effective")
    assert check["ok"] is True
    assert "require_baseline" in check["keys"]


def test_round_manifest_is_carried_and_checked(tmp_path):
    root = _run_dir(tmp_path)
    _write(root / "coverage" / "testpoints.json", {
        "testpoints": [{"tp_id": "TP1"}]})
    _write(root / "coverage" / "stimulus_plan.json", {
        "schema": "stimulus_plan_v1", "backend": "generated",
        "sha256": "plan-sha",
        "testpoints": [{"tp_id": "TP1", "kind": "stimulus",
                        "transactions": [{"field": "f", "value": 0}]}],
    })
    entry = {"tp_id": "TP1", "kind": "stimulus",
             "transactions": [{"field": "f", "value": 0}]}
    import hashlib
    entry_sha = hashlib.sha256(json.dumps(
        entry, ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    _write(root / "coverage" / "round_manifest.json", {
        "schema": "round_manifest_v1", "query_contract": "round_facts_v1",
        "rounds": [{"round": 1, "facts": [{
            "round": 1, "backend": "generated", "test_name": "t_a",
            "tp_id": "TP1", "kind": "stimulus", "status": "HIT",
            "plan_sha256": "plan-sha", "entry_sha256": entry_sha,
            "playback_log_sha256": "x", "pass_criteria": "mismatched=0",
        }]}],
    })
    write_package(root, _manifest(root))
    pkg = root / "signoff_evidence"
    result = replay_tier_a(pkg)
    check = next(c for c in result["checks"] if c["check"] == "round_manifest")
    assert check["ok"] is True and check["facts"] == 1
