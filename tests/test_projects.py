"""项目登记表 —— 「切到哪个芯片项目 / 哪套验证环境」。

**"项目"就是一个工作目录**：产物（`output/`）与记忆（`.signoffai/*.db`）都是
相对进程工作目录解析的，换目录两者天然互不可见 —— 隔离不用新造机制。

切项目**要重启**（不是热切换）：Settings / RunService / 各 L4 记忆库的单例句柄
都绑在启动时的 cwd 上，热切等于把它们全重建一遍。所以这里只做三件事：
登记、解析、给出"用哪个目录跑什么命令"。
"""
from __future__ import annotations

import textwrap

import pytest

from src.workbench import projects


@pytest.fixture()
def registry(tmp_path, monkeypatch):
    """一张临时登记表 —— 走 `SIGNOFFAI_PROJECTS` 环境变量，不碰用户级那份。"""
    def write(text: str) -> None:
        p = tmp_path / "projects.yaml"
        p.write_text(textwrap.dedent(text), encoding="utf-8")
        monkeypatch.setenv(projects.REGISTRY_ENV, str(p))

    return write


class TestLoad:

    def test_reads_entries(self, registry, tmp_path):
        root = tmp_path / "apb_uart"
        root.mkdir()
        registry(f"""
            projects:
              - {{id: apb_uart, name: APB-UART, root: {root.as_posix()}}}
              - {{id: m100, name: M100, root: {tmp_path.as_posix()}, manifest: cfg/w.yaml}}
        """)
        items = projects.load_projects()
        assert [p.id for p in items] == ["apb_uart", "m100"]
        assert items[0].exists is True
        assert items[1].manifest_path is None      # 那份清单不存在 → None，不是假路径

    def test_missing_registry_is_not_an_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv(projects.REGISTRY_ENV, str(tmp_path / "nope.yaml"))
        assert projects.load_projects() == []

    def test_broken_registry_is_not_an_error(self, registry):
        registry("projects: [这不是一个条目, {name: 缺 id}]\n")
        assert projects.load_projects() == []      # 写错一行不该让整表失效

    def test_entry_without_root_is_skipped(self, registry):
        registry("projects: [{id: x}]\n")
        assert projects.load_projects() == []


class TestFindAndCurrent:

    def test_find_by_id(self, registry, tmp_path):
        registry(f"projects: [{{id: a, root: {tmp_path.as_posix()}}}]\n")
        assert projects.find("a").id == "a"
        assert projects.find("b") is None

    def test_current_matches_the_working_directory(self, registry, tmp_path):
        root = tmp_path / "proj"
        root.mkdir()
        registry(f"projects: [{{id: a, root: {root.as_posix()}}}]\n")
        assert projects.current(root).id == "a"

    def test_unregistered_directory_is_not_a_project(self, registry, tmp_path):
        """**没登记 ≠ 没项目** —— 很多人就在仓库目录里跑。返回 None 而不是编一个。"""
        registry(f"projects: [{{id: a, root: {(tmp_path / 'other').as_posix()}}}]\n")
        assert projects.current(tmp_path) is None


class TestRelaunch:

    def test_command_runs_in_that_root_with_its_manifest(self, registry, tmp_path):
        root = tmp_path / "proj"
        (root / "config").mkdir(parents=True)
        (root / "config" / "workbench.yaml").write_text("version: 1\n", encoding="utf-8")
        registry(f"projects: [{{id: a, root: {root.as_posix()}}}]\n")

        project = projects.find("a")
        argv = projects.relaunch_command(project)
        assert argv[1:3] == ["-m", "src.workbench"]
        assert argv[-1] == str(root / "config" / "workbench.yaml")

    def test_command_omits_the_manifest_when_there_is_none(self, registry, tmp_path):
        root = tmp_path / "bare"
        root.mkdir()
        registry(f"projects: [{{id: a, root: {root.as_posix()}}}]\n")
        assert projects.relaunch_command(projects.find("a"))[1:] == ["-m", "src.workbench"]
