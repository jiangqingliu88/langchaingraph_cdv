"""
Hooks 机制 —— 生命周期钩子（对齐 Claude Code）

在 Agent 执行的关键节点前后触发自定义脚本/函数，用于:
  - 拦截危险操作
  - 修改输入
  - 验证输出
  - 记录审计日志

Hook 事件（IC 验证领域适配）:
  SessionStart / SessionEnd     会话
  PreAgent / PostAgent          Agent 执行前后
  PreToolUse / PostToolUse      工具调用前后
  PreCompile / PostCompile      编译前后
  PreSimulation / PostSimulation 仿真前后
  PreDecision / PostDecision    决策前后
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class HookResult:
    """Hook 执行结果"""
    hook_name: str
    event: str
    allowed: bool = True          # 是否允许继续
    modified_input: Any = None    # 修改后的输入（PreToolUse 可改参数）
    output: str = ""              # hook 输出（PostToolUse 可追加）
    reason: str = ""              # 阻止原因


class HookManager:
    """Hooks 管理器：注册、触发生命周期钩子"""

    def __init__(self, hooks_dir: str = "hooks"):
        self.hooks_dir = Path(hooks_dir)
        self._hooks: Dict[str, List[Callable]] = {}  # event → [handler]

    def register(self, event: str, handler: Callable):
        """注册一个 hook 处理器。"""
        self._hooks.setdefault(event, []).append(handler)

    def register_script(self, event: str, script: str):
        """注册一个脚本 hook（shell 命令）。"""
        def _run_script(*args, **kwargs):
            try:
                r = subprocess.run(script, shell=True, capture_output=True,
                                   text=True, encoding="utf-8", errors="replace",
                                   timeout=30)
                return HookResult(hook_name=script[:30], event=event,
                                  output=r.stdout, allowed=r.returncode == 0,
                                  reason=r.stderr[:200] if r.returncode != 0 else "")
            except Exception as e:
                return HookResult(hook_name=script[:30], event=event,
                                  output="", allowed=False, reason=str(e)[:200])
        self.register(event, _run_script)

    def trigger(self, event: str, *args, **kwargs) -> List[HookResult]:
        """触发某个事件的所有 hook。返回结果列表。"""
        results = []
        for handler in self._hooks.get(event, []):
            try:
                r = handler(*args, **kwargs)
                if isinstance(r, HookResult):
                    results.append(r)
                elif isinstance(r, dict):
                    results.append(HookResult(**r))
            except Exception as e:
                results.append(HookResult(hook_name=str(handler), event=event,
                                          allowed=False, reason=str(e)[:200]))
        return results

    def trigger_blocking(self, event: str, *args, **kwargs) -> Optional[HookResult]:
        """触发 hook，遇到第一个阻止的返回（阻塞语义）。"""
        for r in self.trigger(event, *args, **kwargs):
            if not r.allowed:
                return r
        return None

    def load_from_dir(self):
        """从 hooks/ 目录加载脚本 hook。"""
        if not self.hooks_dir.exists():
            return
        for script in sorted(self.hooks_dir.rglob("*.py")):
            # 约定: 文件名即事件名，如 pre_compile.py
            event = script.stem.replace("_", "_")  # pre_compile → pre_compile
            # 映射到标准事件名
            event = self._map_event(event)
            self.register_script(event, f"python {script}")

    @staticmethod
    def _map_event(name: str) -> str:
        """文件名 → 标准事件名。"""
        mapping = {
            "pre_compile": "PreCompile", "post_compile": "PostCompile",
            "pre_sim": "PreSimulation", "post_sim": "PostSimulation",
            "pre_agent": "PreAgent", "post_agent": "PostAgent",
            "pre_tool": "PreToolUse", "post_tool": "PostToolUse",
            "session_start": "SessionStart", "session_end": "SessionEnd",
        }
        return mapping.get(name, name)


# 全局单例
_global_hooks: Optional[HookManager] = None


def get_hook_manager(hooks_dir: str = "hooks") -> HookManager:
    global _global_hooks
    if _global_hooks is None:
        _global_hooks = HookManager(hooks_dir)
    return _global_hooks
