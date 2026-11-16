"""交互式长循环 agent —— 对齐 Claude Code 的使用体验。

用法:
  vagent                     # 进入 REPL
  vagent -p "任务"           # 单次执行（非交互，失败返回非零）
  vagent -c                  # 继续最近一次会话
  vagent -r <session_id>     # 恢复指定会话

REPL 的每次输入都是一个 turn；agent 直接在当前工程里读/改/跑 EDA。
Slash 命令:
  /help /mode [chat|plan|verify] /status /session
  /approve [y|n] /deny /answer <text> /plan <text> /exit

TUI 与 PySide6 UI 是**同一种交互前端**：都按 chat / plan / verify 区分任务。
`verify` 走确定性验证主链，`plan` 走待人工审批的计划候选，`chat` 只对话。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

MODES = ("chat", "plan", "verify")

#: plan 模式的 agent config —— 与 `modes.interaction` 的口径一致
PLAN_CONFIG = {
    "plan_first": True,
    "require_plan_approval": True,
    "require_exec_approval": True,
}

HELP = """Slash 命令:
  /mode [chat|plan|verify]  查看/切换交互模式（默认 chat）
  /md [list|show|edit]      浏览 / 查看 / 编辑 Markdown 产物
  /help            帮助
  /status          当前模式与会话状态（目标/子目标/改动/证据）
  /session         当前会话 ID
  /approve [y|n]   批准/拒绝挂起的人审（默认 y）
  /deny            拒绝挂起的人审
  /answer <text>   回答 agent 的 ask_user
  /plan <text>     给挂起的计划审批提交替代计划
  /exit            退出
"""


def _service():
    from src.workbench.api import agent_mode_service as agent_service
    return agent_service


def _workspace_root(workspace: Optional[str]) -> str:
    svc = _service()
    return str(svc.resolve_project_root(workspace))


def _print_result(result: Dict[str, Any], *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(result, ensure_ascii=False, default=str))
        return
    _service().render(result)


def run_once(prompt: str, *, workspace: Optional[str] = None,
             json_output: bool = False, mode: str = "agent") -> int:
    """单次任务；返回进程退出码（0 成功，1 失败/阻塞，130 取消）。"""
    if str(mode).lower() in ("verify", "engine"):
        from src.workbench.modes import router
        try:
            result = router.run(prompt, mode="verify")
        except Exception as exc:               # noqa: BLE001 失败要非零退出
            print(f"verify failed: {exc}", file=sys.stderr)
            return 1
        if json_output:
            print(json.dumps(result, ensure_ascii=False, default=str))
        else:
            router.render(result, "verify")
        return router.exit_code(result, "verify")
    if json_output:
        try:
            from src.orchestration_plane.kernel.middleware.debug_logger import (
                ExecutionTracer,
            )
            ExecutionTracer().disable()      # 别让 [llm] 预览污染 stdout JSON
        except Exception:                    # noqa: BLE001
            pass
    svc = _service()
    result = svc.agent_turn(prompt, workspace=workspace)
    _print_result(result, as_json=json_output)
    if result.get("status") == "paused" and not json_output:
        print("  会话已暂停；用 `vagent -r <session_id>` 恢复并审批。")
    return int(result.get("exit_code") or 0)


class Repl:
    def __init__(self, *, workspace: Optional[str] = None,
                 session_id: Optional[str] = None, mode: str = "chat",
                 session_name: str = "", agent_mode: str = ""):
        self.svc = _service()
        self.workspace = _workspace_root(workspace)
        self.session_id = session_id or ""
        self.session_name = str(session_name or "").strip()
        self.agent_mode = str(agent_mode or "").strip()
        self.mode = mode if mode in MODES else "chat"
        if self.session_name:
            from . import tui_sessions
            doc = tui_sessions.load(self.session_name, self.workspace)
            if doc:
                self.session_id = self.session_id or str(doc.get("session_id") or "")
                saved_mode = str(doc.get("mode") or "")
                if saved_mode in MODES and mode == "chat":
                    self.mode = saved_mode
                self.agent_mode = self.agent_mode or str(doc.get("agent_mode") or "")

    def _persist_session(self) -> None:
        """把名字索引写到 `chipstack_artifacts/tui/sessions/`（手册 §3）。"""
        if not self.session_name or not self.session_id:
            return
        try:
            from . import tui_sessions
            tui_sessions.save(self.session_name, session_id=self.session_id,
                              mode=self.mode, workspace=self.workspace,
                              agent_mode=self.agent_mode)
        except OSError as exc:
            print(f"（会话索引写入失败：{exc}）")

    # ── slash ────────────────────────────────────────────────────────────

    def _load_session(self):
        if not self.session_id:
            return None
        from src.runtime_plane.session import Session
        from src.runtime_plane.workspace_manager import WorkspaceZones
        try:
            zones = WorkspaceZones.direct_mode(self.workspace)
            return Session.load(zones, self.session_id)
        except (OSError, ValueError):
            return None

    def _status(self) -> None:
        print(f"mode={self.mode}")
        session = self._load_session()
        if session is None:
            print("尚无会话")
            return
        proj = session.projection()
        print(f"session={proj['session_id']}  state={proj['state']}  "
              f"round={proj['round']}  step={proj['step']}")
        print(f"task={proj['task']}")
        if proj.get("plan"):
            print(f"plan={proj['plan'][:300]}")
        if proj.get("changed_files"):
            print("changed:")
            for row in proj["changed_files"][:20]:
                print(f"  {row.get('action', '?'):7} {row.get('path')}")
        if proj.get("pending"):
            print(f"pending={proj['pending']}")
        if proj.get("last_error"):
            print(f"last_error={proj['last_error']}")

    def _resume(self, **kwargs) -> None:
        if not self.session_id:
            print("尚无会话可恢复")
            return
        result = self.svc.resume_turn(self.session_id, workspace=self.workspace,
                                      **kwargs)
        _print_result(result)
        self.session_id = result.get("session_id") or self.session_id
        self._persist_session()

    def _slash(self, line: str) -> bool:
        """返回 True 表示退出。"""
        parts = line.strip().split(maxsplit=1)
        cmd, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        if cmd in ("/exit", "/quit"):
            return True
        if cmd == "/help":
            print(HELP)
        elif cmd == "/mode":
            value = rest.strip().lower()
            if not value:
                print(f"当前模式：{self.mode}（可用：{' / '.join(MODES)}）")
            elif value not in MODES:
                print(f"未知模式：{value}（可用：{' / '.join(MODES)}）")
            else:
                self.mode = value
                self._persist_session()
                print(f"已切换模式：{value}"
                      + ("；下一轮进入确定性验证主链" if value == "verify"
                         else "；计划候选需要人工审批" if value == "plan" else ""))
        elif cmd == "/md":
            self._markdown(rest)
        elif cmd == "/status":
            self._status()
        elif cmd == "/session":
            print(self.session_id or "尚无会话")
        elif cmd == "/approve":
            approve = rest.strip().lower() not in ("n", "no", "false", "0")
            self._resume(approve=approve)
        elif cmd == "/deny":
            self._resume(approve=False)
        elif cmd == "/answer":
            self._resume(answer=rest)
        elif cmd == "/plan":
            self._resume(approve=True, plan=rest)
        elif cmd == "/compact":
            print("上下文压缩在每次工具结果后自动进行；长会话会保留最近消息。")
        else:
            print(f"未知命令: {cmd}（输入 /help 查看）")
        return False

    # ── Markdown 产物（TUI 侧浏览/编辑）────────────────────────────────

    def _markdown(self, rest: str) -> None:
        """`/md list|show|edit [path]` —— 与 PySide6「Markdown 产物」同一批文件。

        TUI 不内嵌富文本编辑器：`edit` 交给系统默认程序打开，保存后回到这里
        刷新即可。路径必须落在 workspace 内。
        """
        parts = rest.strip().split(maxsplit=1)
        action = (parts[0].lower() if parts else "list")
        arg = parts[1].strip() if len(parts) > 1 else ""
        root = Path(self.workspace).resolve()
        if action == "list":
            base = self._md_path(arg or ".", root)
            if base is None:
                return
            files = sorted(base.rglob("*.md"))[:200] if base.is_dir() else [base]
            if not files:
                print("没有 Markdown 文件")
                return
            for path in files:
                try:
                    print(" ", path.relative_to(root).as_posix())
                except ValueError:
                    print(" ", path)
            return
        if not arg:
            print("用法：/md list [dir] | /md show <path> | /md edit <path>")
            return
        target = self._md_path(arg, root)
        if target is None:
            return
        if not target.is_file():
            print(f"文件不存在：{target}")
            return
        if action == "show":
            try:
                lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError as exc:
                print(f"读不了：{exc}")
                return
            print("\n".join(lines[:200]))
            if len(lines) > 200:
                print(f"… 共 {len(lines)} 行，只显示前 200 行")
            return
        if action == "edit":
            try:
                if sys.platform.startswith("win"):
                    os.startfile(str(target))            # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.run(["open", str(target)], check=False)
                else:
                    subprocess.run(["xdg-open", str(target)], check=False)
            except OSError as exc:
                print(f"打不开系统编辑器：{exc}")
                return
            print(f"已交给系统程序打开：{target}")
            return
        print(f"未知 /md 动作：{action}（可用 list / show / edit）")

    @staticmethod
    def _md_path(raw: str, root: Path) -> Optional[Path]:
        target = (root / raw).resolve() if not Path(raw).is_absolute() else Path(raw).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            print(f"路径在 workspace 之外：{target}")
            return None
        return target

    # ── 执行 ────────────────────────────────────────────────────────────

    def _execute(self, line: str) -> None:
        """按当前模式跑一轮 —— chat/plan 走 Harness，verify 走确定性主链。"""
        if self.mode == "verify":
            from src.workbench.modes import router
            try:
                result = router.run(line, mode="verify")
            except Exception as exc:             # noqa: BLE001 终端入口给可读错误
                print(f"verify failed: {exc}", file=sys.stderr)
                return
            router.render(result, "verify")
            print(f"exit_code={router.exit_code(result, 'verify')}")
            return

        config = dict(PLAN_CONFIG) if self.mode == "plan" else {"require_exec_approval": True}
        if self.agent_mode:
            from src.workbench.modes.agent_modes import get_mode
            preset = get_mode(self.agent_mode)
            if preset.role_prompt:
                config["role_prompt"] = preset.role_prompt
        result = self.svc.agent_turn(line, workspace=self.workspace,
                                     session_id=self.session_id or None,
                                     config=config)
        _print_result(result)
        self.session_id = result.get("session_id") or self.session_id
        self._persist_session()
        if result.get("status") == "paused":
            print("  会话已暂停；用 /approve、/deny 或 /plan，或 `vagent -r <session_id>`。")

    # ── 主循环 ────────────────────────────────────────────────────────────

    def run(self) -> int:
        print("=" * 56)
        print("SignOffAI — 交互前端（PySide6 UI / TUI 共用同一套模式）")
        agent = f"  agent: {self.agent_mode}" if self.agent_mode else ""
        print(f"workspace: {self.workspace}  mode: {self.mode}{agent}")
        print("输入任务开始；/mode 切换 chat/plan/verify，/help 查看命令，/exit 退出")
        print("=" * 56)
        while True:
            try:
                line = input("\n> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n退出")
                return 0
            if not line:
                continue
            if line.startswith("/"):
                if self._slash(line):
                    return 0
                continue

            # verify 是一次性执行，没有 Harness 会话，不参与审批恢复
            if self.mode != "verify":
                session = self._load_session()
                if session is not None and session.state == "paused":
                    pending = session.pending or {}
                    if pending.get("kind") == "answer":
                        self._resume(answer=line)
                        continue
                    print(f"会话在等待审批（{pending.get('kind')}）；"
                          "用 /approve、/deny 或 /plan。")
                    continue

            self._execute(line)


def run_interactive(session_id: Optional[str] = None,
                    continue_latest: bool = False,
                    workspace: Optional[str] = None,
                    mode: str = "chat",
                    session_name: str = "",
                    agent_mode: str = "") -> int:
    repl = Repl(workspace=workspace, session_id=session_id, mode=mode,
                session_name=session_name, agent_mode=agent_mode)
    if continue_latest and not repl.session_id:
        from src.runtime_plane.workspace_manager import WorkspaceZones
        zones = WorkspaceZones.direct_mode(repl.workspace)
        repl.session_id = _service().last_session(zones)
        if repl.session_id:
            print(f"已继续会话 {repl.session_id}")
        else:
            print("无可继续的会话，已启动新会话")
    elif repl.session_id:
        if repl._load_session() is None:
            print(f"错误：找不到会话 {session_id}", file=sys.stderr)
            return 1
        print(f"已恢复会话 {repl.session_id}")
    return repl.run()
