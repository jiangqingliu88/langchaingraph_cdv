"""把 SignOffAI 生成的 UVM 资产整理成 VPlan `sv/` 布局并登记。

**资产由内核生成，不在这里手写**：`verify` 产出 `<run>/agents/...`、
`<run>/env/...`、`<run>/coverage/...`，本模块只做两件事：

1. 按 X01 布局复制到 `<run>/sv/{interface,agents,monitor,coverage,sva,
   checker,scb,seq,test,env}`；
2. 补锚点（ARTIFACT / SOURCE / CONTRACT_REFS / STATUS）并写
   `sv/asset_registry.csv`。

状态一律从 `candidate` 起步；编译/运行证据由后续 gate 推进。
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

#: 生成目录 → VPlan sv/ 子目录。顺序即匹配顺序（先具体、后宽泛）。
_RULES: Tuple[Tuple[str, str, str], ...] = (
    ("agents/*/1_interface/*.sv", "interface", "interface"),
    ("agents/*/3_transaction_sequencer/*.sv", "agents", "sequencer"),
    ("agents/*/4_driver_monitor/*.sv", "agents", "driver_monitor"),
    ("agents/*/5_agent/*.sv", "agents", "agent"),
    ("agents/*/7_sequence/*.sv", "seq", "seq"),
    ("env/coverage/*.sv", "coverage", "coverage"),
    ("env/tests/*.sv", "test", "test"),
    ("env/rtl_sc/*.sv", "scb", "scb"),
    ("env/cons/*.sv", "seq", "constraint"),
    ("env/*.sv", "env", "env"),
    ("bench/*.sv", "env", "env"),
    ("coverage/*_cov_if.sv", "interface", "interface"),
)

_HEADER_KEYS = ("ARTIFACT", "SOURCE", "CONTRACT_REFS", "CASE_ID", "STATUS")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _has_header(text: str, key: str) -> bool:
    return re.search(rf"^\s*//\s*{key}:", text, re.MULTILINE) is not None


def _anchor_index(root: Path) -> Tuple[Dict[str, List[str]], Dict[str, List[str]],
                                      Dict[str, List[str]]]:
    """`artifact → C-*` / `test → TC_*` / `kind → C-*`（来自 run 的 Case IR）。"""
    artifact_contracts: Dict[str, set[str]] = {}
    test_cases: Dict[str, set[str]] = {}
    kind_contracts: Dict[str, set[str]] = {}
    case_ir = _read_json(root / "coverage" / "case_ir.json")
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        cid = str(case.get("id") or "")
        contracts = [str(c) for c in (case.get("feats") or []) if c]
        for kind in ("sva", "scb"):
            items = case.get(kind) or []
            if items:
                kind_contracts.setdefault(kind, set()).update(contracts)
            for item in items:
                if isinstance(item, dict) and item.get("id"):
                    artifact_contracts.setdefault(str(item["id"]), set()).update(contracts)
        for test in case.get("tests") or []:
            if test:
                test_cases.setdefault(str(test), set()).add(cid)
    return ({k: sorted(v) for k, v in artifact_contracts.items()},
            {k: sorted(v) for k, v in test_cases.items()},
            {k: sorted(v) for k, v in kind_contracts.items()})


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _header(source_rel: str, artifact: str,
            contracts: List[str] | None = None,
            case_ids: List[str] | None = None) -> str:
    contract_text = " ".join(contracts or []) or "(none)"
    lines = [
        "// ============================================================================",
        f"// {source_rel} — SignOffAI 生成资产（VPlan 布局）",
        f"// SOURCE: {source_rel}",
        f"// ARTIFACT: {artifact}",
        f"// CONTRACT_REFS: {contract_text}",
    ]
    if case_ids:
        lines.append("// CASE_ID: " + " ".join(case_ids))
    lines += [
        "// STATUS: candidate",
        "// ============================================================================",
        "",
    ]
    return "\n".join(lines)


def _target_rel(src_rel: Path) -> Tuple[str, str] | None:
    """源相对路径 → (sv 子目录, kind)。"""
    posix = src_rel.as_posix()
    for pattern, subdir, kind in _RULES:
        if Path(posix).match(pattern):
            if subdir == "agents":
                agent = src_rel.parts[1]
                return f"agents/{agent}", kind
            return subdir, kind
    return None


def _iter_sources(run_root: Path) -> Iterable[Path]:
    for base in ("agents", "env", "bench", "coverage"):
        root = run_root / base
        if root.is_dir():
            yield from root.rglob("*.sv")


def package_run_assets(run_root: str | Path, module: str = "") -> Dict[str, Any]:
    """把 run 里的生成资产整理到 `<run>/sv/`，返回摘要。"""
    root = Path(run_root)
    sv_root = root / "sv"
    rows: List[Dict[str, str]] = []
    copied = 0
    skipped = 0
    artifact_contracts, test_cases, kind_contracts = _anchor_index(root)
    for src in sorted(_iter_sources(root)):
        rel = src.relative_to(root)
        target = _target_rel(rel)
        if target is None:
            skipped += 1
            continue
        subdir, kind = target
        dest = sv_root / subdir / src.name
        if dest.exists() and dest.resolve() == src.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        contracts = (artifact_contracts.get(src.stem)
                     or kind_contracts.get(kind)
                     or [])
        case_ids = test_cases.get(src.stem, []) if kind == "test" else []
        text = _read(src)
        if not _has_header(text, "ARTIFACT"):
            text = _header(rel.as_posix(), src.stem, contracts, case_ids) + text
        dest.write_text(text, encoding="utf-8")
        copied += 1
        rows.append({
            "artifact": src.stem,
            "kind": kind,
            "path": dest.relative_to(root).as_posix(),
            "owner": "",
            "status": "candidate",
            "contract_ids": "|".join(contracts),
            "case_ids": "|".join(case_ids),
            "source": rel.as_posix(),
        })

    sv_root.mkdir(parents=True, exist_ok=True)
    fields = ["artifact", "kind", "path", "owner", "status",
              "contract_ids", "case_ids", "source"]
    with (sv_root / "asset_registry.csv").open(
            "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    (sv_root / "README.md").write_text(
        "# sv — SignOffAI 生成的验证资产（VPlan 布局）\n\n"
        "由 `vagent vplan package-assets` 从本 run 的 `agents/`、`env/`、"
        "`coverage/` 整理而来；每个文件带 `// ARTIFACT:` / `// SOURCE:` 锚点。\n"
        "全部 `candidate`：没有编译/运行证据，契约仍 `assume`、case 仍 `planned`。\n",
        encoding="utf-8")
    return {"sv_root": str(sv_root), "copied": copied, "skipped": skipped,
            "registry": str(sv_root / "asset_registry.csv"),
            "assets": len(rows)}


def scan_assets(root: str | Path) -> List[Dict[str, str]]:
    """扫描 `sv/**/*.sv` 的锚点（用于 --check / registry 核对）。"""
    sv_root = Path(root) / "sv"
    out: List[Dict[str, str]] = []
    if not sv_root.is_dir():
        return out
    for path in sorted(sv_root.rglob("*.sv")):
        text = _read(path)
        def value(key: str) -> str:
            found = re.search(rf"^\s*//\s*{key}:\s*(.*)$", text, re.MULTILINE)
            return found.group(1).strip() if found else ""
        rel = path.relative_to(root).as_posix()
        out.append({
            "artifact": value("ARTIFACT") or path.stem,
            "kind": path.parent.name,
            "path": rel,
            "owner": value("OWNER"),
            "status": value("STATUS") or "candidate",
            "contract_ids": value("CONTRACT_REFS"),
            "case_ids": value("CASE_ID"),
            "source": value("SOURCE"),
        })
    return out
