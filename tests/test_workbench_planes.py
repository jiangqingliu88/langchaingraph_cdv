"""Workbench 与 Architecture 4.0 的 8 平面对齐。"""
from __future__ import annotations

import yaml

from src.workbench.api.architecture_service import (
    INTERFACE_DIR, PLANES, snapshot,
)
from src.workbench.spec import WorkbenchManifest


def test_exactly_eight_responsibility_planes():
    assert [p.key for p in PLANES] == [
        "Agent", "Orchestration", "Generation", "Engine",
        "IR", "Knowledge", "Experience", "Runtime",
    ]
    assert all(p.dir.endswith("_plane") for p in PLANES)


def test_every_plane_directory_exists():
    data = snapshot()
    assert all(p["exists"] for p in data["planes"]), data["planes"]
    assert data["workbench"]["dir"] == INTERFACE_DIR


def test_snapshot_reports_guard_status():
    data = snapshot()
    assert data["guard"]["version"] == "2.1"
    assert "ok" in data["guard"]
    assert isinstance(data["guard"]["import_issues"], list)


def test_manifest_registers_architecture_module():
    doc = yaml.safe_load(open("config/workbench.yaml", encoding="utf-8"))
    manifest = WorkbenchManifest(**doc)
    groups = {g.id for g in manifest.groups}
    modules = {m.id: m for m in manifest.modules}
    assert "architecture" in groups
    assert modules["architecture.planes"].factory == (
        "src.workbench.modules.architecture.module:ArchitecturePlaneModule")
