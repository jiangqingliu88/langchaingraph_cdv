"""回归用例的**覆盖率**：找得到库、摊得开给人看。

背景：仿真命令里那句 `-coverstore ${EMAN_CM_DIR}/${EMAN_TEST_NAME}` 会把覆盖率
落成一份库（`<用例目录>/cov/<用例>/questa.db`），但**它是二进制** —— 双击什么都不
会发生。人想校对只能看报告，所以"打开覆盖率"的真实动作是
`vcover report -html` 先生成、再打开。这里钉的就是这两步。

三件容易错的事：

  · **别把 `.data` 当库**：`-coverstore` 在同一个目录里还写一个 `<name>.data`，
    `vcover` 不认它（实测 `vcover-6808`）。收错了 → 点了弹一个错误框。
  · **报告要复用**：一条用例点第二次不该再跑一遍 vcover（那几秒体感很明显），
    但库重跑过（mtime 变新）时必须重建 —— 给人看上一轮的数比不显示更坏。
  · **找不到要说清楚是哪一个**：库不在 / vcover 不在 / vcover 报错，三种原因的
    处置完全不同（等回归跑完 / 装 Questa / 看库本身）。
"""
from __future__ import annotations

import time

from src.layers.l3_decision.evidence import cov_api


class TestFindCoverageDb:

    def _case(self, tmp_path, name="t1"):
        d = tmp_path / "regression_run" / "build_b1" / f"test_{name}"
        d.mkdir(parents=True)
        return d

    def test_prefers_the_configured_location(self, tmp_path):
        d = self._case(tmp_path)
        db = d / "cov" / "t1" / "questa.db"
        db.parent.mkdir(parents=True)
        db.write_bytes(b"db")

        path, source = cov_api.find_coverage_db(d)
        assert path == str(db)
        assert source == "cm_dir"

    def test_data_file_next_to_the_db_is_not_a_database(self, tmp_path):
        """`-coverstore` 的副产品 `.data` 不是库（vcover 不认）。"""
        d = self._case(tmp_path)
        covdir = d / "cov" / "t1"
        covdir.mkdir(parents=True)
        (covdir / "t1.data").write_bytes(b"data")

        assert cov_api.find_coverage_db(d) == ("", "none")

    def test_plain_ucdb_under_cov_counts(self, tmp_path):
        d = self._case(tmp_path)
        covdir = d / "cov"
        covdir.mkdir(parents=True)
        ucdb = covdir / "merged.ucdb"
        ucdb.write_bytes(b"ucdb")

        path, source = cov_api.find_coverage_db(d)
        assert path == str(ucdb) and source == "cm_dir"

    def test_falls_back_to_the_simulator_default_location(self, tmp_path):
        d = self._case(tmp_path)
        ucdb = d / "vsim.ucdb"
        ucdb.write_bytes(b"ucdb")

        path, source = cov_api.find_coverage_db(d)
        assert path == str(ucdb) and source == "sim_dir"

    def test_nothing_found_is_empty(self, tmp_path):
        assert cov_api.find_coverage_db(self._case(tmp_path)) == ("", "none")

    def test_newest_db_wins(self, tmp_path):
        """一条用例多轮覆盖数据 → 取最新那轮。"""
        import os

        d = self._case(tmp_path)
        covdir = d / "cov"
        covdir.mkdir(parents=True)
        old, new = covdir / "old.ucdb", covdir / "new.ucdb"
        old.write_bytes(b"1")
        new.write_bytes(b"2")
        os.utime(old, (1000, 1000))
        os.utime(new, (time.time(), time.time()))

        assert cov_api.find_coverage_db(d)[0] == str(new)


class TestFindRunCoverage:
    """**总覆盖率**（整个环境合并后的那一份）落在哪 —— 与"一条用例的库"分开。"""

    def test_finds_the_merged_db_and_the_agents_report(self, tmp_path):
        """两份产物各有各的用处：库能重新出报告，报告是当时 agent 看的那一份。"""
        cov = tmp_path / "sim" / "coverage"
        (cov / "reports").mkdir(parents=True)
        (cov / "merged.ucdb").write_bytes(b"merged")
        (cov / "reports" / "index.html").write_text("<html></html>", encoding="utf-8")

        files = cov_api.find_run_coverage(tmp_path)
        assert files["db"]["exists"] and files["db"]["path"].endswith("merged.ucdb")
        assert files["report"]["exists"] and files["report"]["path"].endswith("index.html")

    def test_falls_back_to_any_ucdb_in_the_coverage_dir(self, tmp_path):
        cov = tmp_path / "sim" / "coverage"
        cov.mkdir(parents=True)
        (cov / "some.ucdb").write_bytes(b"x")

        files = cov_api.find_run_coverage(tmp_path)
        assert files["db"]["exists"] and files["db"]["path"].endswith("some.ucdb")

    def test_nothing_there_is_not_an_error(self, tmp_path):
        files = cov_api.find_run_coverage(tmp_path)
        assert files["db"]["exists"] is False and files["db"]["kb"] is None
        assert files["report"]["exists"] is False


class TestBuildCoverageReport:

    def _db(self, tmp_path, name="case.ucdb"):
        # 这里测的是**报告生成**，不是 coverstore 转换 —— 用一个真正的 UCDB
        # （`questa.db` 的转换由 `test_coverage_coverstore.py` 单独钉）。
        db = tmp_path / "cov" / "t1" / name
        db.parent.mkdir(parents=True)
        db.write_bytes(b"db")
        return db

    def test_missing_db_fails_loud(self, tmp_path):
        out = cov_api.build_coverage_report(str(tmp_path / "nope"))
        assert out["status"] == "FAIL"
        assert "不存在" in out["error"]

    def test_missing_vcover_fails_loud(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "")
        out = cov_api.build_coverage_report(str(self._db(tmp_path)))
        assert out["status"] == "FAIL"
        assert "vcover" in out["error"]

    def test_reuses_a_report_that_is_newer_than_the_db(self, tmp_path):
        db = self._db(tmp_path)
        html = db.parent / cov_api.HTML_DIR_NAME
        html.mkdir()
        (html / "index.html").write_text("<html></html>", encoding="utf-8")
        # 报告比库新（先写库、再写报告）
        import os
        os.utime(db, (1000, 1000))

        out = cov_api.build_coverage_report(str(db))
        assert out["status"] == "PASS" and out["cached"] is True
        assert out["html"].endswith("index.html")

    def test_stale_report_is_rebuilt(self, tmp_path, monkeypatch):
        """库重跑过 → 旧报告必须重建（给人看上一轮的数比不显示更坏）。"""
        db = self._db(tmp_path)
        html = db.parent / cov_api.HTML_DIR_NAME
        html.mkdir()
        (html / "index.html").write_text("<html>old</html>", encoding="utf-8")
        import os
        os.utime(html / "index.html", (1000, 1000))     # 报告是旧的

        calls = []

        class _Proc:
            returncode = 0
            stdout = ""
            stderr = ""

        def fake_run(cmd, **kw):
            calls.append(cmd)
            (html / "index.html").write_text("<html>new</html>", encoding="utf-8")
            return _Proc()

        monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover")
        monkeypatch.setattr(cov_api.subprocess, "run", fake_run)

        out = cov_api.build_coverage_report(str(db))
        assert out["status"] == "PASS" and out["cached"] is False
        assert calls, "没重建：vcover 没被调用"
        assert "-html" in calls[0] and db.as_posix() in calls[0]

    def test_vcover_failure_is_reported_with_its_output(self, tmp_path, monkeypatch):
        db = self._db(tmp_path)

        class _Proc:
            returncode = 1
            stdout = "** Error: (vcover-7) Failed to open UCDB file"
            stderr = ""

        monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover")
        monkeypatch.setattr(cov_api.subprocess, "run",
                            lambda cmd, **kw: _Proc())

        out = cov_api.build_coverage_report(str(db))
        assert out["status"] == "FAIL"
        assert "vcover-7" in out["error"]

    def test_custom_output_dir(self, tmp_path, monkeypatch):
        db = self._db(tmp_path)
        target = tmp_path / "报告" / "here"
        html = target

        class _Proc:
            returncode = 0
            stdout = ""

        def fake_run(cmd, **kw):
            html.mkdir(parents=True, exist_ok=True)
            (html / "index.html").write_text("<html></html>", encoding="utf-8")
            return _Proc()

        monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover")
        monkeypatch.setattr(cov_api.subprocess, "run", fake_run)

        out = cov_api.build_coverage_report(str(db), output_dir=str(target))
        assert out["status"] == "PASS"
        assert out["output_dir"] == str(target)
