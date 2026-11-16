"""TUI 主窗口 —— 终端里的 ChipStack 风格交互界面。

两个主窗口：
  · TUI（本文件）：`vagent tui --mode ...` / `vagent tui --session-name ...`
  · 老 GUI：`vagent gui [--mode ...]`（PySide6，`src/workbench/main_window.py`）

TUI 不另造执行链：每个 turn 仍由 `cli/repl.Repl` → `agent_mode_service` /
`verify_mode` 完成；本文件只负责**主窗口布局**（模式、会话、最新运行、最近
输出）和输入循环。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from src.runtime_plane.core.project_layout import ProjectLayout
from src.workbench.chipstack_compat import GUIDE_TUI_MODES, TUI_MODES
from src.workbench.cli import tui_sessions
from src.workbench.cli.repl import Repl
from src.workbench.modes.agent_modes import get_mode

console = Console()

_HELP = """命令:
  /agent [mode]    切换领域模式（mental_model/formal/functional_coverage/uvm/rtl_designer/debug/workflows）
  /mode [chat|plan|verify]  切换交互方式
  /md list|show|edit        浏览/查看/编辑 Markdown 产物
  /status /session /approve /deny /answer /plan /help /exit
"""


class TuiApp:
    def __init__(self, *, workspace: Optional[str] = None,
                 mode: str = "", session_name: str = ""):
        self.workspace = str(Path(workspace or Path.cwd()).resolve())
        self.session_name = str(session_name or "").strip()
        self.preset_id = TUI_MODES.get(mode, "") if mode else ""
        interaction = get_mode(self.preset_id).interaction if self.preset_id else "chat"
        self.repl = Repl(workspace=self.workspace, mode=interaction,
                         session_name=self.session_name, agent_mode=self.preset_id)
        self.layout = ProjectLayout.discover(self.workspace)
        self._input = console.input

    # ── 渲染 ─────────────────────────────────────────────────

    def _header(self) -> Panel:
        preset = get_mode(self.repl.agent_mode) if self.repl.agent_mode else None
        mode_label = f"{preset.label} / {self.repl.mode}" if preset else self.repl.mode
        session = self.repl.session_id or "（新会话）"
        name = f" · name={self.session_name}" if self.session_name else ""
        lines = Text()
        lines.append("mode: ", style="dim")
        lines.append(mode_label, style="bold cyan")
        lines.append("   workspace: ", style="dim")
        lines.append(self.workspace)
        lines.append("   session: ", style="dim")
        lines.append(f"{session}{name}")
        return Panel(lines, title="SignOffAI · ChipStack TUI", subtitle=" /help 查看命令")

    def _modes_table(self) -> Table:
        table = Table(title="领域模式", show_header=False, box=None, padding=(0, 1))
        for mode_id in GUIDE_TUI_MODES:
            preset = get_mode(TUI_MODES[mode_id])
            active = "●" if preset.id == self.repl.agent_mode else " "
            style = "bold green" if active == "●" else ""
            table.add_row(f"{active} {mode_id}", Text(f"({preset.interaction})", style="dim"),
                          style=style)
        return table

    def _sessions_table(self) -> Table:
        rows = tui_sessions.list_sessions(self.workspace)
        table = Table(title="命名会话", show_header=False, box=None, padding=(0, 1))
        if not rows:
            table.add_row(Text("（暂无）", style="dim"))
            return table
        for row in rows[:8]:
            name = str(row.get("name") or "")
            active = "●" if name == self.session_name else " "
            table.add_row(f"{active} {name}",
                          Text(f"{row.get('mode','')} · {row.get('session_id','')[:8]}", style="dim"))
        return table

    def _run_text(self) -> Text:
        run = self.layout.latest_run()
        if not run:
            return Text("最新运行：（还没有 run）", style="dim")
        status = str(run.get("status") or "?")
        text = Text()
        text.append("最新运行：", style="dim")
        text.append(str(run.get("run_id") or ""), style="bold")
        text.append(f"  {status}")
        if run.get("run_dir"):
            text.append(f"\n{run.get('run_dir')}", style="dim")
        return text

    def render(self) -> None:
        console.clear()
        console.print(self._header())
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1)
        grid.add_column(ratio=2)
        grid.add_row(self._modes_table(), self._sessions_table())
        console.print(Panel(grid, title="模式 / 会话"))
        console.print(self._run_text())
        console.print(Text("输入任务开始；/agent 切换模式，/md 查看产物，/exit 退出", style="dim"))

    # ── 输入 ─────────────────────────────────────────────────

    def _agent_command(self, rest: str) -> bool:
        value = rest.strip()
        if not value:
            console.print(f"当前领域模式：{self.repl.agent_mode or '（无）'}；"
                          f"可用：{', '.join(GUIDE_TUI_MODES)}")
            return True
        if value not in TUI_MODES:
            console.print(f"未知领域模式：{value}；可用：{', '.join(GUIDE_TUI_MODES)}")
            return True
        preset = get_mode(TUI_MODES[value])
        self.repl.agent_mode = preset.id
        self.repl.mode = preset.interaction
        self.preset_id = TUI_MODES[value]
        self.repl._persist_session()
        console.print(f"已切换领域模式：{value}（交互：{self.repl.mode}）")
        return True

    def run(self) -> int:
        if self.repl.session_name:
            doc = tui_sessions.load(self.repl.session_name, self.workspace)
            if doc:
                console.print(f"[green]已恢复会话 {self.repl.session_name}[/green]")
        while True:
            self.render()
            try:
                line = str(self._input("\n> ")).strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n退出")
                return 0
            if not line:
                continue
            if line.startswith("/"):
                cmd, _, rest = line.partition(" ")
                if cmd.lower() == "/agent":
                    self._agent_command(rest)
                    continue
                if self.repl._slash(line):
                    return 0
                continue
            try:
                self.repl._execute(line)
            except Exception as exc:  # noqa: BLE001 主窗口不因单轮失败退出
                console.print(f"[red]本轮失败：{type(exc).__name__}: {exc}[/red]")
        return 0


def run_tui(*, workspace: Optional[str] = None, mode: str = "",
            session_name: str = "") -> int:
    return TuiApp(workspace=workspace, mode=mode, session_name=session_name).run()


__all__ = ["TuiApp", "run_tui"]
