"""VPlan 契约 → UVM 环境架构（`<run>/sv/uvm_arch.*`）。

不是从 RTL 端口"猜"环境，而是把 VPlan 的契约/TP/case 投影成环境骨架：

    agent       契约 class=if 的 object（接口契约）→ 一个 agent 槽位
    checker     契约 check_method ∈ {sva, checker} → 断言 checker
    scoreboard  data/scoreboards.csv 的每条 SB → 收口比对
    coverage    Case IR 的 group（CG-*）→ covergroup
    test        Case IR 的 case → UVM test 类

产物（`sv/` 下）：
    uvm_arch.yaml   机器读
    uvm_arch.csv    人读/评审（kind,name,contracts,tp_ids）
    uvm_arch.md     架构说明 + 契约到组件的映射

它描述"环境应该长什么样"，不替代生成器；生成后的 `sv/` 资产用
`// CONTRACT_REFS:` / `// CASE_ID:` 锚点与本架构对齐。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml

SCHEMA = "vplan_uvm_arch_v1"
_FIELDS = ("kind", "name", "contracts", "tp_ids", "source")


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _read_csv(path: Path) -> List[Dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [dict(row) for row in csv.DictReader(fh)]
    except OSError:
        return []


def _tp_by_contract(project) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for tp in project.testpoints:
        cid = str(tp.get("contract_id") or "")
        tpid = str(tp.get("tp_id") or "")
        if cid and tpid:
            out.setdefault(cid, []).append(tpid)
    return out


def _agents(project, tp_by_contract) -> List[Dict[str, Any]]:
    buckets: Dict[str, List[str]] = {}
    for cid, row in project.contracts.items():
        if str(row.get("class") or "") != "if":
            continue
        name = str(row.get("object") or "").strip()
        # 中文 object（"接口"）不是合法 agent 名 —— 归到 top 接口 agent。
        if not name or not name.isascii():
            name = "cmd_if"
        buckets.setdefault(name, []).append(cid)
    return [{
        "kind": "agent",
        "name": f"{name}_agent",
        "contracts": sorted(cids),
        "tp_ids": sorted({t for c in cids for t in tp_by_contract.get(c, [])}),
        "source": "contract_matrix/if",
    } for name, cids in sorted(buckets.items())]


def _checkers(project, tp_by_contract) -> List[Dict[str, Any]]:
    out = []
    for cid, row in project.contracts.items():
        if str(row.get("check_method") or "").lower() not in ("sva", "checker"):
            continue
        out.append({
            "kind": "checker", "name": cid, "contracts": [cid],
            "tp_ids": sorted(tp_by_contract.get(cid, [])),
            "source": "contract_matrix",
        })
    return out


def _scoreboards(project, data_dir: Path) -> List[Dict[str, Any]]:
    func_contracts = sorted(cid for cid, row in project.contracts.items()
                            if str(row.get("class") or "") in ("func", "data"))
    out = []
    for row in _read_csv(data_dir / "scoreboards.csv"):
        sb = str(row.get("id") or "")
        if not sb:
            continue
        # 优先按契约声明的 check_artifact / object 精确绑定；没有声明时才
        # 退回“所有 func/data 契约”，避免把 scoreboard 写成万能收口。
        tokens = {sb.lower(), str(row.get("name") or "").lower()}
        related = sorted(
            cid for cid, c in project.contracts.items()
            if str(c.get("class") or "") in ("func", "data")
            and (
                str(c.get("check_artifact") or "").strip().lower() in tokens
                or str(c.get("object") or "").strip().lower() in tokens
            )
        )
        out.append({
            "kind": "scoreboard", "name": sb,
            "contracts": related or func_contracts,
            "tp_ids": [], "source": "data/scoreboards.csv",
            "rules": row.get("rules", ""),
        })
    return out


def _coverage_groups(case_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    seen: Dict[str, Dict[str, Any]] = {}
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        feats = [str(c) for c in case.get("feats") or [] if c]
        for grp in case.get("groups") or []:
            name = str((grp or {}).get("group") or "")
            if not name:
                continue
            slot = seen.setdefault(name, {"kind": "coverage", "name": name,
                                          "contracts": [], "tp_ids": [],
                                          "source": "case_ir"})
            for cid in feats:
                if cid not in slot["contracts"]:
                    slot["contracts"].append(cid)
            for tpid in (grp or {}).get("tp_ids") or []:
                if str(tpid) not in slot["tp_ids"]:
                    slot["tp_ids"].append(str(tpid))
    return list(seen.values())


def _tests(case_ir: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for case in case_ir.get("cases") or []:
        if not isinstance(case, dict):
            continue
        test = str((case.get("tests") or [""])[0] or case.get("name") or "")
        out.append({
            "kind": "test", "name": test,
            "contracts": [str(c) for c in case.get("feats") or [] if c],
            "tp_ids": [], "source": "cases/*.yaml",
            "case_id": str(case.get("id") or ""),
        })
    return out


def build_uvm_arch(project, run_dir: str | Path) -> Dict[str, Any]:
    """VPlan 契约 + Case IR → UVM 环境架构。"""
    root = Path(run_dir)
    case_ir = _read_json(root / "coverage" / "case_ir.json")
    if not case_ir.get("cases"):
        case_ir = {}
    tp_by_contract = _tp_by_contract(project)
    sections = {
        "agents": _agents(project, tp_by_contract),
        "checkers": _checkers(project, tp_by_contract),
        "scoreboards": _scoreboards(project, project.root / "data"),
        "coverage": _coverage_groups(case_ir),
        "tests": _tests(case_ir),
    }
    return {
        "schema": SCHEMA,
        "module": project.module,
        "env": f"{project.module}_env",
        **sections,
    }


def _write_csv(path: Path, doc: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(_FIELDS),
                                extrasaction="ignore")
        writer.writeheader()
        for section in ("agents", "checkers", "scoreboards", "coverage",
                        "tests"):
            for row in doc.get(section) or []:
                writer.writerow({**row,
                                 "contracts": "|".join(row.get("contracts") or []),
                                 "tp_ids": "|".join(row.get("tp_ids") or [])})


def _write_md(path: Path, doc: Dict[str, Any]) -> None:
    lines = [
        f"# UVM 环境架构 — {doc.get('module', '')}",
        "",
        f"env: `{doc.get('env', '')}`；来源：VPlan 契约 / TP / case，**不是 RTL 端口猜测**。",
        "",
    ]
    for title, key in (("Agents", "agents"), ("Checkers", "checkers"),
                       ("Scoreboards", "scoreboards"),
                       ("Coverage groups", "coverage"), ("Tests", "tests")):
        lines += [f"## {title}", "", "| 名称 | 契约 | TP |", "|---|---|---|"]
        for row in doc.get(key) or []:
            lines.append("| `{}` | {} | {} |".format(
                row.get("name", ""),
                ", ".join(row.get("contracts") or []) or "-",
                ", ".join(row.get("tp_ids") or []) or "-"))
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_uvm_arch(run_dir: str | Path, project) -> Dict[str, Any]:
    """写 `<run>/sv/uvm_arch.{yaml,csv,md}`；返回架构 dict。"""
    root = Path(run_dir)
    doc = build_uvm_arch(project, root)
    out = root / "sv"
    out.mkdir(parents=True, exist_ok=True)
    (out / "uvm_arch.yaml").write_text(
        yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    _write_csv(out / "uvm_arch.csv", doc)
    _write_md(out / "uvm_arch.md", doc)
    return doc


__all__ = ["SCHEMA", "build_uvm_arch", "write_uvm_arch"]
