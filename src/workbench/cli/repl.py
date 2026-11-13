"""交互式长循环 agent —— 对齐 Claude Code 的使用体验。

用法:
  vagent                     # 进入 REPL
  vagent -p "任务"           # 单次执行（非交互，失败返回非零）
  vagent -c                  # 继续最近一次会话
  vagent -r <session_id>     # 恢复指定会话

REPL 的每次输入都是一个 turn；agent 直接在当前工程里读/改/跑 EDA。
Slash 命令:
  /help /status /session /approve [y|n] /deny /answer <text> /plan <text> /exit
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional

HELP = """Slash 命令:
  /help            帮助
  /status          当前会话状态（目标/子目标/改动/证据）
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
            from src.orchestration_plane.l2.middleware.debug_logger import (
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
                 session_id: Optional[str] = None):
        self.svc = _service()
        self.workspace = _workspace_root(workspace)
        self.session_id = session_id or ""

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

    def _slash(self, line: str) -> bool:
        """返回 True 表示退出。"""
        parts = line.strip().split(maxsplit=1)
        cmd, rest = parts[0].lower(), (parts[1] if len(parts) > 1 else "")
        if cmd in ("/exit", "/quit"):
            return True
        if cmd == "/help":
            print(HELP)
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

    # ── 主循环 ────────────────────────────────────────────────────────────

    def run(self) -> int:
        print("=" * 56)
        print("SignOffAI — 长循环验证 agent（直接在当前工程工作）")
        print(f"workspace: {self.workspace}")
        print("输入任务开始；/help 查看命令，/exit 退出")
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

            session = self._load_session()
            if session is not None and session.state == "paused":
                pending = session.pending or {}
                if pending.get("kind") == "answer":
                    self._resume(answer=line)
                    continue
                print(f"会话在等待审批（{pending.get('kind')}）；"
                      "用 /approve、/deny 或 /plan。")
                continue

            result = self.svc.agent_turn(line, workspace=self.workspace,
                                         session_id=self.session_id or None)
            _print_result(result)
            self.session_id = result.get("session_id") or self.session_id


def run_interactive(session_id: Optional[str] = None,
                    continue_latest: bool = False,
                    workspace: Optional[str] = None) -> int:
    repl = Repl(workspace=workspace, session_id=session_id)
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
