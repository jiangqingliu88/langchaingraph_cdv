"""直接模式：原地读写 + 敏感路径/越界防护。"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from src.runtime_plane.workspace_manager import WorkspaceError, WorkspaceZones


def test_direct_mode_writes_project_root_and_hides_secrets(tmp_path):
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    zones = WorkspaceZones.direct_mode(tmp_path)

    target = zones.write_staging("rtl/a.sv", "module a; endmodule\n")
    assert target == tmp_path / "rtl" / "a.sv"
    assert target.read_text(encoding="utf-8").startswith("module a")

    for rel in (".env", ".git/config", "../outside.txt"):
        with pytest.raises(WorkspaceError):
            zones.staging_path(rel)

    assert zones.workdir == tmp_path
    assert zones.harness_dir == tmp_path / ".signoffai"
    assert (tmp_path / ".signoffai" / "sessions").is_dir()


def test_direct_mode_reset_staging_is_refused(tmp_path):
    zones = WorkspaceZones.direct_mode(tmp_path)
    with pytest.raises(WorkspaceError):
        zones.reset_staging()


def test_direct_mode_git_diff_reports_changes(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git 不可用")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.sv").write_text("module t; endmodule\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.sv"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=a@b", "-c", "user.name=a",
                    "commit", "-qm", "init"], cwd=tmp_path, check=True)
    (tmp_path / "tracked.sv").write_text("module t; endmodule // x\n",
                                         encoding="utf-8")
    (tmp_path / "new.sv").write_text("module n; endmodule\n", encoding="utf-8")

    rows = {row["path"]: row["action"] for row in WorkspaceZones.direct_mode(tmp_path).changed_files()}
    assert rows.get("tracked.sv") == "modify"
    assert rows.get("new.sv") == "add"
