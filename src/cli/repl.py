"""
交互式 REPL —— 对齐 Claude Code 的命令体验

用法:
  vagent                    # 进入交互式 REPL
  vagent -p "prompt"        # 单次查询（非交互）
  vagent -c                 # 继续上次会话
  vagent -r <session_id>    # 恢复指定会话

Slash 命令:
  /help /clear /compact /model /memory /skills /plugins /hooks /artifacts
  /agents /verify /coverage /signoff /status /cost
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SlashCommandHandler:
    """Slash 命令处理器"""

    @staticmethod
    def policies() -> str:
        """列出设计风格策略包（design-style 驱动，差异化核心）"""
        from src.core.policy_pack import get_policy_pack_loader
        packs = get_policy_pack_loader().list()
        if not packs:
            return "无策略包"
        return "\n".join(f"  {p['design_style']}: {p['description'][:50]}" for p in packs)

    @staticmethod
    def hooks() -> str:
        from src.core.hooks import get_hook_manager
        hm = get_hook_manager()
        return "\n".join(f"  {event}: {len(handlers)} handlers"
                         for event, handlers in hm._hooks.items()) or "无 hooks"

    @staticmethod
    def artifacts() -> str:
        from src.core.artifacts import get_artifact_registry
        ar = get_artifact_registry()
        return "\n".join(f"  [{a.type}] {a.name} {a.version} (by {a.agent})"
                         for a in ar._artifacts) or "无产物"

    @staticmethod
    def agents() -> str:
        from src.core.jsonrpc import A2ADispatcher
        cards = A2ADispatcher.AGENT_CARDS
        return "\n".join(f"  {name}: {card.description}" for name, card in cards.items())

    @staticmethod
    def memory() -> str:
        from src.core.context_loader import ContextLoader
        memory = ContextLoader('.').load_project_memory()
        return memory if memory else "无 SignOffAI.md"

    @staticmethod
    def compact(session) -> str:
        """压缩会话上下文（数据级压缩 + 历史裁剪），减少 LLM context 消耗。"""
        saved = 0
        # 1. 压缩 ContextStore（数据截断，原始保留供审计）
        try:
            from src.core.context import ContextStore
            store = ContextStore()
            saved += store.compress()
        except Exception:
            pass
        # 2. 裁剪会话历史（保留最近 N 条）
        if hasattr(session, 'history') and len(session.history) > 50:
            cut = len(session.history) - 50
            session.history = session.history[-50:]
            saved += cut
        return f"上下文已压缩（节省 {saved} 项）"

    @staticmethod
    def help() -> str:
        return (
            "Slash 命令:\n"
            "  /help      帮助\n"
            "  /clear     清空会话\n"
            "  /compact   压缩上下文（减少 token 消耗）\n"
            "  /memory    项目记忆 (SignOffAI.md)\n"
            "  /policies  列出策略包（design-style）\n"
            "  /hooks     列出钩子\n"
            "  /artifacts 列出产物\n"
            "  /agents    列出 7 个 Agent\n"
            "  /status    状态\n"
            "  /exit      退出"
        )


class SessionManager:
    """会话管理：记录、恢复对话历史"""

    def __init__(self, sessions_dir: str = ".sessions"):
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.history: List[Dict] = []

    def save(self, session_id: str = None):
        """保存当前会话。"""
        sid = session_id or f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        fpath = self.sessions_dir / f"{sid}.json"
        fpath.write_text(json.dumps({
            "session_id": sid,
            "saved_at": datetime.now().isoformat(),
            "history": self.history,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        return sid

    def load(self, session_id: str) -> bool:
        """加载指定会话。"""
        fpath = self.sessions_dir / f"{session_id}.json"
        if not fpath.exists():
            return False
        data = json.loads(fpath.read_text(encoding="utf-8"))
        self.history = data.get("history", [])
        return True

    def list_sessions(self) -> List[str]:
        return [f.stem for f in self.sessions_dir.glob("*.json")]


class Repl:
    """交互式 REPL 主循环"""

    def __init__(self):
        self.sessions = SessionManager()
        self.slash = SlashCommandHandler()

    async def run_interactive(self):
        """进入交互式 REPL。"""
        print("=" * 50)
        print("SignOffAI — IC 验证平台（对齐 Claude Code 命令体验）")
        print("输入 /help 查看命令，输入 /exit 退出")
        print("=" * 50)

        while True:
            try:
                user_input = input("\n> ").strip()
            except (KeyboardInterrupt, EOFError):
                print("\n退出")
                break

            if not user_input:
                continue

            # Slash 命令
            if user_input.startswith("/"):
                await self._handle_slash(user_input)
                continue

            # 正常查询 → 走闭环
            await self._handle_query(user_input)

    async def _handle_slash(self, cmd: str):
        """处理 slash 命令。"""
        cmd = cmd.strip()
        if cmd in ("/exit", "/quit"):
            self.sessions.save()
            raise SystemExit(0)
        elif cmd == "/help":
            print(self.slash.help())
        elif cmd == "/clear":
            self.sessions.history = []
            print("会话已清空")
        elif cmd == "/compact":
            print(self.slash.compact(self.sessions))
        elif cmd == "/memory":
            print(self.slash.memory())
        elif cmd == "/policies":
            print("策略包:\n" + self.slash.policies())
        elif cmd == "/hooks":
            print("Hooks:\n" + self.slash.hooks())
        elif cmd == "/artifacts":
            print("Artifacts:\n" + self.slash.artifacts())
        elif cmd == "/agents":
            print("Agents:\n" + self.slash.agents())
        elif cmd == "/status":
            print(f"会话历史: {len(self.sessions.history)} 条")
        else:
            print(f"未知命令: {cmd}（输入 /help 查看）")

    async def _handle_query(self, query: str):
        """处理正常查询：走七 Agent 闭环。"""
        print(f"🔍 处理: {query}")

        # 调用闭环
        try:
            from src.core.execution import PipelineExecutionService
            svc = PipelineExecutionService.get_instance()
            result = await svc.run_closed_loop(query, output_root="output/repl")
            cov = result.get("final_coverage", 0)
            print(f"  ✅ 闭环完成: 覆盖率 {cov}%, 收敛={result.get('converged')}")
        except Exception as e:
            print(f"  ❌ 执行失败: {str(e)[:200]}")

        self.sessions.history.append({"query": query, "time": datetime.now().isoformat()})


def run_once(prompt: str):
    """单次查询（非交互 -p 模式）。"""
    import asyncio
    repl = Repl()
    asyncio.run(repl._handle_query(prompt))


def run_interactive():
    """启动交互式 REPL。"""
    import asyncio
    repl = Repl()
    asyncio.run(repl.run_interactive())
