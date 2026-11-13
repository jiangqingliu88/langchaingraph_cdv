"""`vagent evidence` —— 无 GUI 的那一半。

界面上的「保存」会自动记账；在终端里用编辑器改文件**没有那个钩子**，所以这组
命令不是"顺手也做个 CLI"，而是"没有它，无 GUI 的人根本无法在这条链上留痕"。

三条里 `check` 最要紧：一条只在"你记得记账时才记账"的链，读的人分不清
「没人改」和「改了没记」—— 两者在链上都是一片空白。
"""
from __future__ import annotations

import json
import subprocess

import pytest
from click.testing import CliRunner

from src.workbench.cli.commands import cli


@pytest.fixture
def repo(tmp_path):
    """一个真的 git 仓库 —— 对账拿 `git status` 当改动清单，没有 git 就无从谈起。"""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e"}

    def git(*args):
        return subprocess.run(["git", *args], cwd=str(tmp_path), check=True,
                              capture_output=True, text=True, env={**_os_environ(), **env})

    git("init", "-q", ".")
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "dut.sv").write_text("module dut; endmodule\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "init")
    return tmp_path


def _os_environ():
    import os
    return dict(os.environ)


@pytest.fixture
def runner():
    return CliRunner()


def _run(runner, repo, *args):
    return runner.invoke(cli, ["evidence", *args, "--root", str(repo)])


class TestRecord:
    def test_records_a_file_into_the_project_chain(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // 改了\nendmodule\n",
                                             encoding="utf-8")
        result = _run(runner, repo, "record", "rtl/dut.sv",
                      "-m", "修正握手", "--author", "jiang")
        assert result.exit_code == 0, result.output

        chain = json.loads((repo / ".signoffai" / "human_edits.json")
                           .read_text(encoding="utf-8"))
        assert chain["total_changes"] == 1
        record = chain["records"][0]
        assert record["file_path"] == "rtl/dut.sv"
        assert record["agent"] == "human:jiang"
        assert record["reason"] == "修正握手"

    def test_a_missing_file_is_an_error_exit(self, runner, repo):
        result = _run(runner, repo, "record", "rtl/nope.sv", "-m", "x")
        assert result.exit_code == 1
        assert "不存在" in result.output

    def test_an_empty_reason_is_recorded_not_invented(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // x\nendmodule\n",
                                             encoding="utf-8")
        result = _run(runner, repo, "record", "rtl/dut.sv")
        assert result.exit_code == 0
        chain = json.loads((repo / ".signoffai" / "human_edits.json")
                           .read_text(encoding="utf-8"))
        assert chain["records"][0]["reason"] == "（未填理由）"

    def test_json_output_is_machine_readable(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // y\nendmodule\n",
                                             encoding="utf-8")
        result = _run(runner, repo, "record", "rtl/dut.sv", "-m", "y", "-j")
        payload = json.loads(result.output)
        assert payload["recorded"] is True
        assert payload["seq"] == 0
        assert payload["file"] == "rtl/dut.sv"


class TestCheck:
    """对账 —— 这一组才是这一块存在的理由。"""

    def test_an_unrecorded_change_fails_the_check(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // 偷偷改了\nendmodule\n",
                                             encoding="utf-8")
        result = _run(runner, repo, "check")
        assert result.exit_code == 1, result.output
        assert "rtl/dut.sv" in result.output
        assert "未记账" in result.output

    def test_recording_clears_the_check(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // 改了\nendmodule\n",
                                             encoding="utf-8")
        assert _run(runner, repo, "check").exit_code == 1
        assert _run(runner, repo, "record", "rtl/dut.sv", "-m", "说明").exit_code == 0
        result = _run(runner, repo, "check")
        assert result.exit_code == 0, result.output

    def test_a_clean_tree_passes(self, runner, repo):
        result = _run(runner, repo, "check")
        assert result.exit_code == 0
        assert "改动 0 个文件" in result.output

    def test_editing_again_after_recording_is_flagged(self, runner, repo):
        """记过账不等于**这份内容**记过账 —— 改回原样、再改一次都要重判。

        用的是内容哈希而不是"这个文件有没有记录"：否则第二次修改会拿着第一次的
        记账蒙混过去。
        """
        target = repo / "rtl" / "dut.sv"
        target.write_text("module dut; // 第一次\nendmodule\n", encoding="utf-8")
        _run(runner, repo, "record", "rtl/dut.sv", "-m", "第一次")
        assert _run(runner, repo, "check").exit_code == 0

        target.write_text("module dut; // 第二次\nendmodule\n", encoding="utf-8")
        assert _run(runner, repo, "check").exit_code == 1

    def test_the_chain_file_does_not_reconcile_against_itself(self, runner, repo):
        """链文件自己不能进改动清单 —— 否则每记一笔账，下一轮 check 就报未记账。

        成长目录（`.signoffai/`，含经验库与 `rl_policy.json`）整体排除，它们每次
        运行都在变，不是人工编辑。
        """
        (repo / "rtl" / "dut.sv").write_text("module dut; // z\nendmodule\n",
                                             encoding="utf-8")
        _run(runner, repo, "record", "rtl/dut.sv", "-m", "z")
        result = _run(runner, repo, "check")
        assert result.exit_code == 0, result.output
        assert ".signoffai" not in result.output

    def test_outside_a_git_repo_it_skips_instead_of_failing(
            self, runner, tmp_path, monkeypatch):
        """不在 git 仓库里就没有"改动清单"可比 —— 跳过，不是失败。

        pytest 的 tmp_path 在部分配置下会落在仓库内，`git status` 仍能
        找到父仓库；这里直接模拟“git 不可用/非仓库”的返回值，才测的是
        目标分支，而不是测试临时目录的位置。
        """
        from src.orchestration_plane.l2.evidence import human_edit

        monkeypatch.setattr(human_edit, "_git_changed_files",
                            lambda root, limit=500: None)
        (tmp_path / "a.txt").write_text("x", encoding="utf-8")
        result = _run(runner, tmp_path, "check")
        assert result.exit_code == 0, result.output
        assert "跳过" in result.output


class TestLog:
    def test_shows_the_chain_with_integrity(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // q\nendmodule\n",
                                             encoding="utf-8")
        _run(runner, repo, "record", "rtl/dut.sv", "-m", "说明文字")
        result = _run(runner, repo, "log")
        assert result.exit_code == 0
        assert "rtl/dut.sv" in result.output
        assert "完整性：完整" in result.output

    def test_an_empty_chain_is_not_an_error(self, runner, repo):
        result = _run(runner, repo, "log")
        assert result.exit_code == 0
        assert "还没有人工变更记录" in result.output

    def test_a_broken_chain_is_reported(self, runner, repo):
        (repo / "rtl" / "dut.sv").write_text("module dut; // w\nendmodule\n",
                                             encoding="utf-8")
        _run(runner, repo, "record", "rtl/dut.sv", "-m", "先记一条")
        path = repo / ".signoffai" / "human_edits.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["records"][0]["reason"] = "篡改"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        result = _run(runner, repo, "log")
        assert "已断" in result.output


class TestHelp:
    def test_the_group_documents_itself(self, runner):
        result = runner.invoke(cli, ["evidence", "--help"])
        assert result.exit_code == 0
        for word in ("record", "log", "check"):
            assert word in result.output


class TestArchiveCarriesThePhysicalEvidence:
    """`vagent archive` 要把**结论的物证**一起收进包，且缺了什么要说。

    ## 为什么

    原来白名单只有四个 JSON：`manifest` / `evidence_chain` / `report` /
    `coverage_result`。而 `coverage_result.json` 里那句"覆盖率 93.5%"对应的
    `merged.ucdb`、以及现场波形，**都不在包里** —— 拿到证据包的人只有指纹、
    没有实物，回溯不了"这个数字出自哪一份库"。

    静默跳过同样要不得：包里没有波形，究竟是我漏收了、还是这次本来就没跑波形？
    这两件事长得一模一样，而一件要修、一件要接受。
    """

    def _run_dir(self, tmp_path, name="output_x", with_ucdb=True, with_vcd=True,
                 with_stages=True):
        import json

        d = tmp_path / name
        (d / "docs").mkdir(parents=True)
        (d / "sim" / "coverage").mkdir(parents=True)
        (d / "docs" / "manifest.json").write_text(json.dumps({"run_id": name}),
                                                  encoding="utf-8")
        (d / "sim" / "coverage" / "coverage_result.json").write_text(
            json.dumps({"status": "PASS"}), encoding="utf-8")
        if with_ucdb:
            (d / "sim" / "coverage" / "merged.ucdb").write_bytes(b"ucdb")
        if with_vcd:
            (d / "sim" / "coverage" / "wave_seed_default.vcd").write_bytes(b"$dumpvars")
            (d / "sim" / "coverage" / "wave_seed_42.vcd").write_bytes(b"$dumpvars2")
        if with_stages:
            (d / "regression_stages.json").write_text(json.dumps({"stages": []}),
                                                      encoding="utf-8")
        return d

    def test_the_ucdb_and_every_waveform_land_in_the_zip(self, tmp_path, runner,
                                                          monkeypatch):
        import zipfile

        monkeypatch.chdir(tmp_path)
        self._run_dir(tmp_path)
        result = runner.invoke(cli, ["archive", "--run", "output_x",
                                     "--output", "ev.zip"])
        assert result.exit_code == 0, result.output

        with zipfile.ZipFile(tmp_path / "ev.zip") as zf:
            names = [n.replace("\\", "/") for n in zf.namelist()]
        assert any(n.endswith("merged.ucdb") for n in names), "覆盖率库没进包"
        vcds = [n for n in names if n.endswith(".vcd")]
        assert len(vcds) == 2, f"波形没收全（带种子命名的那些）：{vcds}"
        assert any(n.endswith("regression_stages.json") for n in names)

    def test_what_is_absent_is_reported_not_silently_skipped(self, tmp_path, runner,
                                                             monkeypatch):
        """没有波形时必须**说出来** —— "我漏收了"与"这次没跑"要分得开。"""
        monkeypatch.chdir(tmp_path)
        self._run_dir(tmp_path, with_ucdb=False, with_vcd=False, with_stages=False)
        result = runner.invoke(cli, ["archive", "--run", "output_x",
                                     "--output", "ev.zip"])
        assert result.exit_code == 0, result.output
        assert "merged.ucdb" in result.output
        assert "未打包" in result.output
