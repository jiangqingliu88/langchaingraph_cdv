"""SoC 页面公共壳 —— 工程根、run 选择、波形/证据动作。

数据走 `src/workbench/cli/soc_adapter.py` 的只读函数（经 bridge/catalog 白名单），
页面本身不读 RTL、不跑 EDA（运行是 `soc.run` 的显式按钮）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

from ..base import ModuleBase


def find_project_root() -> Path:
    """当前工作目录下的 examples/open_npu_soc（或 cwd 本身）。"""
    here = Path.cwd()
    for base in (here, *here.parents):
        candidate = base / "examples" / "open_npu_soc"
        if (candidate / "spec" / "soc_spec.yaml").is_file():
            return candidate
        if (base / "spec" / "soc_spec.yaml").is_file() and (base / "rtl" / "soc_top.sv").is_file():
            return base
    return here / "examples" / "open_npu_soc"


class SocModuleBase(ModuleBase):
    """Run 选择 + 常用动作。"""

    def __init__(self, ctx, spec) -> None:
        super().__init__(ctx, spec)
        self.project_root = find_project_root()
        self._runs: List[Dict[str, Any]] = []
        self._summary: Dict[str, Any] = {}

    def _run_bar(self, parent: QWidget) -> QWidget:
        bar = QWidget(parent)
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("SoC run"))
        self.run_combo = QComboBox(bar)
        self.run_combo.setMinimumWidth(340)
        self.run_combo.currentIndexChanged.connect(self._run_changed)
        row.addWidget(self.run_combo, 1)
        row.addWidget(self._button("刷新", self.refresh, bar))
        return bar

    def _button(self, text: str, slot, parent=None) -> QPushButton:
        button = QPushButton(text, parent or self.content)
        button.clicked.connect(slot)
        return button

    def refresh(self) -> None:
        payload = self.run_tool("soc.runs", quiet=True, base=str(Path.cwd()))
        # SoC 页面只认 SoC / C 用例 run。IP run 是**子集回归**，混进来会被
        # 当成"这次 SoC 跑过了"——它归 IP 工作区自己看。
        self._runs = [r for r in (payload if isinstance(payload, list) else [])
                      if str(r.get("kind") or "") != "ip"]
        current = self.run_combo.currentData()
        self.run_combo.blockSignals(True)
        self.run_combo.clear()
        for item in self._runs:
            label = f"{item.get('run')} · {item.get('status') or '?'}"
            if item.get("kind") == "soc_c":
                label = (f"{item.get('run')} · C·{item.get('case') or '?'} · "
                         f"{item.get('status') or '?'}")
            self.run_combo.addItem(label, item.get("dir"))
        idx = self.run_combo.findData(current) if current else -1
        if idx < 0 and self.run_combo.count():
            idx = 0
        self.run_combo.setCurrentIndex(idx)
        self.run_combo.blockSignals(False)
        self._run_changed(self.run_combo.currentIndex())

    def _run_changed(self, index: int) -> None:
        root = str(self.run_combo.currentData() or "")
        if not root:
            self._summary = {}
            self.on_summary({})
            return
        payload = self.run_tool("soc.run_summary", quiet=True, run_root=root)
        self._summary = payload if isinstance(payload, dict) else {}
        self.on_summary(self._summary)

    def on_summary(self, summary: Dict[str, Any]) -> None:
        """子类覆盖。"""

    def current_dir(self) -> str:
        return str(self.run_combo.currentData() or "")

    def open_wave(self) -> None:
        wave = str((self._summary or {}).get("wave") or "")
        if not wave:
            self.show_warning("这次 run 没有波形；确认 regression.yaml 开了 -qwavedb")
            return
        from ..ops.cov_actions import open_wave
        open_wave(self, wave)

    def verify_evidence(self) -> None:
        root = self.current_dir()
        if not root:
            self.show_warning("先选一次 SoC run")
            return
        if str((self._summary or {}).get("kind") or "") == "soc_c":
            self.show_info("C 用例 run 没有 SoC 证据包（产物是 c_run.json + 波形）。")
            return
        result = self.run_tool("soc.verify_evidence", quiet=True, run_root=root)
        if not isinstance(result, dict):
            return
        if result.get("ok"):
            self.show_info(f"证据包完整：{result.get('files', 0)} 个文件 · "
                           f"package_hash {str(result.get('package_hash'))[:16]}…")
        else:
            self.show_error("证据包校验失败：" + str(result.get("issues") or [])[:300])

    def run_soc(self) -> None:
        self.show_info("开始跑 SoC 回归（Questa vlog/vsim，约 2–5 秒）…")
        result = self.run_tool("soc.run", force=True,
                               project_project_root=str(self.project_root))
        if not isinstance(result, dict):
            return
        if result.get("status") == "PASS":
            self.show_info(f"SoC 回归 PASS · {result.get('output_root', '')}")
        else:
            self.show_error(f"SoC 回归失败：{result.get('error') or result.get('status')}")
        self.refresh()
