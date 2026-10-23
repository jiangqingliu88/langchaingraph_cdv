"""波形/覆盖率「打开」的动作 —— 按格式选对工具。

Visualizer 只认 qwavedb（`waves/*.db`）；`.wlf` 必须走 `vsim -view`，否则
Visualizer 报 "is not a qwavedb file"。这两条是记忆里踩过的坑，这里钉住命令形状。

另外：`vsim -view` 只打开数据集，**不把信号加到波形窗** —— 窗口是空的，看起来
就像"打不开"。所以必须带 `-do "add wave -r /*"`；而且 GUI 进程的 stdin 是 EOF
的，vsim 执行完会**当场退出**，得给它一个被父进程持有的 PIPE。
"""
from __future__ import annotations

import subprocess

from src.workbench.modules.ops import cov_actions


class _Proc:
    def poll(self):
        return None


class _Module:
    def __init__(self):
        self.messages = []

    def set_status(self, msg):
        self.messages.append(msg)


def _patch_launch(monkeypatch):
    calls = {}

    def fake_popen(cmd, **kw):
        calls["cmd"] = cmd
        calls["kw"] = kw
        return _Proc()

    monkeypatch.setattr(cov_actions, "vsim_exe", lambda: "vsim.exe")
    monkeypatch.setattr(cov_actions, "visualizer_exe", lambda: "visualizer.exe")
    monkeypatch.setattr(cov_actions.subprocess, "Popen", fake_popen)
    return calls


def test_a_wlf_uses_vsim_view_and_adds_the_signals(monkeypatch, tmp_path):
    wlf = tmp_path / "t.wlf"
    wlf.write_bytes(b"x")
    calls = _patch_launch(monkeypatch)
    module = _Module()

    cov_actions.open_wave(module, str(wlf))

    assert calls["cmd"][:3] == ["vsim.exe", "-view", str(wlf)]
    assert calls["cmd"][3:5] == ["-do", "add wave -r /*"]
    # 没有这个 PIPE，vsim 读完 EOF 会立刻退出（窗口一闪而过）
    assert calls["kw"].get("stdin") == subprocess.PIPE
    assert module._wave_procs and module._wave_procs[-1].poll() is None
    assert "Visualizer 只认 qwavedb" in module.messages[-1]


def test_a_qwavedb_uses_visualizer_with_the_design_index(monkeypatch, tmp_path):
    """**必须成对给 `-designfile`**：只有 `-wavefile` 时没有 hier、跳不到源码。"""
    db = tmp_path / "t.db"
    db.write_bytes(b"x")
    design = tmp_path / "design.db"
    design.write_bytes(b"design")
    calls = _patch_launch(monkeypatch)
    module = _Module()

    cov_actions.open_wave(module, str(db))

    assert calls["cmd"] == ["visualizer.exe", "-designfile", str(design),
                            "-wavefile", str(db)]
    assert "stdin" not in calls["kw"]
    assert "Questa Visualizer" in module.messages[-1]


def test_a_qwavedb_without_design_still_opens_the_wave(monkeypatch, tmp_path):
    """生成不了 design.db 时退回只开波形 —— 能看波形，但不假装有 hier。"""
    db = tmp_path / "t.db"
    db.write_bytes(b"x")
    calls = _patch_launch(monkeypatch)
    module = _Module()

    cov_actions.open_wave(module, str(db))

    assert calls["cmd"] == ["visualizer.exe", "-wavefile", str(db)]
    assert "无设计索引" in module.messages[-1]


def test_a_missing_file_is_explained_not_launched(monkeypatch, tmp_path):
    calls = _patch_launch(monkeypatch)
    module = _Module()

    cov_actions.open_wave(module, str(tmp_path / "nope.wlf"))

    assert "cmd" not in calls
    assert "没有" in module.messages[-1]
