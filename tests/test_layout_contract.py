"""运行目录布局契约 —— **同一份目录，写端拼一遍、读端认一遍**。

## 这个文件存在的理由

`regression_run` 的布局曾经散在读写两边各拼一份。分级回归一改成"每级一个子目录"，
写端改对了、读端没跟上 —— GUI 的「回归状态」**整页空白**。

那次没有任何测试变红。因为既有测试各自的夹具**自己造目录、自己读**，
两边在同一个文件里自洽：**夹具怎么造，读端就怎么认** —— 照不出"写端和读端
对布局的理解不一致"这种错位。

所以这里换个造法：目录**按写端的公式造**（`InfrastructureManager` 里那条
`regression_root(output)/<stage>`），再用**真正的读端**（`run_regression_status`）
去认。写端公式改了、读端没跟着改 —— 这里就红。
"""
from __future__ import annotations

import pytest


def _write_run_dir(output_root, *, stages=(), flat=False, shared_case="",
                   artifact_stage=""):
    """按**写端的公式**造一份回归产物，不是在测试里另发明一种形状。

    写端（`infrastructure.run_regression`）：

        root_dir = layout.regression_root(output_root)      # <out>/regression_run
        if self._stage_tag: root_dir = root_dir / stage     # 分级时每级一层
        ShellGenerator().generate(config, root_dir, ...)    # 其下 build_*/test_*/

    **`ShellGenerator` 在每一级的目录里都铺出全部用例目录**，只有那一级要跑的
    子集才真跑出产物 —— 给 `shared_case` 时每一级都会有它的目录，产物只落在
    `artifact_stage` 那一级。这正是读端要处理的现实形状。
    """
    from src.layers.l1_infrastructure.layout import regression_root

    def emit(root_dir, case, status="pass", artifact=False):
        d = root_dir / "build_b1" / f"test_{case}"
        d.mkdir(parents=True, exist_ok=True)
        (d / "status.env").write_text(f"EMAN_BASE_STATUS={status}\n", encoding="utf-8")
        (d / "sim_vsim.log").write_text("# UVM_INFO x @ 0: y [T] ok\n", encoding="utf-8")
        if artifact:
            (d / "waves").mkdir(exist_ok=True)
            (d / "waves" / f"{case}.db").write_bytes(b"x" * 64)
            (d / "cov" / case).mkdir(parents=True, exist_ok=True)
            (d / "cov" / case / "questa.db").write_bytes(b"x" * 64)
        return d

    made = {}
    if flat:
        made[""] = emit(regression_root(output_root), "t_flat")
    for st in stages:
        stage_root = regression_root(output_root) / st
        made[st] = emit(stage_root, f"t_{st}")
        if shared_case:
            emit(stage_root, shared_case, artifact=(st == artifact_stage))
    return made


class TestStageNamesAgreeWithTheWriter:
    """`layout.STAGE_DIRS` 必须**罩得住**写端的分级定义。

    两处各写一份级名是没办法的事（一个在读层、一个在基础设施层），那就钉住
    从属关系：写端新加一级、布局层的识别名单没跟上 → 那级目录会被读端当
    "不是一级"而漏掉。这里让它红，而不是等 GUI 少一列。
    """

    def test_every_writer_stage_is_recognised(self):
        from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
        from src.layers.l1_infrastructure.layout import STAGE_DIRS

        writer_stages = [s[0] for s in InfrastructureManager.REGRESSION_STAGES]
        missing = [s for s in writer_stages if s not in STAGE_DIRS]
        assert not missing, (
            f"写端有这些级，布局层的识别名单里没有：{missing} —— "
            f"它们的用例目录会被读端漏掉")

    def test_the_writer_actually_uses_the_contract(self):
        """写端拼路径**必须走 `layout.regression_root`**，不许自己再拼一次。

        这条防的是"收口了、又被人改回去"：改回 `output_root / "regression_run"`
        字面量 → 这里红。查的是**代码行**（注释会讲这件事、那不算复现）。
        """
        from pathlib import Path
        import src.layers.l1_infrastructure.infrastructure as infra

        code_lines = [
            ln for ln in Path(infra.__file__).read_text(encoding="utf-8").splitlines()
            if not ln.lstrip().startswith("#")
        ]
        offenders = [ln.strip() for ln in code_lines
                     if 'output_root / "regression_run"' in ln]
        assert not offenders, (
            f"写端又在拼字面量路径了 —— 布局契约只有 layout.py 一处：{offenders}")


class TestReaderRecognisesTheWrittenLayout:
    """读端认得**写端写出来的**布局 —— 这是那个整页空白的直接回归测试。"""

    def test_staged_layout_is_read(self, tmp_path):
        """**每一级**的用例都要看得见 —— 分级回归的意义就是每级的证据。

        写端只 `rmtree` **本级**目录（见 `run_regression` 里那段），所以每一级
        都躺着自己跑过的那批用例与产物。读端以前只扫最后一级（`latest_root`）——
        而最后一级往往只剩"随机/通用"那批，跑完什么都不落，于是
        「回归波形」「回归覆盖率」两页**整页空白**：产物明明在 p0/p1/p2。
        """
        from src.interfaces.api.flow.api import run_regression_status

        _write_run_dir(tmp_path, stages=("loopback", "p0", "p1"))
        payload = run_regression_status(str(tmp_path))

        assert "error" not in payload, payload.get("error")
        names = {r["name"] for r in payload["rows"]}
        assert names == {"t_loopback", "t_p0", "t_p1"}, f"读端漏了分级用例，拿到 {names}"
        assert payload["stats"]["total"] == 3

    def test_a_case_points_at_the_stage_that_actually_ran_it(self, tmp_path):
        """同一个用例在每一级都有目录，**只有跑过它的那一级有产物**。

        读端必须挑**有产物的那一份**，不能挑最后一级那个空壳 —— 否则页面上
        永远是"这条没有波形"，而波形就在旁边那一级的目录里。
        """
        from pathlib import Path

        from src.interfaces.api.flow.api import run_regression_status

        _write_run_dir(tmp_path, stages=("p0", "p1"), shared_case="t_shared",
                       artifact_stage="p0")
        payload = run_regression_status(str(tmp_path))
        rows = [r for r in payload["rows"] if r["name"] == "t_shared"]

        assert len(rows) == 1, "同一个用例出现在几级也只该占一行"
        assert rows[0]["wave"], "波形在 p0，读端却挑到了 p1 的空壳"
        assert rows[0]["cov"], "覆盖率库同上"
        assert "p0" in Path(rows[0]["wave"]).parts

    def test_flat_layout_still_reads(self, tmp_path):
        """老布局**不能因为支持分级就废掉** —— 存量运行目录都是平的。"""
        from src.interfaces.api.flow.api import run_regression_status

        _write_run_dir(tmp_path, flat=True)
        payload = run_regression_status(str(tmp_path))
        assert {r["name"] for r in payload["rows"]} == {"t_flat"}

    def test_regression_dir_itself_is_accepted(self, tmp_path):
        """传进来的可能就是**回归目录本身** —— 实测踩过，别再退回去。"""
        from src.layers.l1_infrastructure.layout import regression_root
        from src.interfaces.api.flow.api import run_regression_status

        _write_run_dir(tmp_path, stages=("p0",))
        reg_dir = regression_root(tmp_path)
        payload = run_regression_status(str(reg_dir))
        assert {r["name"] for r in payload["rows"]} == {"t_p0"}


class TestLayoutFunctions:
    """三个函数的语义 —— 读端两个需求（看一个 / 看全）共用一套判据。"""

    def test_latest_root_is_the_newest_stage(self, tmp_path):
        from src.layers.l1_infrastructure.layout import latest_root, regression_root

        _write_run_dir(tmp_path, stages=("loopback", "p0", "p2"))
        assert latest_root(tmp_path) == regression_root(tmp_path) / "p2"

    def test_test_dirs_sees_every_stage(self, tmp_path):
        """**看全**：每一级都是证据，不是只看最后一级。"""
        from src.layers.l1_infrastructure.layout import test_dirs

        _write_run_dir(tmp_path, stages=("loopback", "p0", "p2"))
        assert {d.name for d in test_dirs(tmp_path)} == {
            "test_t_loopback", "test_t_p0", "test_t_p2"}

    def test_no_regression_artifacts_returns_none_not_a_bogus_path(self, tmp_path):
        """没有产物 → `None`。**不返回一个不存在的路径** —— 那会让调用方
        读到一个空目录、当成"没有用例"，把"路径拼错了"伪装成"这轮没跑"。"""
        from src.layers.l1_infrastructure.layout import latest_root, test_dirs

        assert latest_root(tmp_path) is None
        assert test_dirs(tmp_path) == []

    def test_empty_regression_run_is_none(self, tmp_path):
        from src.layers.l1_infrastructure.layout import regression_root, latest_root

        regression_root(tmp_path).mkdir()          # 目录在，但没有 build_*
        assert latest_root(tmp_path) is None
