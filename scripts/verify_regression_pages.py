"""离屏验收：回归状态 / 回归波形 / 回归覆盖率 三个页面**在真窗口里**能不能装数据。

不是单元测试的替代品，是补上它们测不到的那一段：模块在真清单、真 bridge、
真运行目录下走一遍 `load()`，并把窗口抓成 PNG 供人眼看。跑法（在仓库根目录）：

    QT_QPA_PLATFORM=offscreen venv/Scripts/python.exe scripts/verify_regression_pages.py

判据：
  · 三个模块都能 `open()` 成功（清单里注册了、factory 能导入）；
  · `load(run_id)` 之后表格行数 > 0（数据真的从 `flow.regression_status` 流进来了）；
  · 「打开总覆盖率」按钮在回归状态页上找得到。
抓出来的图在 `_shots/` 下。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QSettings            # noqa: E402
from PySide6.QtWidgets import QApplication      # noqa: E402

app = QApplication.instance() or QApplication([])

from src.orchestration_plane.l2.run_service import list_runs   # noqa: E402
from src.workbench.settings_store import SettingsStore         # noqa: E402
from src.workbench.tests.conftest import (make_ctx, make_window,  # noqa: E402
                                          shipped_manifest)

SHOTS = ROOT / "_shots"
SHOTS.mkdir(exist_ok=True)

# ── 挑一次真有产物的运行：优先 regression_run 里带 wave 的那些 ──
runs = list_runs() or []
if isinstance(runs, dict):
    runs = runs.get("runs") or []
print(f"运行历史里 {len(runs)} 条")
chosen = None
for r in runs:
    rid = r.get("run_id") or r.get("id") or ""
    if rid:
        chosen = rid
        break
if not chosen:
    print("!! 没有可用的运行 —— 先跑一次闭环再看")
    raise SystemExit(1)
print(f"用这次运行验收：{chosen}")

manifest, manifest_path = shipped_manifest()
settings = SettingsStore(QSettings(str(ROOT / "_shots" / "_verify.ini"),
                                   QSettings.Format.IniFormat))
window = make_window(app, make_ctx(manifest, manifest_path, settings))
window.show()
app.processEvents()

PAGES = [
    ("ops.regression_status", "回归状态"),
    ("ops.regression_wave", "回归波形"),
    ("ops.regression_coverage", "回归覆盖率"),
]

failed = []
for module_id, title in PAGES:
    print(f"\n=== {title}（{module_id}）===")
    window.manager.open(module_id)
    app.processEvents()
    module = window.manager.module(module_id)
    if module is None:
        print("  !! 模块没建起来")
        failed.append(module_id)
        continue
    module.load(chosen)
    app.processEvents()
    rows = getattr(module.model, "rowCount", lambda: 0)()
    print(f"  表格行数：{rows}")
    if rows <= 0:
        failed.append(module_id)
    label = getattr(module, "summary_label", None)
    if label is not None:
        print(f"  摘要：{label.text()}")
    out = SHOTS / f"regression_{module_id.split('.')[-1]}.png"
    window.grab().save(str(out))
    print(f"  截图：{out.relative_to(ROOT)}")

# 「打开总覆盖率」按钮必须在回归状态页上
status = window.manager.module("ops.regression_status")
has_btn = status is not None and hasattr(status, "btn_total_coverage")
print(f"\n回归状态页有「打开总覆盖率」按钮：{has_btn}")
if not has_btn:
    failed.append("ops.regression_status:btn_total_coverage")

window.manager.mark_all_clean()
window.close()
window.deleteLater()
app.processEvents()

print("\n结论：" + ("全部通过" if not failed else f"有问题 → {failed}"))
raise SystemExit(1 if failed else 0)
