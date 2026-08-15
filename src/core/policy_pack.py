"""
策略包（Policy Pack）—— 设计风格验证知识，差异化于 Claude Code Skill 的领域语义。

与 Skill 的本质差异（三层差异化）：
  1. 命名：策略包（Policy Pack）承载"测什么设计"的风格知识，不是"怎么验证"的通用技巧
  2. 语义：内容是结构化的验证知识（测试场景 / 覆盖点 / 断言模板 / 编译选项），
          而非自由文本的 SKILL.md
  3. 机制：按 `--design-style` 驱动加载（design-style → 策略包），
          而非按任务文本匹配（task_text → skill）

用法:
    from src.core.policy_pack import get_policy_pack_loader
    loader = get_policy_pack_loader()
    pack = loader.load("pipeline")               # 按设计风格加载
    prompt = loader.apply_to_prompt("pipeline", base_prompt)  # 注入验证知识
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

DEFAULT_DESIGN_STYLE = "baseline"


@dataclass
class PolicyPack:
    """一个设计风格的验证策略包。"""
    design_style: str
    description: str = ""
    prompt_hints: str = ""                 # 注入 verify agent prompt 的领域知识
    test_scenarios: List[Dict] = field(default_factory=list)   # [{name, desc}]
    coverage_bins: List[Dict] = field(default_factory=list)    # [{name, desc}]
    assertion_templates: List[Dict] = field(default_factory=list)  # [{name, desc}]
    compile_options: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "design_style": self.design_style,
            "description": self.description,
            "prompt_hints": self.prompt_hints,
            "test_scenarios": self.test_scenarios,
            "coverage_bins": self.coverage_bins,
            "assertion_templates": self.assertion_templates,
            "compile_options": self.compile_options,
        }


class PolicyPackLoader:
    """按 design-style 加载策略包（不是按任务匹配）。"""

    def __init__(self, policies_dir: str = "policies"):
        self.policies_dir = Path(policies_dir)
        self._cache: Dict[str, PolicyPack] = {}

    def load(self, design_style: str) -> Optional[PolicyPack]:
        """按设计风格加载策略包。未命中则回退 baseline。加载时叠加 L5 进化经验。"""
        style = design_style or DEFAULT_DESIGN_STYLE
        if style in self._cache:
            return self._cache[style]
        pack = self._parse(style)
        if pack is None and style != DEFAULT_DESIGN_STYLE:
            pack = self._parse(DEFAULT_DESIGN_STYLE)  # 回退默认
        if pack:
            self._apply_growth(pack)  # L5 进化：历史有效 gap 模式追加进覆盖点
            self._cache[style] = pack
        return pack

    def _apply_growth(self, pack: PolicyPack) -> None:
        """L5 进化：把历史验证有效的 gap 模式，追加进策略包 coverage_bins。

        这是"经验 → 策略"的蒸馏通道——项目 A 学到的有效 gap 归因，
        迁移到项目 B 的同类设计风格策略包，无需人工追加。
        """
        try:
            from src.core.growth import get_policy_evolution
            for e in get_policy_evolution():
                pack.coverage_bins.append({
                    "name": f"learned_{e.get('reason', 'gap')}",
                    "desc": f"历史有效 gap 模式（改善率 {e.get('confidence', 0):.0%}，{e.get('trials', 0)} 次验证）",
                })
        except Exception:
            pass

    def _parse(self, design_style: str) -> Optional[PolicyPack]:
        # 支持 policy.yaml / policy.yml / manifest.yaml
        for fname in ("policy.yaml", "policy.yml", "manifest.yaml"):
            p = self.policies_dir / design_style / fname
            if p.exists():
                return self._parse_yaml(p, design_style)
        return None

    def _parse_yaml(self, path: Path, design_style: str) -> PolicyPack:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        except Exception:
            data = {}
        return PolicyPack(
            design_style=data.get("design_style", design_style),
            description=data.get("description", ""),
            prompt_hints=data.get("prompt_hints", ""),
            test_scenarios=data.get("test_scenarios", []),
            coverage_bins=data.get("coverage_bins", []),
            assertion_templates=data.get("assertion_templates", []),
            compile_options=data.get("compile_options", []),
        )

    def list(self) -> List[Dict[str, str]]:
        """列出所有可用策略包（design_style + description）。"""
        if not self.policies_dir.exists():
            return []
        result = []
        for d in sorted(self.policies_dir.iterdir()):
            if not d.is_dir():
                continue
            pack = self.load(d.name)
            if pack:
                result.append({"design_style": pack.design_style,
                               "description": pack.description})
        return result

    # ── 注入到 prompt / 配置 ──

    def apply_to_prompt(self, design_style: str, base_prompt: str) -> str:
        """把策略包的验证知识注入到 prompt（领域语义）。"""
        pack = self.load(design_style)
        if not pack or not (pack.prompt_hints or pack.test_scenarios):
            return base_prompt
        lines = [base_prompt, "", f"═══════ 设计风格策略（{pack.design_style}）═══════"]
        if pack.prompt_hints:
            lines.append(pack.prompt_hints)
        if pack.test_scenarios:
            lines.append("必须覆盖的场景:")
            for s in pack.test_scenarios:
                lines.append(f"  - {s.get('name', '')}: {s.get('desc', '')}")
        lines.append("══════════════════════════════════")
        return "\n".join(lines)

    def get_compile_options(self, design_style: str) -> List[str]:
        pack = self.load(design_style)
        return pack.compile_options if pack else []


# 全局单例
_global_loader: Optional[PolicyPackLoader] = None


def get_policy_pack_loader(policies_dir: str = "policies") -> PolicyPackLoader:
    global _global_loader
    if _global_loader is None:
        _global_loader = PolicyPackLoader(policies_dir)
    return _global_loader
