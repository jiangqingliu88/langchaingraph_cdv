"""Intent 落盘 —— `coverage/intents.json`（语义映射的构建物）。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .compiler import intents_from_case_ir
from .schema import VerificationIntent, from_dict
from .validator import validate

SCHEMA = "intents_v1"


def write_intents(output_dir: str | Path, case_ir: Dict[str, Any], *,
                  module: str = "") -> Dict[str, Any]:
    root = Path(output_dir)
    intents = intents_from_case_ir(case_ir, module=module)
    report = validate(intents)
    doc = {
        "schema": SCHEMA,
        "module": module or str(case_ir.get("module") or ""),
        "total": len(intents),
        "candidate": sum(1 for i in intents if not i.confirmed),
        "confirmed": sum(1 for i in intents if i.confirmed),
        "validation": report,
        "intents": [i.to_dict() for i in intents],
    }
    path = root / "coverage" / "intents.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return {"path": "coverage/intents.json", "total": len(intents),
            "candidate": doc["candidate"], "confirmed": doc["confirmed"],
            "ok": bool(report["ok"])}


def load_intents(output_dir: str | Path) -> List[VerificationIntent]:
    try:
        doc = json.loads((Path(output_dir) / "coverage" / "intents.json")
                         .read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return []
    return [from_dict(i) for i in (doc.get("intents") or [])
            if isinstance(i, dict)]


__all__ = ["SCHEMA", "load_intents", "write_intents"]
