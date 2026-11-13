"""
统一上下文加载器 —— 整合 SignOffAI.md + 策略包 + Hooks

Agent 初始化时调用，加载:
  1. SignOffAI.md   项目级记忆（类似 CLAUDE.md，自动加载）
  2. policies/      设计风格策略包（design-style 驱动，差异化核心）
  3. hooks/         生命周期钩子

（原 skills/plugins 通用层已删除，统一到策略包。）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


class ContextLoader:
    """统一上下文加载器"""

    def __init__(self, project_root: str = "."):
        self.project_root = Path(project_root)

    # ── 1. 项目级记忆（SignOffAI.md）──

    def load_project_memory(self) -> str:
        """加载 SignOffAI.md（项目根目录）。"""
        md = self.project_root / "SignOffAI.md"
        if md.exists():
            return md.read_text(encoding="utf-8", errors="replace")
        return ""

    # ── 2. 策略包（design-style 驱动，差异化核心）──

    def load_policies(self) -> List[Dict[str, str]]:
        """列出所有设计风格策略包。"""
        from src.orchestration_plane.l2.governance.policy_pack import get_policy_pack_loader
        return get_policy_pack_loader().list()

    # ── 3. Hooks ──

    def load_all_hooks(self) -> List[str]:
        """收集 hooks 目录。"""
        hooks_dir = self.project_root / "hooks"
        return [str(hooks_dir)] if hooks_dir.exists() else []

    # ── 4. 生成完整上下文 ──

    def build_context(self, design_style: str = "baseline") -> Dict[str, Any]:
        """生成完整上下文：项目记忆 + 策略包。"""
        from src.orchestration_plane.l2.governance.policy_pack import get_policy_pack_loader
        pack = get_policy_pack_loader().load(design_style)
        return {
            "project_memory": self.load_project_memory(),
            "design_style": design_style,
            "policies": self.load_policies(),
            "active_policy": pack.to_dict() if pack else None,
        }


# 全局单例
_global_loader: Optional[ContextLoader] = None


def get_context_loader(project_root: str = ".") -> ContextLoader:
    global _global_loader
    if _global_loader is None:
        _global_loader = ContextLoader(project_root)
    return _global_loader
