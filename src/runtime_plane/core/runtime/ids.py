"""全局 ID 的唯一实现点 —— `CASE-` / `CCAT-` / `TST-` / `EVD-` / `CG-`…

这里只做**字符串规范化与拼接**，不含业务规则。放在 `core.runtime` 是为了
让身份层（Case IR）、证据层（case_cov）、账本（ledger）共用同一套口径，
而不是各拼各的。

身份层 `layers/l3_decision/case_ir/ir_core.py` 直接使用这些名字。
"""
from __future__ import annotations

import re
from typing import Any

_ID_INVALID = re.compile(r"[^A-Za-z0-9_.\-]+")


def slug(text: Any, *, upper: bool = True, fallback: str = "") -> str:
    """任意文本 → 可用作 ID 片段的 slug（保留 `_ . -`）。"""
    raw = str(text or "").strip()
    if not raw:
        return fallback
    out = _ID_INVALID.sub("_", raw).strip("_")
    if not out:
        return fallback
    return out.upper() if upper else out


def case_id_of(*parts: Any) -> str:
    """`CASE-<parts...>` —— 唯一实现点，别在别处拼字符串。"""
    body = [slug(p) for p in parts if slug(p)]
    return "CASE-" + "-".join(body) if body else ""


def ccat_id_of(*parts: Any) -> str:
    body = [slug(p) for p in parts if slug(p)]
    return "CCAT-" + "-".join(body) if body else ""


def tst_id_of(test: str, seed: Any = "") -> str:
    """**TST 身份 = test @ seed**。

    没有种子时给 test 级的模板身份（`TST-<test>`）—— 生成期还没有具体
    执行实例，只有模板；执行期（`task_meta`）再补种子。
    """
    test = slug(test)
    if not test:
        return ""
    return f"TST-{test}@{int(seed)}" if str(seed).strip().isdigit() else f"TST-{test}"


def evd_id_of(run_id: str, test: str, seed: Any = "") -> str:
    """一次执行 = 一条 EVD。去重键 `(run, tst, seed, cfg)`。"""
    tst = tst_id_of(test, seed)
    run = slug(run_id, upper=False)
    return f"EVD-{run}-{tst}" if run and tst else ""


def group_id_of(dimension: Any) -> str:
    """`CG-<维度>` —— 功能组（覆盖组）身份，**唯一实现点**。"""
    body = slug(dimension)
    if not body:
        return ""
    return body if body.startswith("CG") else f"CG-{body}"


def group_short(group: Any) -> str:
    """`CG-D_DEP` → `D_DEP`（拼 `CELL-<group>-<P>` 时用短名）。"""
    text = slug(group)
    return text[3:] if text.startswith("CG-") or text.startswith("CG_") else text


def sva_id_of(assertion: Any) -> str:
    """`SVA-<断言 id>`。断言已在模型里唯一，这里只加前缀。"""
    body = slug(assertion)
    if not body:
        return ""
    return body if body.startswith("SVA") else f"SVA-{body}"


def scb_id_of(check: Any) -> str:
    """`SB-<check>`（scoreboard 条目）。同一实现点，别处不拼。"""
    body = slug(check)
    if not body:
        return ""
    return body if body.startswith("SB-") or body.startswith("SB_") else f"SB-{body}"


__all__ = [
    "case_id_of", "ccat_id_of", "evd_id_of", "group_id_of", "group_short",
    "scb_id_of", "slug", "sva_id_of", "tst_id_of",
]
