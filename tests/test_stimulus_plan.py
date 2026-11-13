"""StimulusPlan IR —— 两个后端的公共前置层，且 player 不装成“已可用”。

约束（第一版）：
  · generated 接受 stimulus/sequence/backdoor；observe 进 unsupported；
  · player 只接受 stimulus/sequence 且单 agent；runtime 未实现 → 显式报错；
  · 同输入同 sha256；plan 落盘可回读。
"""
from __future__ import annotations

import json

import pytest

from src.ir.vplan.runtime.framework.stimulus_plan import (
    BACKENDS,
    DEFAULT_BACKEND,
    StimulusBackendError,
    build_and_write,
    build_stimulus_plan,
    ensure_backend_executable,
    load_stimulus_plan,
    plan_digest,
)


TPS = [
    {"tp_id": "TP-S", "realization": {"kind": "stimulus", "agent": "a",
                                      "field": "instr_type", "value": 0},
     "execution": {"test": "t_s", "stage": "p0"}},
    {"tp_id": "TP-Q", "realization": {"kind": "sequence", "agent": "a",
                                      "values": [0, 0, 3], "sequence": "s"},
     "execution": {"test": "t_q", "stage": "p1"}},
    {"tp_id": "TP-B", "realization": {"kind": "backdoor", "value": 2,
                                      "path": "tb.u.queue"},
     "execution": {"test": "t_b", "stage": "p1"}},
    {"tp_id": "TP-O", "realization": {"kind": "observe"},
     "execution": {"test": "t_o", "stage": "p2"}},
]


def test_generated_backend_plans_all_drivable_kinds():
    plan = build_stimulus_plan(TPS, backend="generated", module="m")
    assert plan["schema"] == "stimulus_plan_v1"
    assert plan["backend"] == DEFAULT_BACKEND == "generated"
    assert [e["tp_id"] for e in plan["testpoints"]] == ["TP-S", "TP-Q", "TP-B"]
    assert [u["tp_id"] for u in plan["unsupported"]] == ["TP-O"]
    seq = next(e for e in plan["testpoints"] if e["tp_id"] == "TP-Q")
    assert [t["value"] for t in seq["transactions"]] == [0, 0, 3]
    assert plan["stats"]["planned"] == 3
    assert plan["sha256"] == plan_digest(plan)


def test_player_backend_is_limited_and_explicitly_not_executable():
    plan = build_stimulus_plan(TPS, backend="player", module="m")
    assert {e["tp_id"] for e in plan["testpoints"]} == {"TP-S", "TP-Q"}
    reasons = {u["tp_id"]: u["reason"] for u in plan["unsupported"]}
    assert "backdoor" in reasons["TP-B"]
    assert "observe" in reasons["TP-O"]
    with pytest.raises(StimulusBackendError, match="runtime"):
        ensure_backend_executable("player")
    assert BACKENDS["player"]["runtime"] is False
    ensure_backend_executable("generated")


def test_player_rejects_multi_agent_plans():
    tps = TPS + [{"tp_id": "TP-Z", "realization": {
        "kind": "stimulus", "agent": "b", "field": "f", "value": 1}}]
    plan = build_stimulus_plan(tps, backend="player")
    assert len({e["agent"] for e in plan["testpoints"]}) == 1
    assert any("单 agent" in u["reason"] for u in plan["unsupported"])


def test_unknown_backend_fails_loudly():
    with pytest.raises(StimulusBackendError, match="未知"):
        build_stimulus_plan(TPS, backend="magic")


def test_plan_digest_is_stable_and_write_roundtrip(tmp_path):
    a = build_stimulus_plan(TPS, backend="generated", module="m", seed=7)
    b = build_stimulus_plan(TPS, backend="generated", module="m", seed=7)
    assert a["sha256"] == b["sha256"]

    summary = build_and_write(TPS, tmp_path, backend="generated",
                              module="m", seed=7)
    assert summary["path"].replace("\\", "/").endswith(
        "coverage/stimulus_plan.json")
    assert summary["sha256"] == a["sha256"]
    assert load_stimulus_plan(tmp_path)["sha256"] == a["sha256"]
    # 落盘字节里的 plan 不依赖绝对路径
    raw = json.loads((tmp_path / "coverage" / "stimulus_plan.json")
                     .read_text(encoding="utf-8"))
    assert raw["backend"] == "generated"
