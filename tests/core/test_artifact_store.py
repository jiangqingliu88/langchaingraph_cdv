from __future__ import annotations

import hashlib
import json

from src.runtime_plane.core.runtime.artifacts import ArtifactStore, sha256_file
from src.runtime_plane.core.runtime.events import EventStore


def test_register_hashes_in_place(tmp_path):
    src = tmp_path / "rtl" / "dut.sv"
    src.parent.mkdir()
    src.write_text("module dut; endmodule\n", encoding="utf-8")
    store = ArtifactStore(tmp_path, run_id="r1")
    ref = store.register("rtl", src, producer="design")
    assert ref.sha256 == hashlib.sha256(src.read_bytes()).hexdigest()
    assert ref.path == "rtl/dut.sv"
    assert ref.state == "present"
    assert ref.content_addressed is False


def test_put_uses_content_addressed_copy(tmp_path):
    src = tmp_path / "q.json"
    src.write_text('{"ok": true}', encoding="utf-8")
    store = ArtifactStore(tmp_path, run_id="r1")
    ref = store.put("quality", src, producer="audit")
    assert ref.content_addressed is True
    assert ref.path.startswith("artifacts/cas/")
    assert (tmp_path / ref.path).read_text(encoding="utf-8") == '{"ok": true}'
    # 同一内容再次 put 复用同一个对象
    again = store.put("quality", src, producer="audit")
    assert again.sha256 == ref.sha256
    assert len(store.all("quality")) == 1


def test_missing_source_is_recorded_not_raised(tmp_path):
    store = ArtifactStore(tmp_path, run_id="r1")
    ref = store.register("missing", tmp_path / "nope.txt")
    assert ref.state == "missing"
    assert ref.sha256 == ""


def test_index_persists_and_reloads(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("a", encoding="utf-8")
    store = ArtifactStore(tmp_path, run_id="r1")
    ref = store.register("spec", src)
    idx = json.loads((tmp_path / "artifacts" / "artifacts.json").read_text(encoding="utf-8"))
    assert idx["schema"] == "artifact_index_v1"
    assert idx["artifacts"][0]["sha256"] == ref.sha256
    again = ArtifactStore(tmp_path, run_id="r1")
    assert again.latest("spec").sha256 == ref.sha256
    assert again.get(ref.sha256).kind == "spec"


def test_same_path_new_content_is_a_new_version(tmp_path):
    src = tmp_path / "a.txt"
    store = ArtifactStore(tmp_path, run_id="r1")
    src.write_text("v1", encoding="utf-8")
    first = store.register("spec", src)
    src.write_text("v2", encoding="utf-8")
    second = store.register("spec", src)
    assert first.sha256 != second.sha256
    assert len(store.all("spec")) == 2


def test_artifact_produced_event_is_emitted_once(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("a", encoding="utf-8")
    events = EventStore(tmp_path, run_id="r1")
    store = ArtifactStore(tmp_path, run_id="r1", event_store=events)
    ref = store.register("spec", src)
    store.register("spec", src)
    produced = events.read("artifact.produced")
    assert len(produced) == 1
    assert produced[0]["payload"]["artifact_id"] == ref.artifact_id


def test_sha256_file_missing_returns_empty(tmp_path):
    assert sha256_file(tmp_path / "none") == ""
