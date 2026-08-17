"""
CoverageMap —— 验证空间覆盖地图（bin 级覆盖状态，对应自动驾驶的"定位层"）。

自动驾驶靠 GPS + 高精地图精确知道"我在哪个车道的哪个位置"，SignOffAI 靠
覆盖地图精确知道"哪个 bin 命中、哪个 bin 没命中、缺口在验证空间的哪个坐标"。

与 gap 向量（reason 维度粗定位）的区别：覆盖地图是 bin 级精确坐标——
不是"constraint 缺口"，而是"opcode[31:16] 的 toggle 未命中"。

用法:
    from src.layers.l2_orchestration.coverage_map import CoverageMap
    cm = CoverageMap()
    map_data = cm.build(nested_cov, toggle_details, functional_detail)
    # → {bins, covered, total, coverage, uncovered_bins}
"""
from __future__ import annotations

from typing import Any, Dict, List


# metric → purpose 映射（对应 L0 验证目标）
_METRIC_PURPOSE = {
    "line": "functional", "statement": "functional",
    "branch": "protocol", "condition": "protocol",
    "toggle": "corner", "fsm": "corner",
}


class CoverageMap:
    """bin 级覆盖地图：语义位置 + 命中状态。"""

    def build(self, nested_cov: Dict[str, Any],
              toggle_details: List[Dict] = None,
              functional_detail: Dict = None) -> Dict[str, Any]:
        """聚合代码/功能/toggle 覆盖率成覆盖地图。

        Args:
            nested_cov: 代码覆盖率（line/branch/toggle/... + *_bins/*_misses）
            toggle_details: signal 级 toggle 缺口（parse_toggle_details 输出）
            functional_detail: 功能覆盖率（_parse_cvg_text 输出）

        Returns:
            {bins, covered, total, coverage, uncovered_bins}
        """
        bins: List[Dict[str, Any]] = []

        # 1. 代码覆盖率 bin（metric 级）
        #    hit 判定必须区分「真收集到且 0 miss」与「空数据（无 bin）」：
        #    空数据时 *_bins==0 且 misses==0，若只看 misses==0 会把空数据误判成全覆盖
        #    （历史上伪造出 6/7=85.7% 的假覆盖率）。故要求 bins>0 才算命中。
        for metric, purpose in _METRIC_PURPOSE.items():
            pct = nested_cov.get(f"{metric}_pct", 0) or 0
            misses = nested_cov.get(f"{metric}_misses", 0) or 0
            bins_n = nested_cov.get(f"{metric}_bins", 0) or 0
            bins.append({
                "type": "code", "metric": metric, "purpose": purpose,
                "location": f"code.{metric}",
                "hit": bins_n > 0 and misses == 0, "misses": misses,
                "pct": round(pct, 1) if bins_n > 0 else 0.0,
            })

        # 2. toggle 明细 bin（signal 级精确位置）
        for td in (toggle_details or []):
            signal = td.get("signal", "")
            hi, lo = td.get("high", 0), td.get("low", 0)
            misses = td.get("misses", 0) or 0
            loc = f"{signal}[{hi}:{lo}]" if hi != lo else signal
            bins.append({
                "type": "toggle", "signal": signal, "purpose": "corner",
                "location": loc,
                "hit": misses == 0, "misses": misses,
            })

        # 3. 功能覆盖率 bin（covergroup 级）
        functional_pct = nested_cov.get("functional_pct", 0) or 0
        bins.append({
            "type": "functional", "metric": "covergroup", "purpose": "functional",
            "location": "functional.covergroup",
            "hit": functional_pct >= 100, "misses": 0, "pct": round(functional_pct, 1),
        })

        # 汇总
        covered = sum(1 for b in bins if b["hit"])
        total = len(bins)
        uncovered = [b for b in bins if not b["hit"]]
        # 按 purpose 聚合未覆盖缺口
        by_purpose: Dict[str, List[Dict]] = {}
        for b in uncovered:
            by_purpose.setdefault(b["purpose"], []).append(b)

        return {
            "bins": bins,
            "covered": covered,
            "total": total,
            "coverage": round(covered / total * 100, 1) if total else 0.0,
            "uncovered_bins": uncovered,
            "uncovered_by_purpose": {p: len(v) for p, v in by_purpose.items()},
        }

    def locate_uncovered(self, map_data: Dict[str, Any],
                         purpose: str = None) -> List[Dict[str, Any]]:
        """定位未覆盖的 bin（可按 purpose 过滤），供决策层精准补漏。"""
        uncovered = map_data.get("uncovered_bins", [])
        if purpose:
            uncovered = [b for b in uncovered if b.get("purpose") == purpose]
        return uncovered
