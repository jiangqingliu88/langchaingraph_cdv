"""覆盖率豁免（Exclude）的审批面 —— 给界面用的薄壳。

**为什么要有这一层。** `ExcludeRegistry` 本身是齐的：`propose_exclude` 由覆盖率
阶段的"自动发现"在跑（`graph.py` 里那句「已提议（待审批）」），`approve_exclude`
还带**哈希链**（前一条 approved 的 hash + 本条记录 → `audit_hash`，跨 run 连续）。
但**能调它的只有 CLI**（`vagent exclude approve`）—— 工作台里没有任何一页看得到
待批的提议，更别说批。

于是这些东西的现状是：提议一直在攒，没人批。而"这个覆盖率洞是不是结构不可达"
恰恰是 **AI 判断不了、只有人能判** 的那一类问题 —— 也正是豁免必须**审计门控**的
原因：批准一条豁免会把它从覆盖率分母里拿掉，等于**放行**一个原本没覆盖的点。
能签字的人必须看得见自己在签什么。

这一层只做三件事：读、批、拒。判定逻辑一条都不在这儿（全在 `ExcludeRegistry`）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

#: 提议类型 → 中文。认不出的原样显示 —— 界面里出现一个生词，好过出现空白。
TYPE_TITLES = {
    "unreachable": "结构不可达",
    "unreachable_struct": "结构不可达",
    "dead_code": "死代码",
    "unreachable_fsm": "状态不可达",
    "waived": "主动豁免",
}

#: 状态 → 中文
STATUS_TITLES = {
    "proposed": "待审批",
    "approved": "已批准",
    "rejected": "已拒绝",
}


def _registry(db_path: Optional[str] = None):
    from src.layers.l4_memory.exclude_registry import ExcludeRegistry

    return ExcludeRegistry(db_path) if db_path else ExcludeRegistry()


def _default_db() -> Optional[str]:
    return None          # 让 ExcludeRegistry 用它自己的默认位置（.signoffai/）


def _resolve_approver(explicit: str = "") -> str:
    """签字的人是谁。

    复用人工编辑那一套署名规则（`PLATFORM_USER_NAME` → 系统登录名）：同一个人
    在两处的名字必须是同一个，否则审计记录里会出现两个人。
    （CLI 那边用的是 `os.environ.get("USER", "engineer")`，在 Windows 上 `USER`
    通常没有，于是人人都是 `engineer` —— 那个"签名"是没有意义的。）
    """
    from src.core.runtime.identity import resolve_author

    return resolve_author(explicit)


def read_excludes(db_path: Optional[str] = None) -> Dict[str, Any]:
    """待批 + 已批 + 统计。**只读**，切标签页不弹确认。

    已批的那一列带上 `audit_hash` 与审批人 —— 那正是"这条豁免是**谁**签的、
    在链上的哪一环"的答案。少了它，这张表就只是"系统说这些点不用管"。
    """
    reg = _registry(db_path or _default_db())
    try:
        pending = reg.list_pending()
        approved = reg.get_approved_excludes()
        stats = reg.stats()
    finally:
        reg.close()
    return {
        "path": str(reg.db_path),
        "pending": [_decorate(r) for r in pending],
        "approved": [_decorate(r, approved=True) for r in approved],
        "stats": stats,
        "summary": _summary(stats),
    }


def _summary(stats: Dict[str, Any]) -> str:
    bits = [f"待批 {stats.get('pending', 0)}"]
    if stats.get("approved"):
        bits.append(f"已批 {stats.get('approved')}（不计入覆盖率分母）")
    if not stats.get("total"):
        return "还没有豁免提议"
    return "　".join(bits)


def _decorate(record: Dict[str, Any], *, approved: bool = False) -> Dict[str, Any]:
    out = dict(record)
    out["type_title"] = TYPE_TITLES.get(str(out.get("exclude_type", "")),
                                        str(out.get("exclude_type", "")))
    out["status_title"] = STATUS_TITLES.get(str(out.get("status", "")),
                                            str(out.get("status", "")))
    if approved:
        # 有签名才算数：没审批人/没哈希的"已批准"是坏了的数据，如实标出来
        out["signed"] = bool(out.get("approver") and out.get("audit_hash"))
    return out


def approve_exclude(exclude_id: str, approver: str = "",
                    db_path: Optional[str] = None) -> Dict[str, Any]:
    """批准一条豁免 —— **签名 + 哈希指纹入链**。

    这条动作的后果要说清楚：它把那个覆盖点从**分母**里拿掉。原本被算作"没覆盖"
    的点，批准之后就不再拉低覆盖率了。所以界面在按下这个按钮之前必须让人看见
    提议的理由与证据。
    """
    who = _resolve_approver(approver)
    reg = _registry(db_path or _default_db())
    try:
        ok = reg.approve_exclude(exclude_id, who)
        record = _find(reg, exclude_id) if ok else None
    finally:
        reg.close()
    if not ok:
        return {"approved": False, "error": f"没有这条豁免：{exclude_id}"}
    return {"approved": True, "exclude_id": exclude_id, "approver": who,
            "audit_hash": (record or {}).get("audit_hash", ""),
            "coverage_point": (record or {}).get("coverage_point", "")}


def reject_exclude(exclude_id: str, approver: str = "",
                   db_path: Optional[str] = None) -> Dict[str, Any]:
    """拒绝一条豁免 —— 点仍然要覆盖。"""
    who = _resolve_approver(approver)
    reg = _registry(db_path or _default_db())
    try:
        ok = reg.reject_exclude(exclude_id, who)
    finally:
        reg.close()
    if not ok:
        return {"rejected": False, "error": f"没有这条豁免：{exclude_id}"}
    return {"rejected": True, "exclude_id": exclude_id, "approver": who}


def _find(reg, exclude_id: str) -> Optional[Dict[str, Any]]:
    for row in reg.get_approved_excludes():
        if row.get("exclude_id") == exclude_id:
            return row
    return None
