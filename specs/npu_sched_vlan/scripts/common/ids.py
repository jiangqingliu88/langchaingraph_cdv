"""ID patterns — single source shared by every lint/gate script.

Keep in sync with docs/appendix/X00_id_anchor_spec.md.
"""
from __future__ import annotations

import re

PATTERNS = {
    "contract": re.compile(r"^C-[A-Z]+(?:-[A-Z0-9]+)*-\d{3}$"),
    "case": re.compile(r"^TC_[A-Z0-9]+(?:_[A-Z0-9]+)*$"),
    "cg": re.compile(r"^cg_[a-z0-9_]+$"),
    "cp": re.compile(r"^cp_[a-z0-9_]+$"),
    "cross": re.compile(r"^cross_[a-z0-9_]+$"),
    "constraint": re.compile(r"^CON_[A-Z0-9_]+$"),
    "exemption": re.compile(r"^EX-\d{3}$"),
    "batch": re.compile(r"^batch\d{2}$"),
    "artifact": re.compile(r"^[a-z][a-z0-9_]*$"),
}


def is_valid(kind: str, value) -> bool:
    pattern = PATTERNS.get(kind)
    return bool(pattern and isinstance(value, str) and pattern.match(value))


def split_ids(value: str):
    return [part for part in re.split(r"[\s,]+", (value or "").strip()) if part]
