"""签核策略 schema —— 非法键/值 fail-fast，策略哈希进证据。"""
from __future__ import annotations

import pytest

from src.layers.l2_orchestration.evidence.signoff_package import (
    POLICY_SCHEMA,
    PolicyError,
    load_policy,
)


def _write(tmp_path, text):
    (tmp_path / "signoff_policy.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_valid_policy_passes_strict_and_has_hash(tmp_path):
    _write(tmp_path, (
        f"schema: {POLICY_SCHEMA}\n"
        "module: dut\n"
        "require_baseline: true\n"
        "reward_weights: {compile: 1, regression: 1, coverage: 2}\n"
    ))
    policy, source = load_policy(tmp_path, "dut", strict=True)
    assert source.endswith("signoff_policy.yaml")
    assert policy["issues"] == []
    assert policy["schema"] == POLICY_SCHEMA
    assert len(policy["policy_hash"]) == 64


def test_unknown_key_fails_strict(tmp_path):
    _write(tmp_path, "require_basline: true\n")   # 拼写错误
    with pytest.raises(PolicyError, match="未知策略键"):
        load_policy(tmp_path, "dut", strict=True)
    policy, _ = load_policy(tmp_path, "dut")
    assert any("未知策略键" in i for i in policy["issues"])


def test_bad_values_fail_strict(tmp_path):
    _write(tmp_path, "require_baseline: yes-please\n")
    with pytest.raises(PolicyError, match="require_baseline"):
        load_policy(tmp_path, "dut", strict=True)


def test_accepted_caveat_requires_approver_and_reason(tmp_path):
    _write(tmp_path, (
        "accepted_caveats:\n"
        "  TP_MISSED: {accepted: true}\n"
    ))
    with pytest.raises(PolicyError, match="approver"):
        load_policy(tmp_path, "dut", strict=True)


def test_bad_reward_weights_fail_strict(tmp_path):
    _write(tmp_path, (
        "reward_weights: {compile: -1, regression: 1, coverage: 1}\n"
    ))
    with pytest.raises(PolicyError, match="非负"):
        load_policy(tmp_path, "dut", strict=True)


def test_policy_hash_is_stable_for_same_content(tmp_path):
    _write(tmp_path, "require_baseline: true\n")
    a, _ = load_policy(tmp_path, "dut", strict=True)
    b, _ = load_policy(tmp_path, "dut", strict=True)
    assert a["policy_hash"] == b["policy_hash"]


def test_module_policy_inherits_global_defaults(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    _write(tmp_path, "require_ref_model: true\n")
    policy, _ = load_policy(tmp_path, "dut", project_root=root, strict=True)
    assert policy["require_ref_model"] is True
    assert policy["require_baseline"] is True       # 来自 _default.yaml
    assert policy["effective"]["require_ref_model"]["source"] == "module"
    assert policy["effective"]["require_baseline"]["source"] == "default"


def test_module_policy_overrides_global_default(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    _write(tmp_path, "require_baseline: false\n")
    policy, _ = load_policy(tmp_path, "dut", project_root=root, strict=True)
    assert policy["require_baseline"] is False
