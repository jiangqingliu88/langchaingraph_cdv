"""
CoverageMap —— 验证空间覆盖地图（bin 级覆盖状态，对应自动驾驶的"定位层"）。

自动驾驶靠 GPS + 高精地图精确知道"我在哪个车道的哪个位置"，SignOffAI 靠
覆盖地图精确知道"哪个 bin 命中、哪个 bin 没命中、缺口在验证空间的哪个坐标"。

与 gap 向量（reason 维度粗定位）的区别：覆盖地图是 bin 级精确坐标——
不是"constraint 缺口"，而是"opcode[31:16] 的 toggle 未命中"。

用法:
    from src.orchestration_plane.l2.coverage_map import CoverageMap
    cm = CoverageMap()
    map_data = cm.build(nested_cov, toggle_details, functional_detail)
    # → {bins, covered, total, coverage, uncovered_bins}
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


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
            {bins, covered, total, coverage, uncovered_bins, metrics_clean}

        `total` / `covered` 是**bin 数**（不是条目数）—— 于是 `coverage` 是一个真
        百分比，能拿去跟覆盖率目标比（见下）。
        """
        bins: List[Dict[str, Any]] = []

        # 1. 代码覆盖率 bin（metric 级）
        #    每个 metric 一条，但**带上它的 bin 总数**：这条既是"这个 metric 干净吗"
        #    的判据（`hit`），也是加权求百分比的分子分母（`bins`/`covered`）。
        #    hit 判据必须区分「真收集到且 0 miss」与「空数据（无 bin）」：
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
                "bins": bins_n, "covered": max(bins_n - misses, 0),
                "pct": round(pct, 1) if bins_n > 0 else 0.0,
            })

        # 2. toggle 明细 bin（signal 级精确位置）
        #
        # ⚠️ **没采到 toggle 就不该把它算进分母**。
        #
        # 这段无条件按 `toggle_details` 造 bin，而 toggle_details 是从 ucdb 里
        # **声明过的信号**里读的 —— 与"这次编译有没有采 toggle"无关。于是
        # toggle 没采的那些 run 里，这些 bin 全是 miss，把总分母撑大、
        # 把 `coverage`（= Σcovered/Σbins）压下去。
        #
        # 后果实测：`effective_coverage` 47.3%，而同一轮的**功能覆盖率是 56.2%** ——
        # 而 `converged` 正是拿 `effective_coverage >= target` 判的（lifecycle.py），
        # 于是收敛**永远达不到**。这与上面注释里记的那次"拿 metric 干净数去比 95%"
        # 是同一类病：**把"没测"当成"没覆盖"**。
        # 判据用覆盖率解析自己报出来的 `metrics_absent`（见 collect_real_coverage）。
        _absent = {str(x) for x in (nested_cov.get("metrics_absent") or [])}
        _toggle_collected = "toggle" not in _absent
        if not _toggle_collected and toggle_details:
            logger.info(f"toggle 覆盖率本次未采集（metrics_absent 里有 toggle）—— "
                        f"{len(toggle_details)} 条 toggle bin **不计入分母**："
                        f"「没测」不是「没覆盖」")
        for td in (toggle_details or []) if _toggle_collected else []:
            signal = td.get("signal", "")
            hi, lo = td.get("high", 0), td.get("low", 0)
            misses = td.get("misses", 0) or 0
            total_td = (td.get("total") or misses or 1)
            loc = f"{signal}[{hi}:{lo}]" if hi != lo else signal
            bins.append({
                "type": "toggle", "signal": signal, "purpose": "corner",
                "location": loc,
                "hit": misses == 0, "misses": misses,
                "bins": total_td, "covered": max(total_td - misses, 0),
            })

        # 3. 功能覆盖率 bin（covergroup 级）
        #    **按 covergroup bin 加权**，不再是"covergroup 级 100% 才算命中"：
        #    后者把"3 个 covergroup 里 2 个盖满"压成一个布尔，粒度太粗。
        functional_pct = nested_cov.get("functional_pct", 0) or 0
        f_total = 0
        f_hit = 0
        if isinstance(functional_detail, dict):
            f_total = int(functional_detail.get("bin_total", 0) or 0)
            f_hit = int(functional_detail.get("bin_hits", 0) or 0)
        bins.append({
            "type": "functional", "metric": "covergroup", "purpose": "functional",
            "location": "functional.covergroup",
            "hit": functional_pct >= 100, "misses": max(f_total - f_hit, 0),
            "bins": f_total, "covered": f_hit,
            "pct": round(functional_pct, 1),
        })

        # ── 汇总 ──
        #
        # **两个数，含义不同，都要**：
        #
        #   · `coverage` —— **按 bin 加权**的百分比：`Σcovered / Σbins`。
        #     这是"盖了多少"，能直接跟覆盖率目标比。
        #   · `metrics_clean` —— **每个 metric 都盖满**才算 true。
        #     这是比 95% 严格得多的信号，留着作证据（当初用"条目计数"就是为了
        #     不被空数据骗，那个用意保留在这个布尔上）。
        #
        # 曾经只留了后者、还把它当百分比用：7 个条目里干净 1 个 → 14.3%，
        # 而真实覆盖率是 96% —— 拿"几个 metric 干净"去比"95% 覆盖率目标"，
        # 结果**永远收敛不了**（实测跑满轮次仍是 NO）。
        total = sum(int(b.get("bins", 0) or 0) for b in bins)
        covered = sum(int(b.get("covered", 0) or 0) for b in bins)
        counted = [b for b in bins if int(b.get("bins", 0) or 0) > 0]
        clean = sum(1 for b in counted if b["hit"])
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
            "metrics_clean": bool(counted) and clean == len(counted),
            "metrics_clean_ratio": round(clean / len(counted), 3) if counted else 0.0,
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
