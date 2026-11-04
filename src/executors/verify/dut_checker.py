"""DUT 逐拍检查规则 + 逐条 SB 收口归属（`env_cov_bins.yaml#dut_checker`）。

**真 pass 的"比对"那一半**：断言那半由 SVA 承担（bind 进 DUT），这一半在 env
的覆盖率组件里逐拍求值**同一组规则**，把结论收口成 `matched=… mismatched=…`。

同一份规则、两个执行点 —— 规则来自 case 模型的 `assertions:`，各写一份必然漂。
逐条 SB 的归属来自模型的 `scoreboards[].rules`：**声明了且名字对得上**才发
`[SCB <id>]` 行，不猜（猜错就是假的逐条证据）。
"""
from __future__ import annotations

from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


def build_dut_checker(decls: Dict[str, Any],
                      meta: Dict[str, Any]) -> Dict[str, Any]:
    """模型 `assertions` → env 逐拍检查规则（失败给 `{}`，不编规则）。"""
    try:
        from src.tools.generation.casemodel_tools.coverage import checker_rules
        got = checker_rules(decls.get("assertions"), meta.get("signals") or [])
        for skipped in got["skipped"]:
            logger.warning(f"DUT 检查跳过：{skipped}")
        if not got["rules"]:
            return {}
        logger.info(f"DUT 检查：{len(got['rules'])} 条规则由 env 组件逐拍求值"
                    f"（收口打印 matched/mismatched → 真 pass 的比对半边）")
        patch = {"rules": got["rules"], "skipped": got["skipped"],
                 "clock": meta.get("clock", "clk"),
                 "reset": meta.get("reset", "rst_n")}
        per_sb = _per_sb_rules(decls.get("scoreboards"), got["rules"])
        if per_sb:
            patch["scoreboards"] = per_sb
            logger.info(f"DUT 检查：{len(per_sb)} 条 scoreboard 逐条收口"
                        f"（{', '.join(sb['id'] for sb in per_sb)}）")
        return {"dut_checker": patch}
    except Exception as e:                             # noqa: BLE001 旁路
        logger.warning(f"DUT 检查规则生成失败（本轮没有比对收口）: {e}")
        return {}


def _per_sb_rules(scoreboards: Any,
                  rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """模型的 `scoreboards[].rules` → `[{id, rules}]`（名字必须真对得上）。

    `evidence: aggregate` 的 SB 明确只要聚合行，不给它发逐条行；声明了但名字
    对不上（规则被跳过 / 拼错）的条目也不发 —— 静默忽略会让签核看到一行
    "这条 SB 一条规则都没数"却以为比过了。
    """
    from src.layers.l3_decision.case_ir.ir_core import scb_id_of

    known = {str(r.get("name") or "") for r in rules or []}
    out: List[Dict[str, Any]] = []
    for sb in scoreboards or []:
        if not isinstance(sb, dict):
            continue
        sb_id = scb_id_of(sb.get("id") or sb.get("name") or "")
        if not sb_id or str(sb.get("evidence") or "auto").lower() == "aggregate":
            continue
        owned = [str(n) for n in (sb.get("rules") or []) if str(n) in known]
        if not owned:
            continue
        out.append({"id": sb_id, "rules": owned})
    return out


__all__ = ["build_dut_checker"]
