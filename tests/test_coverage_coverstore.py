"""coverstore → UCDB 的转换契约。

## 为什么需要它

回归的 `-coverstore <store> -testname <test>` 产物是 `<store>/questa.db`
+ `<store>/<test>.data`。`vcover report -cvg <store>/questa.db` **只读得到代码
覆盖率**，功能覆盖率整段丢失（实测 "No matching coverage data"）—— 而用例
日志里 covergroup 明明有命中。正确入口是：

    vcover merge <out.ucdb> "<store>:<test>"

界面上的「看用例覆盖率 / 在 Visualizer 下钻」都走这一步。这里钉住：
  · `.ucdb` 原样透传；
  · coverstore 走 `store.name:test`（**相对路径**，避开 Windows 盘符冒号）；
  · 输出是**绝对路径**（vcover 的 cwd 被切到 store.parent）。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from src.tools.coverage_tools import cov_api


def _fake_store(tmp_path: Path):
    store = tmp_path / "cov" / "mytest"
    store.mkdir(parents=True)
    (store / "questa.db").write_bytes(b"fake-index")
    (store / "mytest.data").write_bytes(b"fake-data")
    return store


def test_a_ucdb_is_passed_through(tmp_path):
    ucdb = tmp_path / "x.ucdb"
    ucdb.write_bytes(b"x")
    path, why = cov_api.materialize_ucdb(str(ucdb))
    assert path == str(ucdb) and why == ""


def test_a_missing_db_is_an_error_not_a_fake_path(tmp_path):
    path, why = cov_api.materialize_ucdb(str(tmp_path / "nope" / "questa.db"))
    assert path == "" and "不存在" in why


def test_coverstore_merges_with_a_relative_spec(monkeypatch, tmp_path):
    store = _fake_store(tmp_path)
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        calls["cwd"] = kw.get("cwd")
        out = Path(cmd[2])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"merged")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover.exe")
    monkeypatch.setattr(cov_api.subprocess, "run", fake_run)

    path, why = cov_api.materialize_ucdb(str(store / "questa.db"), force=True)
    assert why == ""
    assert Path(path).is_absolute() and Path(path).is_file()
    # **相对 spec 且带一层目录**：`cov/<store>:<test>` —— 只写 `<store>:<test>`
    # 会被 vcover 当成目录名（实测）。也避开了 Windows 盘符冒号。
    assert calls["cmd"][3] == "cov/mytest:mytest"
    assert Path(calls["cwd"]).resolve() == (store.parent.parent).resolve()
    # 输出必须是绝对路径（否则会落到被切过的 cwd 下）
    assert Path(calls["cmd"][2]).is_absolute()


def test_the_merged_ucdb_is_reused_when_fresh(monkeypatch, tmp_path):
    store = _fake_store(tmp_path)
    merged = store / "_ucdb" / "mytest.ucdb"
    merged.parent.mkdir(parents=True)
    merged.write_bytes(b"cached")
    # 让合并库比 store 索引新
    merged.touch()
    called = []
    monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover.exe")
    monkeypatch.setattr(cov_api.subprocess, "run",
                        lambda *a, **k: called.append(1) or SimpleNamespace(
                            returncode=0, stdout="", stderr=""))

    path, why = cov_api.materialize_ucdb(str(store / "questa.db"))
    assert path == str(merged.resolve()) and why == ""
    assert called == []                       # 命中缓存，不再 merge


def test_vcover_failure_is_reported_not_swallowed(monkeypatch, tmp_path):
    store = _fake_store(tmp_path)
    monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover.exe")
    monkeypatch.setattr(cov_api.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(
                            returncode=1, stdout="", stderr="bad coverstore"))
    path, why = cov_api.materialize_ucdb(str(store / "questa.db"), force=True)
    assert path == "" and "bad coverstore" in why


def test_a_null_test_name_merges_by_store_path(monkeypatch, tmp_path):
    """`(null).data`（`-testname` 漏传的历史产物）只给 store 路径。

    `vcover merge "store:(null)"` 会报 "No input files"；`store:test` 甚至会
    让 vcover 崩。正确写法是 `cov/<store>`，它自己报 `Merging test ...:(null)`。
    """
    store = tmp_path / "cov" / "mytest"
    store.mkdir(parents=True)
    (store / "questa.db").write_bytes(b"fake-index")
    (store / "(null).data").write_bytes(b"fake-data")
    calls = {}

    def fake_run(cmd, **kw):
        calls["cmd"] = cmd
        out = Path(cmd[2])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"merged")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(cov_api, "_vcover_binary", lambda: "vcover.exe")
    monkeypatch.setattr(cov_api.subprocess, "run", fake_run)

    path, why = cov_api.materialize_ucdb(str(store / "questa.db"), force=True)
    assert why == ""
    assert calls["cmd"][3] == "cov/mytest"          # 不带 :test
    assert Path(path).name == "mytest.ucdb"          # 输出名用目录名
