"""Workspace 三个区的隔离与差异：写只在 staging，main 只读。"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.workspace import WorkspaceError, WorkspaceZones


def _baseline(tmp_path: Path) -> Path:
    src = tmp_path / "baseline"
    (src / "rtl").mkdir(parents=True)
    (src / "rtl" / "a.sv").write_text("module a; endmodule\n", encoding="utf-8")
    (src / "rtl" / "b.sv").write_text("module b; endmodule\n", encoding="utf-8")
    return src


def _zones(tmp_path: Path) -> WorkspaceZones:
    return WorkspaceZones.init(tmp_path / "ws", _baseline(tmp_path))


def test_init_copies_main_and_staging(tmp_path):
    zones = _zones(tmp_path)
    for name in ("main", "staging", "proposals", "gate"):
        assert (zones.root / name).is_dir()
    assert (zones.main / "rtl" / "a.sv").is_file()
    assert (zones.staging / "rtl" / "a.sv").is_file()
    assert zones.fingerprint("main") == zones.fingerprint("staging")


def test_writes_only_reach_staging(tmp_path):
    zones = _zones(tmp_path)
    zones.write_staging("rtl/a.sv", "module a; // changed\nendmodule\n")
    assert "changed" in zones.read("rtl/a.sv", zone="staging")
    assert "changed" not in zones.read("rtl/a.sv", zone="main")
    assert any(row["path"] == "staging/rtl/a.sv"
               for row in zones.changed_files())


@pytest.mark.parametrize("bad", ["../escape.sv", "/abs.sv", "C:/abs.sv"])
def test_path_traversal_is_rejected(tmp_path, bad):
    zones = _zones(tmp_path)
    with pytest.raises(WorkspaceError):
        zones.write_staging(bad, "x")


def test_zone_prefix_cannot_cross(tmp_path):
    zones = _zones(tmp_path)
    with pytest.raises(WorkspaceError):
        zones.zone_path("main/rtl/a.sv", "staging")
    assert zones.zone_path("staging/rtl/a.sv", "staging").is_file()


def test_changed_files_cover_add_modify_delete(tmp_path):
    zones = _zones(tmp_path)
    zones.write_staging("rtl/a.sv", "module a; // modified\nendmodule\n")
    zones.delete_staging("rtl/b.sv")
    zones.write_staging("rtl/c.sv", "module c; endmodule\n")

    rows = {row["path"]: row["action"] for row in zones.changed_files()}
    assert rows == {"staging/rtl/a.sv": "modify",
                    "staging/rtl/b.sv": "delete",
                    "staging/rtl/c.sv": "add"}


def test_reset_staging_discards_changes(tmp_path):
    zones = _zones(tmp_path)
    zones.write_staging("rtl/a.sv", "changed\n")
    zones.reset_staging()
    assert "changed" not in zones.read("rtl/a.sv", zone="staging")
    assert zones.changed_files() == []
