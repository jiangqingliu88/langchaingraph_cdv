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
    ("agents/*/2_config/*.sv", "agents", "config"),
    ("agents/*/3_transaction_sequencer/*.sv", "agents", "sequencer"),
    ("agents/*/4_driver_monitor/*.sv", "agents", "driver_monitor"),
    ("agents/*/5_agent/*.sv", "agents", "agent"),
    ("agents/*/7_sequence/*.sv", "seq", "seq"),
    ("agents/*/8_ral/*.sv", "agents", "ral"),
    ("agents/*/loopback/*_scb.sv", "scbs", "scb"),
    ("agents/*/loopback/*_tb.sv", "tb", "tb"),
    ("agents/*/loopback/*_test.sv", "test", "test"),
    ("agents/*/loopback/*_env.sv", "env", "env"),
    ("agents/*/loopback/*.sv", "tb", "tb"),
    ("env/seqs/*.sv", "seq", "seq"),
    ("env/coverage/*.sv", "covgs", "coverage"),
    ("env/tests/*.sv", "test", "test"),
    ("env/*_loopback_scb.sv", "scbs", "scb"),
    ("env/*_loopback_tb.sv", "tb", "tb"),
    ("env/*_loopback_test.sv", "test", "test"),
    ("env/rtl_sc/*.sv", "scbs", "scb"),
    ("env/*checker*.sv", "checkers", "checker"),
    ("env/*_chk*.sv", "checkers", "checker"),
    ("env/*sva*.sv", "svas", "sva"),
    ("env/cons/*.sv", "cons", "constraint"),
    ("env/*.sv", "env", "env"),
    ("bench/*.sv", "tb", "tb"),
    ("coverage/*_cov_if.sv", "interface", "interface"),
    ("coverage/*.sv", "covgs", "coverage"),
    ("coverage/*bind*.sv", "interface/bind", "bind"),
    ("assertions/*.sv", "svas", "sva"),
    # 兜底：agent 目录下没被上面规则命中的 .sv 仍归到该 agent。
    ("agents/*/*.sv", "agents", "agent"),
)

_HEADER_KEYS = ("ARTIFACT", "SOURCE", "CONTRACT_REFS", "CASE_ID", "STATUS")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _header_contracts(text: str) -> List[str]:
    """从已有资产头的 `CONTRACT_REFS:` 读契约（SVA/手写资产用）。"""
    for line in text.splitlines()[:16]:
        if line.strip().startswith("// CONTRACT_REFS:"):
            value = line.split(":", 1)[1].strip()
            return [c for c in value.split() if c and c != "(none)"]
    return []


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
    for base in ("agents", "env", "bench", "coverage", "assertions"):
        root = run_root / base
        if root.is_dir():
            yield from root.rglob("*.sv")


def _rewrite_filelists(root: Path, rows: List[Dict[str, str]]) -> None:
    """把 `inputs/filelists/*.f` 里指向顶层源文件的路径改到 `sv/`。

    verify 生成期按顶层布局拼 filelist；move 到 sv 后必须同步，否则
    regression 的 `-f filelist_..._lb.f` 会指向已经不存在的文件。
    """
    by_source = {str(r.get("source") or ""): r["path"] for r in rows}
    by_name = {Path(str(r.get("source") or "")).name: r["path"] for r in rows}
    fl_dir = root / "inputs" / "filelists"
    if not fl_dir.is_dir():
        return
    for path in sorted(fl_dir.glob("*.f")):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        out = []
        for line in lines:
            text = line.strip()
            if not text or text.startswith(("#", "//", "+")):
                out.append(line)
                continue
            norm = text.replace("\\", "/")
            rel = ""
            for src, sv_path in by_source.items():
                if norm.endswith(src):
                    rel = sv_path
                    break
            if not rel:
                rel = by_name.get(Path(norm).name, "")
            out.append(str((root / rel).resolve()) if rel else line)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")


def _root_extras(root: Path, source: Path) -> List[Tuple[Path, Path]]:
    """run 根下、但不在渲染暂存区里的资产（DUT 覆盖率接口 / SVA）。"""
    if source.resolve() == root.resolve():
        return []
    extras: List[Tuple[Path, Path]] = []
    for sub in ("coverage", "assertions"):
        base = root / sub
        if base.is_dir():
            extras.extend((src, src.relative_to(root))
                          for src in base.rglob("*.sv"))
    return extras


def package_run_assets(run_root: str | Path, module: str = "",
                       *, move: bool = False,
                       source_root: str | Path | None = None) -> Dict[str, Any]:
    """把生成资产整理到 `<run>/sv/`，返回摘要。

    `source_root`：资产的实际落点（verify 的 VPlan 布局传暂存目录，避免在
    run 根留下顶层 `agents/env/bench`）；缺省为 `run_root`（旧 run 补整理）。
    `move=True`：写入 sv/ 后删除源文件（verify 生成期使用；run 里只保留
    sv/ 这一份 UVM 资产）。`move=False` 保留源文件。
    """
    root = Path(run_root)
    source = Path(source_root) if source_root else root
    sv_root = root / "sv"
    rows: List[Dict[str, str]] = []
    copied = 0
    skipped = 0
    skipped_paths: List[str] = []
    artifact_contracts, test_cases, kind_contracts = _anchor_index(root)
    sources: List[Tuple[Path, Path]] = [
        (src, src.relative_to(source)) for src in _iter_sources(source)]
    # verify 写在 run 根的覆盖率资产（DUT cov_if / bind）与 SVA（bind 进
    # DUT）不在暂存区里；它们和生成资产一起进 sv/，否则对应通道会整条丢失。
    sources.extend(_root_extras(root, source))
    for src, rel in sorted(sources, key=lambda item: item[1].as_posix()):
        target = _target_rel(rel)
        if target is None:
            skipped += 1
            skipped_paths.append(rel.as_posix())
            continue
        subdir, kind = target
        dest_name = ("hdl_top.sv" if kind == "tb" and rel.parts[0] == "bench"
                     else src.name)
        dest = sv_root / subdir / dest_name
        if dest.exists() and dest.resolve() == src.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        text = _read(src)
        contracts = (artifact_contracts.get(src.stem)
                     or kind_contracts.get(kind)
                     or _header_contracts(text)
                     or [])
        case_ids = test_cases.get(src.stem, []) if kind == "test" else []
        # 搬进扁平 sv/ 后，`include "2_config/x.sv"` 这类子目录路径失效 ——
        # 统一改成 basename（filelist 会把各 sv 子目录都加进 incdir）。
        text = re.sub(
            r'`include\s+"([^"]+)"',
            lambda m: '`include "' + Path(m.group(1)).name + '"', text)
        if not _has_header(text, "ARTIFACT"):
            text = _header(rel.as_posix(), src.stem, contracts, case_ids) + text
        dest.write_text(text, encoding="utf-8")
        if move and dest.resolve() != src.resolve():
            try:
                src.unlink()
            except OSError:
                pass
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
    if not rows and (sv_root / "asset_registry.csv").is_file():
        # 没有源文件（已被 move 走）→ 保留上一份登记，不能写成空表。
        with (sv_root / "asset_registry.csv").open(
                encoding="utf-8-sig", newline="") as fh:
            rows = [dict(r) for r in csv.DictReader(fh)]
    fields = ["artifact", "kind", "path", "owner", "status",
              "contract_ids", "case_ids", "source"]
    with (sv_root / "asset_registry.csv").open(
            "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    # 目标布局固定带 `covgs/` 与 `cons/`（即使本轮没有对应 SV 资产）。
    (sv_root / "covgs").mkdir(exist_ok=True)
    (sv_root / "cons").mkdir(exist_ok=True)
    (sv_root / "README.md").write_text(
        "# sv — SignOffAI 生成的验证资产（VPlan 布局）\n\n"
        "由 verify 生成期的暂存目录（或旧 run 的 `agents/`、`env/`、`coverage/`）"
        "整理而来；每个文件带 `// ARTIFACT:` / `// SOURCE:` 锚点。\n"
        "`tb/` 放顶层 testbench，`vc/` 放 hdl/hvl 编译清单，"
        "`checkers/scbs/svas` 放对应资产。\n"
        "全部 `candidate`：没有编译/运行证据，契约仍 `assume`、case 仍 `planned`。\n",
        encoding="utf-8")
    _write_vc_filelists(root, sv_root, rows)
    _rewrite_filelists(root, rows)
    return {"sv_root": str(sv_root), "copied": copied, "skipped": skipped,
            "skipped_paths": skipped_paths[:20],
            "registry": str(sv_root / "asset_registry.csv"),
            "assets": len(rows)}


LEGACY_DIRS = ("agents", "bench", "env", "build")


def clean_legacy_dirs(run_root: str | Path, *, apply: bool = False) -> Dict[str, Any]:
    """删除内核的顶层工作目录（仅当 sv/ 已生成时）。

    这是**不可逆**操作；默认 dry-run。只有 `sv/asset_registry.csv` 存在且至少
    有一个 `sv/**/*.sv` 才允许删 —— 否则会把唯一一份资产删掉。
    """
    root = Path(run_root)
    sv_root = root / "sv"
    assets = list(sv_root.rglob("*.sv")) if sv_root.is_dir() else []
    if not (sv_root / "asset_registry.csv").is_file() or not assets:
        raise ValueError("sv/ 未生成或无 .sv 资产，拒绝删除 legacy 目录")
    present = [name for name in LEGACY_DIRS if (root / name).is_dir()]
    if apply:
        import shutil

        for name in present:
            shutil.rmtree(root / name)
    return {"run": str(root), "apply": apply,
            "present": present, "deleted": present if apply else [],
            "assets": len(assets)}


def _write_vc_filelists(root: Path, sv_root: Path,
                        rows: List[Dict[str, str]]) -> None:
    """生成 `sv/vc/hdl_files.f` / `hvl_files.f`（沿用原 filelist 的顺序）。"""
    by_source = {Path(r["source"]).name: r["path"] for r in rows}
    source_fl = root / "inputs" / "filelists" / "filelist.f"
    ordered: List[str] = []
    if source_fl.is_file():
        for line in _read(source_fl).splitlines():
            text = line.strip()
            if not text or text.startswith(("#", "//", "+")):
                continue
            name = Path(text.replace("\\", "/")).name
            if name in by_source:
                ordered.append(by_source[name])
            elif "rtl/" in text.replace("\\", "/"):
                ordered.append(text.replace("\\", "/"))
    if not ordered:
        ordered = [r["path"] for r in rows]

    hdl, hvl = [], []
    for path in dict.fromkeys(ordered):
        (hdl if path.startswith(("sv/interface/", "sv/tb/", "rtl/"))
         else hvl).append(path)
    vc = sv_root / "vc"
    vc.mkdir(parents=True, exist_ok=True)
    header = "# generated by `vagent vplan package-assets`\n"
    (vc / "hdl_files.f").write_text(
        header + "".join(f"{p}\n" for p in hdl), encoding="utf-8")
    (vc / "hvl_files.f").write_text(
        header + "".join(f"{p}\n" for p in hvl), encoding="utf-8")


#: 文件名 → 期望的 sv 子目录。与 `_RULES` 的“产物→目录”正交：
#: `_RULES` 管源文件怎么归位，这里管**文档里写死的布局**（vc/ 是清单、covgs/ 是覆盖组）。
_LAYOUT_BY_NAME = (
    (re.compile(r"_cov_if\.sv$"), "interface"),
    (re.compile(r"^(hdl|hvl)_files\.f$"), "vc"),
    (re.compile(r"_cov\.sv$"), "covgs"),
    (re.compile(r"_scb\.sv$"), "scbs"),
    (re.compile(r"_checker\.sv$|_chk\.sv$"), "checkers"),
    (re.compile(r"_sva\.sv$"), "svas"),
    (re.compile(r"(^|_)(test|batch)\.sv$|_test\.sv$"), "test"),
    (re.compile(r"_cons\.sv$"), "cons"),
)


def expected_layout_kind(name: str) -> str:
    """文件名 → 期望的 `sv/` 子目录；无法判断返回空串（不猜）。"""
    for pattern, kind in _LAYOUT_BY_NAME:
        if pattern.search(name):
            return kind
    return ""


def layout_mismatches(root: str | Path,
                      rows: List[Dict[str, str]] | None = None
                      ) -> List[str]:
    """核对 `sv/` 布局：`vc/` 清单齐全、`covgs/scbs/...` 文件名落在正确子目录。"""
    run = Path(root)
    sv = run / "sv"
    out: List[str] = []
    if not sv.is_dir():
        return out
    for name in ("vc/hdl_files.f", "vc/hvl_files.f"):
        if not (sv / name).is_file():
            out.append(f"缺少布局文件：sv/{name}")
    scanned = rows if rows is not None else scan_assets(run)
    for row in scanned:
        expected = expected_layout_kind(Path(row["path"]).name)
        kind = str(row.get("kind") or "")
        if expected and kind and expected != kind:
            out.append(
                f"{row['path']} 应放在 sv/{expected}/，实际在 sv/{kind}/")
    return out


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
