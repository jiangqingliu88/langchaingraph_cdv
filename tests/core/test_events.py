from __future__ import annotations

import json
import threading

from src.core.runtime.events import (
    EventStore, Spool, emit, flush_spool, set_active_store,
)


def test_append_read_and_seq(tmp_path):
    store = EventStore(tmp_path, run_id="r1")
    a = store.append("run.started", status="running", source="journal",
                     payload={"x": 1})
    b = store.append("stage.finished", round=2, stage="ops", source="journal")
    assert a["seq"] == 1 and b["seq"] == 2
    rows = store.read()
    assert len(rows) == 2
    assert rows[1]["stage"] == "ops"


def test_reopen_continues_seq_and_dedup(tmp_path):
    first = EventStore(tmp_path, run_id="r1")
    first.append("run.started")
    first.append("decision.evaluated", dedup_key="d1")
    second = EventStore(tmp_path, run_id="r1")
    assert second.append("decision.evaluated", dedup_key="d1") is None
    event = second.append("run.finished")
    assert event["seq"] == 3


def test_corrupt_line_is_skipped(tmp_path):
    store = EventStore(tmp_path, run_id="r1")
    store.append("run.started")
    with store.path.open("a", encoding="utf-8") as fh:
        fh.write("{not json\n")
    assert len(store.read()) == 1


def test_disabled_store_writes_nothing(tmp_path):
    store = EventStore(tmp_path, run_id="r1", enabled=False)
    assert store.append("run.started") is None
    assert not store.path.exists()


def test_spool_flushes_once(tmp_path):
    spool = Spool()
    spool.emit("round.facts", round=1, dedup_key="r1")
    spool.emit("round.facts", round=1, dedup_key="r1")
    assert len(spool) == 1
    store = EventStore(tmp_path, run_id="r1")
    assert flush_spool(store, spool=spool) == 1
    assert len(store.read("round.facts")) == 1
    assert flush_spool(store, spool=spool) == 0


def test_emit_routes_to_active_store(tmp_path):
    store = EventStore(tmp_path, run_id="r1")
    set_active_store(store)
    try:
        emit("job.started", job_id="j1", source="supervisor")
    finally:
        set_active_store(None)
    assert store.read("job.started")[0]["job_id"] == "j1"


def test_threaded_appends_have_unique_seq(tmp_path):
    store = EventStore(tmp_path, run_id="r1")

    def worker(n):
        for _ in range(5):
            store.append("test", payload={"n": n})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqs = [r["seq"] for r in store.read()]
    assert len(seqs) == 20
    assert seqs == sorted(set(seqs))


def test_payload_is_bounded(tmp_path):
    store = EventStore(tmp_path, run_id="r1")
    store.append("test", payload={"big": list(range(200))})
    payload = store.read("test")[0]["payload"]
    assert payload["big"][-1]["_truncated"] is True
