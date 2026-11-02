"""话题 payload 契约 —— 新载荷是 dataclass/dict，旧载荷是 run_id 字符串。"""
from __future__ import annotations

from .. import topics
from ..bus import EventBus


def test_run_id_of_accepts_all_three_shapes():
    ev = topics.RunSelected("r1", run_kind="soc")
    assert topics.run_id_of("r1") == "r1"            # 旧载荷
    assert topics.run_id_of({"run_id": "r1"}) == "r1"
    assert topics.run_id_of(ev) == "r1"
    assert topics.run_id_of(None) == ""
    assert topics.run_id_of({"other": 1}) == ""


def test_to_payload_is_dict():
    assert topics.to_payload(topics.RunSelected("r1")) == {
        "run_id": "r1", "run_kind": "", "project_root": "", "run_path": ""}
    assert topics.to_payload({"a": 1}) == {"a": 1}


def test_bus_publishes_the_contract_shape():
    bus = EventBus()
    seen = []
    bus.subscribe(topics.TOPIC_RUN_SELECTED, seen.append)

    bus.publish_run_selected("r1", run_kind="ip")

    assert seen == [{"run_id": "r1", "run_kind": "ip",
                     "project_root": "", "run_path": ""}]
    assert topics.run_id_of(seen[0]) == "r1"


def test_task_topics_are_declared():
    for name in ("TOPIC_TASK_STARTED", "TOPIC_TASK_COMPLETED",
                 "TOPIC_EVIDENCE_UPDATED", "TOPIC_DECISION_UPDATED",
                 "TOPIC_RUN_COMPLETED"):
        assert isinstance(getattr(topics, name), str)
