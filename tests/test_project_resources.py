"""项目只读资源：RTL/验证/覆盖率/环境/spec/模型可读；密钥不可读；写仍在 staging。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.workspace import WorkspaceZones
from src.workspace.harness import Harness, HarnessConfig
from src.workspace.resources import ProjectResources


def _project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    files = {
        "rtl/a.sv": "module a; endmodule\n",
        "tb/a_tb.sv": "module a_tb; endmodule\n",
        "sv/agents/foo/foo_agent.sv": "class foo_agent; endclass\n",
        "coverage/cov.json": '{"functional_pct": 63}\n',
        "config/workbench.yaml": "window: {}\n",
        "specs/x.md": "# spec\n",
        "model/m.sc": "int sc_main() { return 0; }\n",
        ".env": "LLM_API_KEY=secret\n",
        ".jwt_secret": "secret\n",
        "venv/lib.py": "x = 1\n",
    }
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    (root / "coverage" / "done.ucdb").write_bytes(b"\x00binary")
    return root


def test_inventory_and_classification(tmp_path):
    project = _project(tmp_path)
    resources = ProjectResources(project)
    inventory = resources.inventory()
    assert inventory["kinds"]["rtl"] >= 1
    assert inventory["kinds"]["verification"] >= 2
    assert inventory["kinds"]["coverage"] >= 2
    assert inventory["kinds"]["env"] >= 1
    assert inventory["kinds"]["spec"] >= 1
    assert inventory["kinds"]["model"] >= 1
    paths = {item["path"] for item in inventory["items"]}
    assert not any(path.startswith((".env", ".jwt_secret", "venv/"))
                   for path in paths)


def test_read_text_binary_and_secret_guard(tmp_path):
    project = _project(tmp_path)
    resources = ProjectResources(project)
    text = resources.read("rtl/a.sv")
    assert text["binary"] is False and "module a" in text["content"]
    binary = resources.read("coverage/done.ucdb")
    assert binary["binary"] is True and "content" not in binary
    with pytest.raises(ValueError):
        resources.read(".env")
    with pytest.raises(ValueError):
        resources.read("../escape.sv")


def test_search_by_kind(tmp_path):
    project = _project(tmp_path)
    resources = ProjectResources(project)
    hits = resources.search("module", kind="rtl")
    assert hits and all(hit["path"].startswith("rtl/") for hit in hits)


def test_workspace_remembers_project_root(tmp_path):
    project = _project(tmp_path)
    zones = WorkspaceZones.init(tmp_path / "ws", project / "rtl",
                                project_root=project)
    assert zones.project_root() == project.resolve()
    assert (zones.staging / "a.sv").is_file()


def test_workspace_discovers_project_root_from_baseline(tmp_path):
    project = _project(tmp_path)
    (project / ".git").mkdir()
    zones = WorkspaceZones.init(tmp_path / "ws", project / "rtl")
    assert zones.project_root() == project.resolve()


def test_harness_reads_project_but_writes_only_staging(tmp_path):
    project = _project(tmp_path)
    zones = WorkspaceZones.init(tmp_path / "ws", project / "rtl",
                                project_root=project)
    decisions = [
        {"tool": "read_project_file", "args": {"path": "rtl/a.sv"}},
        {"tool": "write_file",
         "args": {"path": "staging/a.sv", "content": "module a; // fixed\n"}},
        {"tool": "run_shell",
         "args": {"command": [sys.executable, "-c", "print('ok')"]}},
        {"tool": "propose",
         "args": {"before": "module a", "after": "fixed",
                  "reasoning_trace": "读了项目 RTL 后修改 staging",
                  "open_questions": []}},
    ]
    queue = list(decisions)
    harness = Harness(zones, config=HarnessConfig(project_root=str(project)),
                      planner=lambda payload: queue.pop(0))
    result = harness.run("修一下 a.sv")
    assert result["status"] == "proposal"
    read_messages = [m for m in harness.session.messages
                     if m.get("name") == "read_project_file"]
    assert read_messages and "module a" in str(read_messages[0]["content"])
    assert (project / "rtl" / "a.sv").read_text(encoding="utf-8") == \
        "module a; endmodule\n"
    assert (zones.staging / "a.sv").read_text(encoding="utf-8").startswith(
        "module a; // fixed")
