"""
Agent 自主蒸馏流水线 —— 把经验从"记录"自动"上升为能力"（L5 进化）。

核心理念：蒸馏的本质是把 LLM 一次性的推理结果，转化为确定性的规则/模板/
策略，下次直接复用，无需 LLM 参与。

闭环：经验库（L4）→ 蒸馏引擎（三条通道）→ 验证 → 灰度 → 上线/回滚（门禁）。

三条蒸馏通道：
  通道1 调试经验 → FIX_TEMPLATES（成熟修复固化为确定性模板）
  通道2 gap 归因 → 策略包（反复出现的高价值 gap 模式固化为 coverage_bins）
  通道3 决策效果 → 规则权重（历史有效的动作提高决策优先级）

用法:
    from src.core.distillation import DistillationOrchestrator
    orch = DistillationOrchestrator("output")
    result = orch.run()          # 扫描 → 提案 → 验证 → 落盘（不自动上线）
    result = orch.run(apply=True)  # 灰度上线（回归验证后固化）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class DistillationProposal:
    """蒸馏提案：一条经验的"能力化"建议。"""
    proposal_id: str
    channel: str                      # debug_to_fix | gap_to_policy | decision_weight
    source_experiences: List[str] = field(default_factory=list)
    content: Dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    confidence: float = 0.0
    status: str = "proposed"          # proposed → validated → grayscale → live / rolled_back
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DistillationOrchestrator:
    """蒸馏编排器：扫描 → 提案 → 验证 → 灰度 → 上线/回滚。"""

    def __init__(self, output_root: str = "output"):
        self.dir = Path(output_root) / ".signoffai" / "distillations"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = self.dir / "registry.json"
        self._registry = self._load_registry()

    # ═══════════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════════

    def scan(self) -> List[DistillationProposal]:
        """扫描三条通道，生成蒸馏提案（不落盘不应用）。"""
        proposals = []
        proposals += self._channel_debug_to_fix()
        proposals += self._channel_gap_to_policy()
        proposals += self._channel_decision_weight()
        return proposals

    def run(self, apply: bool = False) -> Dict[str, Any]:
        """完整蒸馏：扫描 → 验证 → 落盘 → （可选）灰度上线。"""
        proposals = [p for p in self.scan() if self._validate(p)]
        for p in proposals:
            p.status = "validated"
            p.created_at = datetime.now().isoformat()
            self._persist(p)
        applied = 0
        if apply:
            applied = sum(1 for p in proposals if self._grayscale_apply(p))
        return {
            "scanned": len(proposals),
            "applied": applied,
            "proposals": [p.to_dict() for p in proposals],
        }

    # ═══════════════════════════════════════════════════════════
    # 通道1：调试经验 → FIX_TEMPLATES
    # ═══════════════════════════════════════════════════════════

    def _channel_debug_to_fix(self) -> List[DistillationProposal]:
        """成熟调试经验（success>=3）蒸馏为确定性修复模板。"""
        try:
            from src.core.growth import get_mature_fixes
        except Exception:
            return []
        proposals = []
        for exp in get_mature_fixes():
            proposals.append(DistillationProposal(
                proposal_id=f"debug_to_fix_{exp.get('fingerprint', 'x')}",
                channel="debug_to_fix",
                source_experiences=[exp.get("fingerprint", "")],
                content={
                    "template": {
                        "match": [exp.get("root_cause", "")],
                        "fix_name": exp.get("fix_name", ""),
                        "description": f"蒸馏自 {exp.get('success_count', 0)} 次验证经验",
                    }
                },
                reasoning=(f"经验已稳定通过 {exp.get('success_count', 0)} 次，"
                           f"置信度 {exp.get('confidence', 0):.0%}，适合固化为修复模板"),
                confidence=round(exp.get("confidence", 0) * 0.9, 3),  # 保守
            ))
        return proposals

    # ═══════════════════════════════════════════════════════════
    # 通道2：gap 归因 → 策略包
    # ═══════════════════════════════════════════════════════════

    def _channel_gap_to_policy(self) -> List[DistillationProposal]:
        """反复出现且改善率高的 gap 模式蒸馏为策略包 coverage_bins。"""
        try:
            from src.core.growth import get_policy_evolution
        except Exception:
            return []
        proposals = []
        for e in get_policy_evolution():
            proposals.append(DistillationProposal(
                proposal_id=f"gap_to_policy_{e.get('reason', 'x')}",
                channel="gap_to_policy",
                content={
                    "coverage_bin": {
                        "name": f"learned_{e.get('reason', 'gap')}",
                        "desc": f"历史有效 gap 模式（改善率 {e.get('confidence', 0):.0%}）",
                    }
                },
                reasoning=(f"gap reason '{e.get('reason')}' 历史改善率 "
                           f"{e.get('confidence', 0):.0%}（{e.get('trials', 0)} 次验证），"
                           f"适合固化进策略包"),
                confidence=e.get("confidence", 0),
            ))
        return proposals

    # ═══════════════════════════════════════════════════════════
    # 通道3：决策效果 → 规则权重
    # ═══════════════════════════════════════════════════════════

    def _channel_decision_weight(self) -> List[DistillationProposal]:
        """历史有效的决策动作蒸馏为权重建议（提高该动作优先级）。"""
        try:
            from src.core.growth import get_action_experience
        except Exception:
            return []
        proposals = []
        for action_type in ("RELAX_CONSTRAINT", "GENERATE_DIRECTED_TEST",
                            "EXPAND_SEEDS", "REFACTOR_RTL"):
            exp = get_action_experience(action_type)
            if not exp or exp.get("trials", 0) < 2:
                continue
            if exp.get("improve_rate", 0) < 0.5:
                continue  # 只蒸馏"有效"的动作
            proposals.append(DistillationProposal(
                proposal_id=f"decision_weight_{action_type}",
                channel="decision_weight",
                content={
                    "weight": {
                        "action_type": action_type,
                        "weight": round(1.0 + exp.get("improve_rate", 0), 3),
                        "improve_rate": exp.get("improve_rate", 0),
                        "avg_delta": exp.get("avg_delta", 0),
                    }
                },
                reasoning=(f"动作 {action_type} 历史改善率 {exp.get('improve_rate', 0):.0%}"
                           f"（{exp.get('trials', 0)} 次），建议提高决策优先级"),
                confidence=exp.get("improve_rate", 0),
            ))
        return proposals

    # ═══════════════════════════════════════════════════════════
    # 验证器
    # ═══════════════════════════════════════════════════════════

    def _validate(self, proposal: DistillationProposal) -> bool:
        """验证提案：检查是否已有同 id 的 live 提案（避免重复固化）。"""
        live = self._registry.get("live", {})
        return proposal.proposal_id not in live

    # ═══════════════════════════════════════════════════════════
    # 灰度门禁：应用 / 回滚
    # ═══════════════════════════════════════════════════════════

    def _grayscale_apply(self, proposal: DistillationProposal) -> bool:
        """灰度上线：写入注册表（live），标记为已固化。回归验证失败则回滚。"""
        try:
            live = self._registry.setdefault("live", {})
            live[proposal.proposal_id] = proposal.to_dict()
            proposal.status = "live"
            self._save_registry()
            self._persist(proposal)
            return True
        except Exception:
            return False

    def rollback(self, proposal_id: str) -> bool:
        """回滚：从 live 注册表移除，标记 rolled_back。"""
        live = self._registry.get("live", {})
        if proposal_id not in live:
            return False
        prop = live.pop(proposal_id)
        prop["status"] = "rolled_back"
        self._registry.setdefault("rolled_back", {})[proposal_id] = prop
        self._save_registry()
        return True

    # ═══════════════════════════════════════════════════════════
    # 查询：运行时能力（供 auto_fix / policy_pack / decision_engine 读取）
    # ═══════════════════════════════════════════════════════════

    def get_live_templates(self) -> List[Dict[str, Any]]:
        """返回已固化的修复模板（供 auto_fix 合并）。"""
        return [p["content"]["template"] for p in
                self._registry.get("live", {}).values()
                if p.get("channel") == "debug_to_fix"]

    def get_live_policy_bins(self) -> List[Dict[str, Any]]:
        """返回已固化的策略包 coverage_bins（供 policy_pack 合并）。"""
        return [p["content"]["coverage_bin"] for p in
                self._registry.get("live", {}).values()
                if p.get("channel") == "gap_to_policy"]

    def get_live_weights(self) -> Dict[str, float]:
        """返回已固化的决策权重（供 decision_engine 读取）。"""
        weights = {}
        for p in self._registry.get("live", {}).values():
            if p.get("channel") == "decision_weight":
                w = p.get("content", {}).get("weight", {})
                if w.get("action_type"):
                    weights[w["action_type"]] = w.get("weight", 1.0)
        return weights

    # ═══════════════════════════════════════════════════════════
    # 持久化
    # ═══════════════════════════════════════════════════════════

    def _persist(self, proposal: DistillationProposal):
        p = self.dir / f"{proposal.proposal_id}.json"
        p.write_text(json.dumps(proposal.to_dict(), indent=2, ensure_ascii=False),
                     encoding="utf-8")

    def _load_registry(self) -> Dict[str, Any]:
        if self.registry_path.exists():
            try:
                return json.loads(self.registry_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save_registry(self):
        self.registry_path.write_text(
            json.dumps(self._registry, indent=2, ensure_ascii=False), encoding="utf-8")
