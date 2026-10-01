"""主窗口 —— 工具栏 + 标签页 + 状态栏。

它只做四件事：开文件、调分析门面、把结果发给每个标签页、导出报告。
标签页清单从 tabs.TABS 读，所以新增页面不用改这里。

启动:
    python -m src.tools.casemodel_tools.cli gui [模型.yaml]
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, ttk
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "当前 Python 没有 tkinter（Linux 下需 apt install python3-tk）") from exc

from ...analysis import AnalysisResult, analyze_file
from ...analysis.schema_check import SchemaChecker
from ...domain import CaseModelError
from ...domain.errors import CaseListError
from .tabs import TABS
from .widgets import pick_font

APP_TITLE = "SignOffAI · case 属性完备性分析"


class CaseModelApp:
    def __init__(self, root: "tk.Tk", path: Optional[str] = None) -> None:
        self.root = root
        self.result: Optional[AnalysisResult] = None
        self.path: Optional[Path] = None
        self.cases_path: Optional[Path] = None      # 外部真实 case 列表
        self.schema_issues: List = []

        root.title(APP_TITLE)
        root.geometry("1460x900")
        root.minsize(1080, 680)
        self._setup_style()

        self._build_toolbar()
        self._build_body()
        self._build_status()

        if path:
            self.load(path)
        else:
            self._set_status("请用「打开模型」选择 case 模型 YAML，或直接拖入路径。"
                             "示例：src/tools/casemodel_tools/examples/"
                             "cpu_pipeline.yaml")

    # ── 样式 ──

    def _setup_style(self) -> None:
        family = pick_font(self.root)
        if family:
            for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont",
                         "TkHeadingFont"):
                try:
                    tkfont.nametofont(name).configure(family=family, size=9)
                except tk.TclError:
                    pass
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("Treeview", rowheight=23, fieldbackground="white")
        style.configure("Treeview.Heading",
                        font=(family or "TkDefaultFont", 9, "bold"))
        style.configure("TNotebook.Tab", padding=(12, 6))

    # ── 布局 ──

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 8, 10, 4))
        bar.pack(fill=tk.X)
        ttk.Button(bar, text="打开模型…", command=self.on_open).pack(side=tk.LEFT)
        ttk.Button(bar, text="重新分析", command=self.reload).pack(side=tk.LEFT,
                                                                padx=(6, 0))
        ttk.Button(bar, text="载入真实 case…",
                   command=self.on_load_cases).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Button(bar, text="导出报告", command=self.on_export).pack(side=tk.LEFT,
                                                                   padx=(6, 0))
        self.path_label = ttk.Label(bar, text="（未加载）", foreground="#5f6b7a")
        self.path_label.pack(side=tk.LEFT, padx=(14, 0))

    def _build_body(self) -> None:
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        self.tabs: Dict[str, object] = {}
        for tab_cls in TABS:
            tab = tab_cls(self.nb, self)
            self.nb.add(tab.frame, text=tab.title)
            self.tabs[tab.title] = tab

    def _build_status(self) -> None:
        self.status = ttk.Label(self.root, text="就绪", anchor=tk.W,
                                padding=(12, 6), foreground="#37474f")
        self.status.pack(fill=tk.X, side=tk.BOTTOM)

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    # ── 动作 ──

    def on_open(self) -> None:
        path = filedialog.askopenfilename(
            title="选择 case 模型 YAML",
            filetypes=[("YAML 文件", "*.yaml *.yml"), ("所有文件", "*.*")])
        if path:
            self.load(path)

    def on_load_cases(self) -> None:
        path = filedialog.askopenfilename(
            title="选择真实 case 列表",
            filetypes=[("case 列表", "*.yaml *.yml *.json *.csv"),
                       ("所有文件", "*.*")])
        if not path:
            return
        if self.path is None:
            messagebox.showinfo("真实 case 核对", "请先载入 case 模型 YAML。",
                                parent=self.root)
            return
        self.cases_path = Path(path)
        self.load(str(self.path))

    def on_clear_cases(self) -> None:
        self.cases_path = None
        if self.path:
            self.load(str(self.path))

    def reload(self) -> None:
        if self.path:
            self.load(str(self.path))
        else:
            self._set_status("还没有加载模型。")

    def load(self, path: str) -> None:
        self.path = Path(path)
        self.path_label.configure(text=str(self.path))
        self._set_status(f"正在分析 {self.path.name} …")
        self.root.update_idletasks()
        try:
            self.result = analyze_file(
                str(self.path),
                cases=str(self.cases_path) if self.cases_path else None)
        except (CaseModelError, CaseListError) as exc:
            self.result = None
            messagebox.showerror("模型无法构建", str(exc), parent=self.root)
            self._set_status(f"加载失败：{exc}")
            return
        except FileNotFoundError as exc:
            self.result = None
            messagebox.showerror("文件不存在", str(exc), parent=self.root)
            self._set_status(f"加载失败：{exc}")
            return
        except Exception as exc:                      # noqa: BLE001
            self.result = None
            messagebox.showerror(
                "分析失败", f"{exc}\n\n{traceback.format_exc(limit=4)}",
                parent=self.root)
            self._set_status(f"分析失败：{exc}")
            return

        try:
            self.schema_issues = SchemaChecker().check_file(self.path)
        except SystemExit as exc:                     # schema 文件本身坏了
            self.schema_issues = []

        self.refresh()
        s = self.result.summary()
        self._set_status(
            f"{self.path.name} —— 组织树 {s['org_leaf_count']} 叶子，"
            f"专题 {s['theme_count']} 个，生成 {s['case_count']} 个 case"
            + (f"（截断丢弃 {s['dropped']}）" if s["truncated"] else "")
            + f"，完备性 {s['score']}/100，"
              f"错误 {s['error_count']} / 警告 {s['warning_count']} / "
              f"提示 {s['info_count']}")

    def refresh(self) -> None:
        if self.result is None:
            return
        for tab in self.tabs.values():
            tab.refresh(self.result)      # type: ignore[attr-defined]

    # ── 导出 ──

    def on_export(self) -> None:
        if self.result is None:
            messagebox.showinfo("导出报告", "还没有加载模型。", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            title="导出完备性报告", defaultextension=".txt",
            initialfile=f"{self.path.stem if self.path else 'case_model'}_report.txt",
            filetypes=[("文本报告", "*.txt"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            Path(path).write_text(self.render_report(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self._set_status(f"报告已导出：{path}")

    def render_report(self) -> str:
        """导出文本报告 —— 复用 CLI 的渲染器，两处输出保持一致。"""
        from ..text import report as text_report
        result = self.result
        parts = [text_report(result)]
        if result is not None and not self.schema_issues:
            parts.append("\n【Schema 校验】\n  通过")
        elif self.schema_issues:
            parts.append("\n【Schema 校验】\n"
                         + "\n".join(f"  {i}" for i in self.schema_issues))
        return "\n".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    root = tk.Tk()
    CaseModelApp(root, path=args[0] if args else None)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
