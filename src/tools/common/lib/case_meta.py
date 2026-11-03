"""用例身份 + 波形索引 —— **"用例 → 测试点 → 波形"这条链的唯一落点**。

## 为什么需要它

回归目录里每样东西本来就齐了，但没有一处把它们**显式写下来**：

    test_tp_npusch_d_queue_0_seed_6001/     ← 目录名里有 task 与 seed
        cov/npu_sched_env_d_queue_p0_test/questa.db
        waves/tp_npusch_d_queue_0.db
        sim_vsim.log

于是覆盖率只能按**合并库**说"这个 bin 被打到过"，波形打开只看到模块名，
没人能回答"这条波形在证明哪个测试点"。本模块补的就是这份契约：

    task_meta.json     生成回归目录时写下 task / test / seed / stage / tp_ids
    manifest.json      回归收尾时写下 task ↔ 波形 ↔ 测试点

两者都是**派生**出来的（目录名、sim.sh、TP IR 本来就有答案），不是第二份
真相：读不到时按同一套规则从现场重新推导，推导结果与写下来的逐字段一致。

## 判据的三条纪律

1. **读不到 ≠ 没有**：文件缺失时回退到现场推导，回退不出来就如实给空串，
   不编一个看起来对的默认值；
2. **波形只做定位**：`questa.db` 才是覆盖率真源，波形只回答"这一拍在哪"；
3. **TP 归属优先显式**：`task_meta.tp_ids`（回归生成时从 TP IR 反查）> 目录
   名/tag 里的 `TP-*` > 按 UVM test 类反查。来源写进结果（`owner_basis`），
   让人知道这条签核是靠哪一层对上的。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List

#: 每个用例目录里的身份文件（回归目录生成时写）。
TASK_META_NAME = "task_meta.json"
#: v2 只**加键**（`case_id/tst_id/cell_ids`）：v1 的读端不受影响，缺键即 legacy。
#: 见 `src/core/contracts/versions.py::REGRESSION_TASK`。
TASK_META_SCHEMA = "regression_task_v2"

#: 运行根下的波形索引（回归收尾时写）。
WAVE_MANIFEST_DIR = "waves"
WAVE_MANIFEST_NAME = "manifest.json"
WAVE_MANIFEST_SCHEMA = "wave_manifest_v1"

#: 分级回归的级名 —— 仅用于**识别**目录属于哪一级（定义仍在 infrastructure）。
STAGE_DIRS = ("loopback", "p0", "p1", "p2", "p3")

_SEED_RE = re.compile(r"_seed_(\d+)$")
_RUN_RE = re.compile(r"_run_(\d+)$")
_TEST_DIR_RE = re.compile(r"^test_(.+)$")
_UVM_TEST_RE = re.compile(r"\+UVM_TESTNAME\s*[= ]\s*([^\s;'\"]+)")
#: `[SCB_DUT] total=40 matched=40 mismatched=0`（env_cov.sv.j2 的收口行）。
_SCB_RE = re.compile(
    r"\[SCB_DUT\]\s+total=(\d+)\s+matched=(\d+)\s+mismatched=(\d+)")
#: `[SCB <id>] total=… matched=… mismatched=…` —— **单条 scoreboard** 的收口行。
#: 与 `[SCB_DUT]`（env 聚合行）区分：`\s+` 后面必须是 id，`SCB_DUT` 不会被它匹配。
_SCB_ID_RE = re.compile(
    r"\[SCB\s+([^\]\s]+)\]\s+total=(\d+)\s+matched=(\d+)\s+mismatched=(\d+)")
#: `规则 <name> 违规 <n> 次`（DUT 检查规则）。
_DUT_RULE_RE = re.compile(r"规则\s+(\S+)\s+违规\s+(\d+)\s*次")
_WAVE_LOG_RE = re.compile(r"WAVE_PATH\s*=\s*(.+)")
#: `[TP_TIMING] tp=TP-… cycles=… 期望 [min,max]`（env 检查组逐拍判窗后打的行）。
_TP_TIMING_RE = re.compile(r"\[TP_TIMING\]\s+tp=(\S+).*?cycles=(\d+)")
#: `[TP_TIMING] checked=N violations=M`（report_phase 的收口行）。
_TP_TIMING_SUM_RE = re.compile(r"\[TP_TIMING\]\s+checked=(\d+)\s+violations=(\d+)")

_WAVE_SUFFIXES = (".db", ".vcd", ".fsdb")


# ────────────────────────────────────────────────────────────────
# task_meta.json
# ────────────────────────────────────────────────────────────────

def write_task_meta(test_dir: str | Path, meta: Dict[str, Any]) -> Path:
    """把一条用例的身份写进 `<test_dir>/task_meta.json`。

    只写显式给定的字段；缺失由 `read_task_meta` 从现场推导。写入失败不抛
    （生成脚本不该因为一个旁路索引失败而整轮挂掉），返回路径供调用方记账。
    """
    d = Path(test_dir)
    payload = {"schema": TASK_META_SCHEMA}
    payload.update({k: v for k, v in (meta or {}).items() if v is not None})
    out = d / TASK_META_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
    except OSError:
        pass
    return out


def _parse_task_name(test_dir: Path) -> tuple:
    """目录名 → `(task, test_name, seed)`。

    `test_<test_name>_seed_<n>` / `test_<test_name>_run_<n>` / `test_<name>`。
    `task` 是**带 seed 的目录名主体**（与设计里的 `signed_off_by` 同名），
    `test_name` 是回归配置里的用例名（不带 seed）。
    """
    name = test_dir.name
    m = _TEST_DIR_RE.match(name)
    task = m.group(1) if m else name
    base, seed = task, None
    sm = _SEED_RE.search(task)
    if sm:
        seed, base = int(sm.group(1)), task[:sm.start()]
    else:
        rm = _RUN_RE.search(task)
        if rm:
            seed, base = int(rm.group(1)), task[:rm.start()]
    return task, base, seed


def _first_text(*paths: Path) -> str:
    for p in paths:
        try:
            if p.is_file():
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return ""


def _test_from_sim_sh(test_dir: Path) -> str:
    """从 `sim.sh` 里读 `+UVM_TESTNAME=` —— 这是 UVM 真正跑的类名。

    回归配置的 `name` 是**任务名**（如 `tp_x`），`+UVM_TESTNAME` 才是 UVM
    类名（如 `npu_env_attr_test`）。两者不能混：TP IR 的 `execution.test`
    记的是后者。

    **只读 sim.sh，不读 sim.log**：日志可能几十 MB，而这里只是旁路推导；
    没有 sim.sh（老目录/手工目录）就如实给空串，调用方回退到类名匹配。
    """
    try:
        text = (test_dir / "sim.sh").read_text(encoding="utf-8",
                                               errors="replace")
    except OSError:
        return ""
    m = _UVM_TEST_RE.search(text)
    return m.group(1) if m else ""


def _stage_of(test_dir: Path) -> str:
    for parent in test_dir.parents:
        if parent.name in STAGE_DIRS:
            return parent.name
    return ""


CASE_IR_NAME = "case_ir.json"
CASE_IR_SCHEMA = "case_ir_v1"


CASE_GROUP_MAP_NAME = "case_group_map.json"
CASE_CHECKER_MAP_NAME = "case_checker_map.json"


def write_case_ir(cov_dir: str | Path, case_ir: Dict[str, Any],
                  case_maps: Dict[str, Any] = None) -> Dict[str, Any]:
    """落 `coverage/case_ir.json`（身份来源）+ 两份派生索引。空文档**不写**。

    返回 `{path, cases, categories, declared, synthesized, group_map,
    checker_map}`；没写盘时 `path=""`。
    """
    empty = {"path": "", "cases": 0, "categories": 0, "declared": 0,
             "synthesized": 0, "group_map": "", "checker_map": ""}
    if not isinstance(case_ir, dict) or not case_ir.get("cases"):
        return empty
    d = Path(cov_dir)
    out = d / CASE_IR_NAME
    try:
        d.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(case_ir, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
    except OSError:
        return empty
    maps = case_maps or {}
    written = {}
    for key, name in (("group_map", CASE_GROUP_MAP_NAME),
                      ("checker_map", CASE_CHECKER_MAP_NAME)):
        doc = maps.get(key)
        if not isinstance(doc, dict) or not doc:
            continue
        try:
            (d / name).write_text(
                json.dumps(doc, ensure_ascii=False, indent=2),
                encoding="utf-8", newline="\n")
            written[key] = str(d / name)
        except OSError:
            pass
    counts = case_ir.get("counts") or {}
    return {"path": str(out), "cases": int(counts.get("cases") or 0),
            "categories": int(counts.get("categories") or 0),
            "declared": int(counts.get("declared") or 0),
            "synthesized": int(counts.get("synthesized") or 0),
            "groups": int(counts.get("groups") or 0),
            "sva": int(counts.get("sva") or 0),
            "scb": int(counts.get("scb") or 0),
            "group_map": written.get("group_map", ""),
            "checker_map": written.get("checker_map", "")}


def _str_list(value: Any) -> List[str]:
    return [str(v) for v in value if str(v)] if isinstance(value, list) else []


def _identity_fields(raw: Dict[str, Any]) -> Dict[str, Any]:
    """v2 身份键（`case_id/case_ids/tst_id/cell_ids/legacy`）。

    **缺了就是 legacy**：v1 目录 / 手工摆放的用例没有 CASE 身份，标出来让
    视图与门禁能区分，而不是编一个看起来对的默认值。
    """
    case_id = str(raw.get("case_id") or "")
    case_ids = _str_list(raw.get("case_ids")) or ([case_id] if case_id else [])
    return {
        "case_id": case_id,
        "case_ids": case_ids,
        "tst_id": str(raw.get("tst_id") or ""),
        "cell_ids": _str_list(raw.get("cell_ids")),
        # 三集合指纹（v2 追加）：group/sva/scb + 契约哈希
        "group_ids": _str_list(raw.get("group_ids")),
        "sva_ids": _str_list(raw.get("sva_ids")),
        "scb_ids": _str_list(raw.get("scb_ids")),
        "case_ir_sha": str(raw.get("case_ir_sha") or ""),
        # M1：契约构建物的哈希（证据只对那一版契约有效）
        "contract_hash": str(raw.get("contract_hash") or ""),
        # **legacy = 这份身份不是 v2 写的**（缺 `case_ir_sha` 键），而不是
        # "没有 case_id"：批次级 test 合法地不挂 CASE，把它记成 legacy 会让
        # 视图里 199 条正常执行看起来像"改造前的旧 run"。
        "legacy": "case_ir_sha" not in raw,
    }


def read_task_meta(test_dir: str | Path) -> Dict[str, Any]:
    """读一条用例的身份；**文件缺失时按同一套规则从现场推导**。

    返回字段（全部总是存在，值可能为空串）：

        task / test_name / test / seed / build / stage / tp_ids
        tags / desc / dir / source     source = "meta" | "derived"
    """
    d = Path(test_dir)
    task, test_name, seed = _parse_task_name(d)
    raw: Dict[str, Any] = {}
    path = d / TASK_META_NAME
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        if isinstance(doc, dict):
            raw = doc
    except (OSError, ValueError):
        raw = {}

    # `task` 与 `test_name` 的推导互相独立：meta 可能只写了其中一个。
    task = str(raw.get("task") or task)
    test_name = str(raw.get("test_name") or test_name)
    seed_val = raw.get("seed")
    if seed_val is None:
        seed_val = seed

    tp_ids = raw.get("tp_ids")
    if not isinstance(tp_ids, list):
        tp_ids = []
    tp_ids = [str(t) for t in tp_ids if str(t)]

    return {
        "task": task,
        "test_name": test_name,
        "test": str(raw.get("test") or _test_from_sim_sh(d) or ""),
        "seed": seed_val,
        "build": str(raw.get("build") or d.parent.name.replace("build_", "")),
        "stage": str(raw.get("stage") or _stage_of(d) or ""),
        "tags": list(raw.get("tags") or []) if isinstance(raw.get("tags"), list) else [],
        "tp_ids": tp_ids,
        # ── v2 身份键：缺了就是 legacy（v1 目录 / 手工摆放），不编默认值 ──
        **_identity_fields(raw),
        "desc": str(raw.get("desc") or ""),
        "dir": str(d),
        "source": "meta" if raw else "derived",
    }


def tp_ids_from_tags(tags: Iterable[Any]) -> List[str]:
    """`TP-…` 形式的 tag → tp_id（回归生成时把 tp_id 写成 tag）。"""
    out = []
    for t in tags or []:
        s = str(t).strip()
        if s.upper().startswith("TP-"):
            out.append(s)
    return list(dict.fromkeys(out))


# ────────────────────────────────────────────────────────────────
# 波形定位
# ────────────────────────────────────────────────────────────────

def find_case_wave(test_dir: str | Path) -> str:
    """这条用例的波形文件 → 绝对路径；没有就给空串（**不编路径**）。

    两个来源与界面「波形」列同一口径：

      · `waves/*.db|*.vcd|*.fsdb` —— 回归业务实际 dump 的那份；
      · `wave.log` 里的 `WAVE_PATH=` —— sim.sh 跑完写下的记录。

    存在多个时按 mtime 取最新（重跑会留下旧波形，按时间才对得上"最后一次"）。
    """
    d = Path(test_dir)
    wave_dir = d / "waves"
    cands: List[Path] = []
    if wave_dir.is_dir():
        for suffix in _WAVE_SUFFIXES:
            cands.extend(p for p in wave_dir.glob(f"*{suffix}") if p.is_file())
    if cands:
        newest = max(cands, key=lambda p: p.stat().st_mtime)
        return str(newest.resolve())
    m = _WAVE_LOG_RE.search(_first_text(d / "wave.log"))
    if m:
        cand = m.group(1).strip().strip("'\"")
        if cand and not cand.upper().startswith("NOT_FOUND") and Path(cand).is_file():
            return str(Path(cand).resolve())
    return ""


def find_case_log(test_dir: str | Path) -> str:
    """`sim_vsim.log`（首选）或 `sim.log` 的路径；没有给空串。"""
    d = Path(test_dir)
    for name in ("sim_vsim.log", "sim.log"):
        p = d / name
        if p.is_file():
            return str(p.resolve())
    return ""


# ────────────────────────────────────────────────────────────────
# 日志判据
# ────────────────────────────────────────────────────────────────

def parse_case_log(text: str) -> Dict[str, Any]:
    """仿真日志 → `{uvm_errors, uvm_fatal, scb, assertions, log_ok}`。

    只做**事实提取**，不在这里判签核 —— 判据在 `collect_real_coverage`：

        scb.mismatched   None = 日志里没有比对结论（**不是 0**）
        assertions       `规则 <name> 违规 <n> 次` 的收口行

    UVM 的汇总行是 `UVM_ERROR :    0`；逐条违规是 `UVM_ERROR @ …`。两种都要
    认：有汇总行以汇总行为准，没有就数逐条。
    """
    text = text or ""
    scb = {"total": None, "matched": None, "mismatched": None}
    for m in _SCB_RE.finditer(text):
        scb = {"total": int(m.group(1)), "matched": int(m.group(2)),
               "mismatched": int(m.group(3))}
    # 单条 scoreboard 的收口行（`[SCB <id>]`）—— 有就用它做逐 SB 证据
    scb_by_id: Dict[str, Dict[str, int]] = {}
    for m in _SCB_ID_RE.finditer(text):
        scb_by_id[m.group(1)] = {"total": int(m.group(2)),
                                 "matched": int(m.group(3)),
                                 "mismatched": int(m.group(4))}

    summary = [int(x) for x in re.findall(r"UVM_ERROR\s*:\s*(\d+)", text)]
    if summary:
        uvm_errors = max(summary)
    else:
        uvm_errors = (len(re.findall(r"UVM_ERROR\s+@", text))
                      + len(re.findall(r"UVM_FATAL\s+@", text)))
    fatal = [int(x) for x in re.findall(r"UVM_FATAL\s*:\s*(\d+)", text)]

    rules: Dict[str, int] = {}
    for name, n in _DUT_RULE_RE.findall(text):
        rules[name] = max(rules.get(name, 0), int(n))

    # ── 时序判据（P2）：有没有检查、哪几条超窗 ──
    #   None = 这一轮没声明 timing / 没生成检查 —— **不是"时序通过"**。
    summary = _TP_TIMING_SUM_RE.search(text)
    by_tp: Dict[str, int] = {}
    for tp_id, _cycles in _TP_TIMING_RE.findall(text):
        by_tp[tp_id] = by_tp.get(tp_id, 0) + 1
    timing = {
        "checked": int(summary.group(1)) if summary else None,
        "violations": int(summary.group(2)) if summary else None,
        "by_tp": by_tp,
    }

    return {
        "uvm_errors": int(uvm_errors),
        "uvm_fatal": int(max(fatal)) if fatal else 0,
        "scb": scb,
        "scb_by_id": scb_by_id,
        "assertions": {"rules": len(rules), "fired": sum(rules.values()),
                       "by_rule": rules},
        "timing": timing,
        "log_ok": bool(text.strip()),
    }


def read_case_log(test_dir: str | Path) -> tuple:
    """`(日志文本, 日志路径)`；没有日志给 `("", "")`。"""
    p = find_case_log(test_dir)
    if not p:
        return "", ""
    try:
        return Path(p).read_text(encoding="utf-8", errors="replace"), p
    except OSError:
        return "", p


# ────────────────────────────────────────────────────────────────
# waves/manifest.json
# ────────────────────────────────────────────────────────────────

def _rel(path: str, root: Path) -> str:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def write_wave_manifest(output_dir: str | Path,
                        test_dirs: Iterable[str | Path]) -> Dict[str, Any]:
    """把"哪条用例有波形、证明哪些测试点"写成 `<run>/waves/manifest.json`。

    这是签核材料的一部分（**不是缓存**）：`tp_matrix` 说某条 TP 被
    `task@seed` 签核，manifest 必须能反查到那份波形。因此条目里记相对路径
    （可迁移）+ 绝对路径（本机可直接打开）+ 是否真的存在。

    `test_dirs` 由调用方按布局契约给（`layout.test_dirs`），本模块不猜目录结构。
    """
    root = Path(output_dir)
    entries: List[Dict[str, Any]] = []
    by_tp: Dict[str, List[Dict[str, Any]]] = {}
    for d in test_dirs or []:
        meta = read_task_meta(d)
        wave = find_case_wave(d)
        log = find_case_log(d)
        entry = {
            "task": meta["task"],
            "test": meta["test"] or meta["test_name"],
            "seed": meta["seed"],
            "stage": meta["stage"],
            "build": meta["build"],
            "tp_ids": list(meta["tp_ids"]),
            "wave": _rel(wave, root) if wave else "",
            "wave_abs": wave,
            "wave_exists": bool(wave) and Path(wave).is_file(),
            "log": _rel(log, root) if log else "",
            "dir": _rel(str(d), root),
        }
        entries.append(entry)
        for tid in meta["tp_ids"]:
            by_tp.setdefault(tid, []).append({
                "task": meta["task"], "seed": meta["seed"],
                "stage": meta["stage"], "wave": entry["wave"],
                "wave_abs": entry["wave_abs"]})

    payload = {
        "schema": WAVE_MANIFEST_SCHEMA,
        "run": root.name,
        "root": str(root),
        "count": len(entries),
        "with_wave": sum(1 for e in entries if e["wave_exists"]),
        "entries": entries,
        "by_tp": by_tp,
    }
    # 没有任何用例目录 → **不落空索引**。写一份 count=0 的 manifest 会让
    # "没跑回归"看起来像"跑了但没波形"，也会在临时目录/单元测试里留下空壳。
    if not entries:
        return payload
    out = root / WAVE_MANIFEST_DIR / WAVE_MANIFEST_NAME
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
    except OSError:
        pass
    return payload


def read_wave_manifest(output_dir: str | Path) -> Dict[str, Any]:
    """读 `<run>/waves/manifest.json`；没有给 `{}`（判不了，不伪造）。"""
    p = Path(output_dir) / WAVE_MANIFEST_DIR / WAVE_MANIFEST_NAME
    try:
        doc = json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def visualizer_command(wave: str) -> str:
    """给 `wave show` 用的打开命令（Questa Visualizer / GTKWave 兜底）。"""
    if not wave:
        return ""
    if str(wave).lower().endswith(".db"):
        return f"visualizer -wavefile {wave}"
    if str(wave).lower().endswith(".vcd"):
        return f"gtkwave {wave}"
    return str(wave)
