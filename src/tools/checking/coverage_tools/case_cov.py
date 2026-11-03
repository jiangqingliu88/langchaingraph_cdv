"""逐用例取证 —— **一条用例自己的 ucdb** 能证明哪些测试点。

签核口径从「合并库里存在这个 bin」改成「这一条用例、同一次 seed 的库里有
该测试点名下的全部覆盖仓，且这条用例本身是干净的」。

为什么不能只看合并库：合并库只能证明「某条用例打到过」，不能证明「这条
用例证明了这个功能点」；更接不上波形 —— 波形是按用例落的。

本模块只做取证与汇总；`vcover` 的文本解析仍复用
`collect_real_coverage._parse_cvg_bin_hits`（**一处实现**，不另起一套）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from config.settings import questa_exe

from src.tools.checking.coverage_tools import cov_api
from src.tools.common.lib import case_meta
from src.tools.common.lib.collect_real_coverage import (
    _lookup_hits, _owned_bins, _parse_cvg_bin_hits, _read_testpoints, _stage_of)

CASE_COV_SCHEMA = "case_cov_v1"
CASE_COV_CACHE_SCHEMA = "case_cov_cache_v1"
CASE_TP_SCHEMA = "case_tp_v1"

#: 签核不通过的机器码 → 人话（写进 case_cov / case_tp 的 reasons）。
REASON_TEXT = {
    "no_owner_case": "没有用例按 execution.test 归属到这条测试点",
    "no_cov_db": "这条用例没有落覆盖率库",
    "coverstore_error": "覆盖率库转换/读取失败",
    "no_declared_bin": "测试点没有声明覆盖仓（模型缺口）",
    "bin_miss": "测试点名下的覆盖仓没有全部命中",
    "illegal_bin": "命中了 illegal_bin（一票否决）",
    "no_log": "没有仿真日志，判不了 UVM/SCB 结论",
    "uvm_error": "UVM_ERROR/UVM_FATAL 非零",
    "no_scb_evidence": "日志里没有 SCB 比对结论（mismatched=…）",
    "scb_mismatch": "SCB mismatched 非零",
    "assert_fired": "DUT 检查规则触发",
    "wave_missing": "这条用例没有波形",
    "timing_violation": "时序窗口超窗（timing.expect_cycles）",
    "behavior_pending": "行为域执行后端未接（P1b）",
}


# ────────────────────────────────────────────────────────────────
# vcover / 目录
# ────────────────────────────────────────────────────────────────

def _parse_cvg_illegal_hits(text: str) -> dict:
    """`vcover -cvg -details` → `{covergroup: {coverpoint: {illegal_bin: hits}}}`。

    `_parse_cvg_bin_hits` 的正则是 `(?:illegal_)?bin`，会把 `illegal_bin` 当
    普通 bin 收进去 —— 于是"命中了一个不该到达的状态"在普通矩阵里看不出来。
    签核要一票否决它，所以单独再解析一遍（只扫逐 bin 命中数那段）。
    """
    out: dict = {}
    head = text.find("COVERGROUP COVERAGE:")
    seg = text[:head] if head >= 0 else text
    cg = cp = ""
    for ln in seg.splitlines():
        m = re.match(r"\s*TYPE\s+(\S+)\s*$", ln)
        if m:
            cg = m.group(1).rstrip("/").split("/")[-1]
            out.setdefault(cg, {})
            cp = ""
            continue
        m = re.match(r"\s*Coverpoint\s+(\S+)\s+", ln)
        if m:
            cp = m.group(1)
            continue
        m = re.match(r"\s*illegal_bin\s+(\S+)\s+(\d+)", ln)
        if m and cg and cp:
            out[cg].setdefault(cp, {})[m.group(1)] = int(m.group(2))
    return out


def _illegal_hits_for(illegal: dict, cp_name: str) -> list:
    """某个 coverpoint 下命中的 illegal_bin（优先 DUT 探针那一组）。"""
    out = []
    if not cp_name:
        return out
    for cg in sorted(illegal, key=lambda g: (not g.startswith("cg_dut"), g)):
        for name, hits in (illegal[cg].get(cp_name) or {}).items():
            if int(hits) > 0:
                out.append(name)
    return out


def _case_dirs(od: Path) -> list:
    """run 根下所有用例目录（两种布局都认）—— 走布局契约，不自己拼。"""
    try:
        from src.layers.l1_infrastructure.layout import test_dirs
        return list(test_dirs(od))
    except Exception:                                  # noqa: BLE001 旁路
        return sorted(Path(od).glob("regression_run/**/test_*"))


def _rel_to(path: str, base: Path) -> str:
    if not path:
        return ""
    try:
        return Path(path).resolve().relative_to(Path(base).resolve()).as_posix()
    except (ValueError, OSError):
        return str(path)


def _vcover_cvg_report(ucdb: str) -> tuple:
    """`vcover report -cvg -details <ucdb>` → `(文本, 错误)`。

    功能覆盖率**必须**先把 coverstore 转成 UCDB 再报（见
    `cov_api.materialize_ucdb`）；直接对 `questa.db` 跑只读得到代码覆盖率。
    """
    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return "", f"vcover not found: {vcover}"
    try:
        proc = subprocess.run(
            [vcover, "report", "-cvg", "-details", str(Path(ucdb).resolve())],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        return "", f"vcover 跑不起来：{e}"
    if proc.returncode != 0 and not (proc.stdout or "").strip():
        return "", ((proc.stderr or proc.stdout or "")
                    .strip()[-300:] or f"vcover 退出码 {proc.returncode}")
    return proc.stdout or "", ""


# ────────────────────────────────────────────────────────────────
# 一条用例的原始事实（带缓存）
# ────────────────────────────────────────────────────────────────

def _case_path(od: Path, stage: str, task: str, name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(task or "case"))
    return od / "coverage" / "case_cov" / (stage or "flat") / f"{safe}.{name}"


def _cache_is_fresh(cache: Path, cov_db: str, log_path: str) -> bool:
    try:
        c = cache.stat().st_mtime
    except OSError:
        return False
    for src in (cov_db, log_path):
        if not src:
            continue
        try:
            if Path(src).stat().st_mtime > c:
                return False
        except OSError:
            return False
    return True


def _tst(test: str, seed) -> str:
    """`TST-<test>@<seed>` —— 与 `humanview.case_ir.tst_id_of` 同一口径。"""
    try:
        from src.tools.humanview.case_ir import tst_id_of
        return tst_id_of(test, seed)
    except Exception:                            # noqa: BLE001 身份层不可用不挡聚合
        return f"TST-{test}@{seed}" if test else ""


def _case_facts(od: Path, test_dir: Path, *, force: bool = False) -> dict:
    """一条用例的**原始事实**（不判签核）+ 缓存（覆盖率库只读一次）。

    缓存 `case_cov_cache_v1` 只存**与 TP IR 无关**的原始事实。测试点的 proof
    obligation 每次现算 —— 模型改了 bin，旧缓存的判定不能跟着漂。

    波形**不**从缓存回填：它可能在仿真结束后才落盘，也可能被清理掉。
    """
    meta = case_meta.read_task_meta(test_dir)
    cov_db, cov_source = cov_api.find_coverage_db(test_dir)
    log_text, log_path = case_meta.read_case_log(test_dir)
    log_facts = case_meta.parse_case_log(log_text)
    wave = case_meta.find_case_wave(test_dir)
    # 后缀用 `.json.cache` 而不是 `.json`：`case_cov/**/*.json` 是**签核材料**
    # 的计数口径（`docs/design/...` 的验收清单），缓存不能混进去。
    cache = _case_path(od, meta["stage"], meta["task"], "json.cache")

    base = {
        "task": meta["task"], "test": meta["test"] or meta["test_name"],
        "test_name": meta["test_name"], "seed": meta["seed"],
        "stage": meta["stage"], "build": meta["build"], "dir": meta["dir"],
        # 身份脊梁（v2）：CASE 在生成期注入，TST 由 test+seed 派生。
        # 旧目录没有这些键 → 空串 + legacy=True，绝不编一个看起来对的。
        "case_id": meta.get("case_id", ""),
        "case_ids": list(meta.get("case_ids") or []),
        "tst_id": meta.get("tst_id", "") or _tst(meta["test"] or meta["test_name"],
                                                  meta["seed"]),
        "legacy": bool(meta.get("legacy")),
        # 契约哈希 + 三集合指纹（task_meta v2 写，case_cov 原样带出）
        "case_ir_sha": str(meta.get("case_ir_sha") or ""),
        "group_ids": list(meta.get("group_ids") or []),
        "sva_ids": list(meta.get("sva_ids") or []),
        "scb_ids": list(meta.get("scb_ids") or []),
        "cov_db": cov_db, "cov_source": cov_source,
        "ucdb": "", "ucdb_abs": "", "log": log_path,
        "wave": wave, "wave_abs": wave, "log_facts": log_facts,
        "hits": {}, "illegal": {}, "error": "", "cached": False,
    }
    if not cov_db:
        base["error"] = "no_cov_db"
        return base

    if not force and _cache_is_fresh(cache, cov_db, log_path):
        try:
            cached = json.loads(cache.read_text(encoding="utf-8",
                                                errors="replace"))
        except (OSError, ValueError):
            cached = None
        if isinstance(cached, dict) and cached.get("schema") == CASE_COV_CACHE_SCHEMA:
            base.update({k: cached.get(k, base[k]) for k in (
                "ucdb", "ucdb_abs", "hits", "illegal", "error")})
            base["cached"] = True
            base["wave_abs"] = base["wave"]
            return base

    ucdb, why = cov_api.materialize_ucdb(cov_db)
    if why:
        base["error"], base["detail"] = "coverstore_error", why
        return base
    text, why = _vcover_cvg_report(ucdb)
    if why:
        base["error"], base["detail"] = "coverstore_error", why
        return base
    base["ucdb"] = _rel_to(ucdb, Path(meta["dir"]))
    base["ucdb_abs"] = ucdb
    base["hits"] = _parse_cvg_bin_hits(text)
    base["illegal"] = _parse_cvg_illegal_hits(text)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({
            "schema": CASE_COV_CACHE_SCHEMA,
            "task": base["task"], "test": base["test"], "seed": base["seed"],
            "stage": base["stage"], "cov_db": cov_db,
            "ucdb": base["ucdb"], "ucdb_abs": base["ucdb_abs"],
            "hits": base["hits"], "illegal": base["illegal"],
        }, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    return base


# ────────────────────────────────────────────────────────────────
# 判定
# ────────────────────────────────────────────────────────────────

def _signoff_reasons(facts: dict, owned: list, missing: list,
                     illegal: list, *, require_wave: bool) -> list:
    """一票否决项 → 机器码列表（空 = 可签核）。

    判据缺一不可：仓全中、illegal 干净、UVM_ERROR=0、SCB mismatched=0、
    断言不触发、有波形。**判不了**（没有日志 / 没有比对结论）也算不通过 ——
    "没报错"不等于"验过了"。
    """
    log_facts = facts.get("log_facts") or {}
    scb = log_facts.get("scb") or {}
    reasons: list = []
    if facts.get("error"):
        reasons.append(facts["error"])
    if not owned:
        reasons.append("no_declared_bin")
    elif missing:
        reasons.append("bin_miss")
    if illegal:
        reasons.append("illegal_bin")
    if not log_facts.get("log_ok"):
        reasons.append("no_log")
    if int(log_facts.get("uvm_errors") or 0) > 0 or int(log_facts.get("uvm_fatal") or 0) > 0:
        reasons.append("uvm_error")
    if scb.get("mismatched") is None:
        reasons.append("no_scb_evidence")
    elif int(scb.get("mismatched") or 0) > 0:
        reasons.append("scb_mismatch")
    if int((log_facts.get("assertions") or {}).get("fired") or 0) > 0:
        reasons.append("assert_fired")
    if require_wave and not facts.get("wave"):
        reasons.append("wave_missing")
    return reasons


def _tp_case_entry(tp: dict, facts: dict, *, require_wave: bool) -> dict:
    """一条测试点在**这一条用例**里的取证结论。"""
    cp_name = str(tp.get("coverpoint") or "")
    owned = _owned_bins(tp)
    bin_hits = {b: _lookup_hits(facts.get("hits") or {}, cp_name, b)
                for b in owned}
    got = sum(1 for v in bin_hits.values() if v is not None and v > 0)
    missing = [b for b, v in bin_hits.items() if v is None or v <= 0]
    illegal = _illegal_hits_for(facts.get("illegal") or {}, cp_name)
    reasons = _signoff_reasons(facts, owned, missing, illegal,
                               require_wave=require_wave)
    # 时序（P2）：`None` = 这一轮没声明/没检查 —— 不是"通过"。
    # 序列型超窗只记 `timing_ok=False`，**不否决**（设计稿 §6.2）。
    timing = (facts.get("log_facts") or {}).get("timing") or {}
    timing_ok = None
    if timing.get("checked") is not None:
        timing_ok = timing.get("by_tp", {}).get(
            str(tp.get("tp_id") or ""), 0) == 0
        kind = str((tp.get("realization") or {}).get("kind") or "")
        if not timing_ok and kind != "sequence":
            reasons.append("timing_violation")
    return {
        "tp_id": tp.get("tp_id"),
        "dimension": tp.get("dimension"),
        "value": tp.get("value"),
        "coverpoint": cp_name,
        "owned": owned,
        "hits": bin_hits,
        "missing": missing,
        "pct": round(100.0 * got / len(owned), 2) if owned else None,
        "illegal_hits": illegal,
        "timing_ok": timing_ok,
        "status": "SIGNED_OFF" if not reasons else "UNSIGNED",
        "reasons": reasons,
        "reason_text": [REASON_TEXT.get(r, r) for r in reasons],
    }


def _owner_tps_for_case(meta: dict, tp_by_id: dict, tp_by_test: dict) -> tuple:
    """这条用例归属哪些测试点 + 归属依据。

    优先级：`task_meta.tp_ids`（回归生成时从 TP IR 反查）> 按 UVM 类反查。
    后者是**兼容老目录**的：那些目录没有 task_meta，只能按
    `execution.test` 对上 —— 依据写进结果，签核报告里能看出是哪一层。
    """
    ids = [str(t) for t in (meta.get("tp_ids") or [])]
    tps = [tp_by_id[t] for t in ids if t in tp_by_id]
    if tps:
        return tps, "task_meta"
    test = str(meta.get("test") or "")
    if test and test in tp_by_test:
        return list(tp_by_test[test]), "test_class"
    return [], ""


def _stage_rank(stage: str) -> int:
    try:
        return case_meta.STAGE_DIRS.index(stage) if stage in case_meta.STAGE_DIRS else 99
    except ValueError:                                 # noqa: PERF203
        return 99


# ────────────────────────────────────────────────────────────────
# 汇总
# ────────────────────────────────────────────────────────────────

def _select_case_dirs(dirs: list, tp_by_id: dict, tp_by_test: dict,
                      max_cases: int) -> tuple:
    """超出采样上限时**先保归属用例**；返回 `(selected, sampled, notes)`。"""
    if not max_cases or len(dirs) <= max_cases:
        return dirs, False, []
    metas = [(d, case_meta.read_task_meta(d)) for d in dirs]
    own = [d for d, m in metas
           if _owner_tps_for_case(m, tp_by_id, tp_by_test)[0]]
    rest = [d for d, _m in metas if d not in own]
    selected = (own + rest)[:max_cases]
    note = (f"逐用例取证采样：只解析 {len(selected)}/{len(dirs)} 条用例"
            f"（max_cases={max_cases}）—— 未解析的用例标注 `evidence_sampled`，"
            f"不当作已签核")
    return selected, True, [note]


def _case_timing_ok(facts: dict):
    """用例级时序结论：`None` = 没检查（不是通过），否则 `violations == 0`。"""
    timing = (facts.get("log_facts") or {}).get("timing") or {}
    if timing.get("checked") is None:
        return None
    return int(timing.get("violations") or 0) == 0


def _evd(run_id: str, test: str, seed) -> str:
    try:
        from src.tools.humanview.case_ir import evd_id_of
        return evd_id_of(run_id, test, seed)
    except Exception:                            # noqa: BLE001 身份层不可用不挡聚合
        return f"EVD-{run_id}-{test}@{seed}" if test else ""


def _cell_ids(owner_tps: list) -> list:
    """这条用例占住的签核格子（CG × P）—— **派生**，不手写。"""
    try:
        from src.tools.checking.coverage_tools.cell_matrix import cell_id_of
    except Exception:                            # noqa: BLE001
        return []
    out = set()
    for tp in owner_tps or []:
        if not isinstance(tp, dict):
            continue
        cid = cell_id_of(tp.get("dimension"),
                         (tp.get("execution") or {}).get("stage") or tp.get("stage"))
        if cid:
            out.add(cid)
    return sorted(out)


#: 三集合状态的"好坏"排序（越大越差）；`NOT_APPLICABLE` 不参与比较。
_STATUS_RANK = {"PROVEN": 0, "NOT_APPLICABLE": 0, "PARTIAL": 1,
                "PENDING_BACKEND": 2, "NOT_EXECUTED": 3, "MISSING": 4}


def _worst(statuses) -> str:
    real = [s for s in statuses if s and s != "NOT_APPLICABLE"]
    if not real:
        return "NOT_APPLICABLE"
    return max(real, key=lambda s: _STATUS_RANK.get(s, 4))


def _read_json(path: Path) -> dict:
    try:
        doc = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    return doc if isinstance(doc, dict) else {}


def _load_case_contract(od: Path) -> dict:
    """`coverage/case_ir.json` → `{case_id: case}`（三集合契约）。"""
    doc = _read_json(od / "coverage" / "case_ir.json")
    return {str(c.get("id") or ""): c for c in doc.get("cases") or []
            if isinstance(c, dict) and c.get("id")}


def _functional_status(mine: list, hit: list) -> str:
    if mine and len(hit) == len(mine):
        return "PROVEN"
    return "PARTIAL" if any(float(e.get("pct") or 0) > 0 for e in mine) else "MISSING"


def _timing_status(timing_ok) -> str:
    if timing_ok is True:
        return "PROVEN"
    return "MISSING" if timing_ok is False else "NOT_APPLICABLE"


def _data_status(scb: dict) -> str:
    matched = scb.get("matched")
    if matched is None:
        return "NOT_APPLICABLE"
    if int(matched) > 0 and int(scb.get("mismatched") or 0) == 0:
        return "PROVEN"
    return "MISSING"


def _group_evidence(item: dict, entries: list, facts: dict,
                    timing_ok) -> dict:
    """一组覆盖组证据：functional / timing / data / path + result。"""
    required = list(item.get("required_layers") or
                    ["functional", "timing", "data"])
    tp_ids = {str(t) for t in (item.get("tp_ids") or [])}
    mine = [e for e in entries if not tp_ids or str(e.get("tp_id")) in tp_ids]
    hit = [e for e in mine if float(e.get("pct") or 0) >= 100.0]
    functional = _functional_status(mine, hit)
    timing = _timing_status(timing_ok)
    scb = facts.get("scb_summary") or {}
    data = _data_status(scb)
    path = "PENDING_BACKEND" if "path" in required else "NOT_APPLICABLE"
    layers = {"functional": functional, "timing": timing,
              "data": data, "path": path}
    return {
        "group": item.get("group", ""),
        # 覆盖描述：功能点 / 覆盖类型 / 作用域 / 覆盖点 / 需求 / 检查项。
        # 只给 CG 编号的话，读的人没法判断"这条用例证明的是哪块逻辑"。
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "coverage_type": item.get("coverage_type", ""),
        "scope": item.get("scope", ""),
        "coverpoints": list(item.get("coverpoints") or []),
        "requirements": list(item.get("requirements") or []),
        "checks": list(item.get("checks") or []),
        "cell": item.get("cell", ""),
        "required_layers": required,
        "functional": {"status": functional,
                       "bins_hit": [e.get("tp_id") for e in hit],
                       "bins_miss": [e.get("tp_id") for e in mine
                                     if e not in hit]},
        "timing": {"status": timing},
        "data": {"status": data, "matched": scb.get("matched"),
                 "mismatched": scb.get("mismatched")},
        "path": {"status": path},
        "result": _worst([layers[k] for k in required]),
    }


def _sva_evidence(items: list, facts: dict) -> list:
    """断言证据：`by_rule` 里有记录才算"求值过"；0 违规才算 PROVEN。"""
    by_rule = ((facts.get("log_facts") or {}).get("assertions") or {}).get("by_rule") or {}
    lowered = {str(k).lower(): v for k, v in by_rule.items()}
    out = []
    for item in items:
        name = str(item.get("name") or "")
        key = name.lower() or str(item.get("id") or "").removeprefix("SVA-").lower()
        fired = lowered.get(key)
        if fired is None:
            status, hit = "MISSING", None
        elif int(fired) == 0:
            status, hit = "PROVEN", None
        else:
            status, hit = "MISSING", None
        out.append({
            "id": item.get("id", ""), "cell": item.get("cell", ""),
            "name": name, "expr": item.get("expr", ""),
            "message": item.get("message", ""),
            "hit": hit, "fail": int(fired or 0),
            "cover_property_hit": None, "status": status,
        })
    return out


def _scb_evidence(items: list, facts: dict) -> list:
    """SCB 证据：优先 `[SCB <id>]` 逐条收口，其次 env 的 `[SCB_DUT]` 汇总。

    契约项自带 `evidence` 模式（`auto` / `aggregate` / `log`）：
      · `log`       —— 必须有自己的收口行，没有就判未执行；
      · `aggregate` —— 用 env 的聚合行；
      · `auto`      —— 先找自己那行，找不到退回聚合。
    用了哪一层写进 `evidence_level`，**不把聚合证据冒充成逐条证据**。
    """
    aggregate = facts.get("scb_summary") or {}
    by_id = (facts.get("log_facts") or {}).get("scb_by_id") or {}
    return [{
        "id": str(item.get("id") or ""), "cell": item.get("cell", ""),
        "name": item.get("name", ""),
        "description": item.get("description", ""),
        "model": item.get("model", ""),
        "evidence_mode": item.get("evidence", "auto"),
        "exec": int((data or {}).get("total") or 0),
        "matched": (data or {}).get("matched"),
        "mismatched": (data or {}).get("mismatched"),
        "evidence_level": level or "none",
        "status": _scb_status(data),
    } for item in items for data, level in [_scb_source(item, aggregate, by_id)]]


def _scb_source(item: dict, aggregate: dict, by_id: dict) -> tuple:
    """这条 SB 的证据来自哪：自己的收口行优先，其次 env 聚合行。"""
    sb_id = str(item.get("id") or "")
    raw_id = sb_id[3:] if sb_id.startswith("SB-") else sb_id
    own = by_id.get(sb_id) or by_id.get(raw_id)
    if own:
        return own, "per_scb"
    if str(item.get("evidence") or "auto") != "log" \
            and aggregate.get("matched") is not None:
        return aggregate, "aggregate"
    return None, ""


def _scb_status(data) -> str:
    if data is None:
        return "NOT_EXECUTED"
    if int(data.get("mismatched") or 0) > 0:
        return "MISSING"
    return "PROVEN" if int(data.get("matched") or 0) > 0 else "NOT_EXECUTED"


def _case_status(groups: list, sva: list, scb: list) -> str:
    """三集合 → case 总状态：全 PROVEN/NA 才是 VERIFIED。

    **三集合全空 = 没有契约 = 判不了**（批次级 test 不挂 case）：返回空串，
    不能落成 VERIFIED —— 那等于拿"没声明"冒充"验证通过"。
    """
    if not groups and not sva and not scb:
        return ""
    worst = _worst([g.get("result") for g in groups]
                   + [s.get("status") for s in sva]
                   + [s.get("status") for s in scb])
    if worst in ("PROVEN", "NOT_APPLICABLE"):
        return "VERIFIED"
    if worst == "MISSING":
        return "NOT_VERIFIED"
    return "PARTIAL"


def _evaluate_case(od: Path, test_dir: Path, owner_tps: list, basis: str,
                   *, require_wave: bool, force: bool,
                   contract: dict = None) -> dict:
    """一条用例 → `case_cov_v1` 记录（并落盘）。"""
    facts = _case_facts(od, test_dir, force=force)
    entries = [_tp_case_entry(tp, facts, require_wave=require_wave)
               for tp in owner_tps]
    case = (contract or {}).get(str(facts.get("case_id") or "")) or {}
    timing_ok = _case_timing_ok(facts)
    groups = [_group_evidence(g, entries, facts, timing_ok)
              for g in (case.get("groups") or []) if isinstance(g, dict)]
    sva = _sva_evidence(case.get("sva") or [], facts)
    scb = _scb_evidence(case.get("scb") or [], facts)
    rec = {
        "schema": CASE_COV_SCHEMA,
        # ── 身份（EVD）：一次执行一条证据；去重键 (run, tst, seed, cfg) ──
        "evd_id": _evd(od.name, facts["test"], facts["seed"]),
        "run_id": od.name,
        "tst_id": facts.get("tst_id", ""),
        "case_id": facts.get("case_id", ""),
        "case_ids": list(facts.get("case_ids") or []),
        "cell_ids": _cell_ids(owner_tps),
        "legacy": bool(facts.get("legacy")),
        "case_ir_sha": str(facts.get("case_ir_sha", "")),
        # ── 三集合证据（与 case_ir 契约一一对应；缺项标 MISSING）──
        "groups": groups,
        "sva": sva,
        "scb": scb,
        "case_status": _case_status(groups, sva, scb),
        "task": facts["task"], "test": facts["test"],
        "test_name": facts["test_name"], "seed": facts["seed"],
        "stage": facts["stage"], "build": facts["build"],
        "dir": _rel_to(facts["dir"], od),
        "ucdb": facts.get("ucdb", ""), "ucdb_abs": facts.get("ucdb_abs", ""),
        # 原始 coverstore（`cov/<test>/questa.db`）与物化后的 UCDB 都记：
        # 前者是现场产物，后者是 `vcover report` 真正读的那份。
        "cov_db": _rel_to(facts.get("cov_db", ""), od),
        "cov_source": facts.get("cov_source", ""),
        "log": _rel_to(facts.get("log", ""), od),
        "wave": _rel_to(facts.get("wave", ""), od),
        "wave_abs": facts.get("wave_abs", ""),
        "owner_basis": basis,
        "tp": entries,
        "uvm_errors": int((facts.get("log_facts") or {}).get("uvm_errors") or 0),
        "uvm_fatal": int((facts.get("log_facts") or {}).get("uvm_fatal") or 0),
        # `scb` 现在是**三集合证据**（上面）；原始 `[SCB_DUT]` 汇总改名
        # `scb_summary` —— 两个不同东西共用一个键会让读者以为是同一件事。
        "scb_summary": (facts.get("log_facts") or {}).get("scb") or {},
        "assertions": (facts.get("log_facts") or {}).get("assertions") or {},
        # 用例级时序结论：`None` = 这一轮没声明/没检查（不是"通过"）。
        "timing_ok": timing_ok,
        "error": facts.get("error", ""),
        "cached": bool(facts.get("cached")),
    }
    if facts.get("detail"):
        rec["error_detail"] = facts["detail"]
    try:
        out = _case_path(od, rec["stage"], rec["task"], "json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                       encoding="utf-8", newline="\n")
    except OSError:
        pass
    return rec


def _sorted_signed(entries: list) -> list:
    """满足全部判据的用例，按 `(stage, task)` 排序 —— 签核取第一条。"""
    return sorted([e for e in entries if e["status"] == "SIGNED_OFF"],
                  key=lambda e: (_stage_rank(e.get("stage", "")),
                                 str(e.get("task"))))


def _unsigned_reasons(entries: list) -> list:
    if not entries:
        return ["no_owner_case"]
    return sorted({r for e in entries for r in (e.get("reasons") or [])})


def _summarize_tp(tp: dict, entries: list) -> dict:
    """一条测试点的跨用例结论：**任何一条**满足全部判据即可签核。"""
    tid = str(tp.get("tp_id") or "")
    kind = str((tp.get("realization") or {}).get("kind") or "")
    if not kind:
        kind = "observe" if bool(tp.get("observe_only")) else "stimulus"
    owner_test = str((tp.get("execution") or {}).get("test") or "")
    if _stage_of(tp) == "behavior":
        return {"tp_id": tid, "kind": kind, "owner_test": owner_test,
                "owned_bins": _owned_bins(tp), "status": "PENDING_BACKEND",
                "signed_off": False, "signed_off_by": "", "owner_case": "",
                "timing_ok": None, "cases": [], "reasons": ["behavior_pending"]}
    signed = _sorted_signed(entries)
    picked = signed[0] if signed else (entries[0] if entries else None)
    timing_ok = _timing_state(entries)
    return {
        "tp_id": tid, "kind": kind, "owner_test": owner_test,
        "owned_bins": _owned_bins(tp),
        "status": "SIGNED_OFF" if signed else "UNSIGNED",
        "signed_off": bool(signed),
        "signed_off_by": (f"{picked['task']}@{picked['seed']}"
                          if signed and picked else ""),
        "owner_case": (picked["task"] if picked else ""),
        "owner_stage": (picked.get("stage", "") if picked else ""),
        "wave": (picked.get("wave", "") if picked else ""),
        "wave_abs": (picked.get("wave_abs", "") if picked else ""),
        "timing_ok": timing_ok,
        "cases": [{k: e.get(k) for k in
                   ("task", "seed", "stage", "status", "pct",
                    "reasons", "owner_basis", "timing_ok")}
                  for e in entries],
        "reasons": [] if signed else _unsigned_reasons(entries),
        # 三集合（TP 行来自 TP IR；case_status 取 owner 用例的结论）
        "case_id": tp.get("case_id", ""),
        "case_status": str((picked or {}).get("case_status", "")),
    }


def _timing_state(entries: list):
    """多用例的时序结论：任一条 `False` → False；全 `None` → None。

    `None` = 这一轮没声明/没检查（不是"通过"）。与三态判定同一纪律。
    """
    states = [e.get("timing_ok") for e in entries if "timing_ok" in e]
    if any(s is False for s in states):
        return False
    if any(s is True for s in states):
        return True
    return None


def _counts(by_tp: dict, unsigned: list) -> dict:
    return {
        "total": len(by_tp),
        "signed_off": sum(1 for v in by_tp.values()
                          if v["status"] == "SIGNED_OFF"),
        "unsigned": len(unsigned),
        "behavior_pending": sum(1 for v in by_tp.values()
                                if v["status"] == "PENDING_BACKEND"),
        "no_owner_case": sum(1 for v in by_tp.values()
                             if v["reasons"] == ["no_owner_case"]),
        "timing_warn": sum(1 for v in by_tp.values()
                           if v.get("timing_ok") is False
                           and v.get("kind") == "sequence"),
    }


def _read_tp_dicts(od: Path) -> list:
    return [tp for tp in _read_testpoints(od) if isinstance(tp, dict)]


def _index_tps(tps: list) -> tuple:
    """`(tp_id → tp, execution.test → [tp…])`。"""
    tp_by_id = {str(tp.get("tp_id") or ""): tp for tp in tps if tp.get("tp_id")}
    tp_by_test: dict = {}
    for tp in tps:
        test = str((tp.get("execution") or {}).get("test") or "")
        if test:
            tp_by_test.setdefault(test, []).append(tp)
    return tp_by_id, tp_by_test


def _entries_for(tid: str, cases: list) -> list:
    return [dict(e, task=rec["task"], seed=rec["seed"],
                 case_id=rec.get("case_id", ""),
                 case_status=rec.get("case_status", ""),
                 stage=rec["stage"], wave=rec["wave"],
                 wave_abs=rec["wave_abs"], owner_basis=rec["owner_basis"],
                 cached=rec["cached"])
            for rec in cases for e in rec["tp"] if e.get("tp_id") == tid]


def _by_case(cases: list) -> dict:
    return {
        rec["task"]: {
            "test": rec["test"], "seed": rec["seed"],
            "stage": rec["stage"], "owner_basis": rec["owner_basis"],
            "case_id": rec.get("case_id", ""),
            "tst_id": rec.get("tst_id", ""),
            "case_status": rec.get("case_status", ""),
            # 三集合反向索引（视图与门禁按 checker 反查用例）
            "group_ids": [g.get("group") for g in rec.get("groups") or []
                          if g.get("group")],
            "sva_ids": [s.get("id") for s in rec.get("sva") or [] if s.get("id")],
            "scb_ids": [s.get("id") for s in rec.get("scb") or [] if s.get("id")],
            "tp_ids": [e["tp_id"] for e in rec["tp"]],
            "signed_tp_ids": [e["tp_id"] for e in rec["tp"]
                              if e["status"] == "SIGNED_OFF"],
        }
        for rec in cases
    }


def case_cov_matrix(od: Path, *, max_cases: int = 0,
                    require_wave: bool = True, force: bool = False) -> dict:
    """逐用例解析回归目录 → 覆盖切片 + 用例 ↔ 测试点证据表。

    产物：

        coverage/case_cov/<stage>/<task>.json   一条用例一份
        coverage/case_tp.json                   用例 ↔ TP（正查/反查都行）

    没有 TP IR 时返回空（`_tp_matrix` 也这么做）：没有测试点就没有"签核谁"
    这个问题，不必去跑几百次 vcover。
    """
    od = Path(od)
    tps = _read_tp_dicts(od)
    if not tps:
        return {"schema": CASE_TP_SCHEMA, "cases": [], "by_tp": {}, "by_case": {},
                "counts": {"total": 0, "signed_off": 0, "unsigned": 0,
                           "behavior_pending": 0, "no_owner_case": 0},
                "signed_off_missing_wave": [], "evidence_sampled": False,
                "notes": ["没有 TP IR（coverage/testpoints.yaml）—— 不产逐用例证据"],
                "errors": [], "case_count": 0}

    tp_by_id, tp_by_test = _index_tps(tps)
    contract = _load_case_contract(od)
    selected, sampled, notes = _select_case_dirs(
        _case_dirs(od), tp_by_id, tp_by_test, max_cases)

    cases: list = []
    errors: list = []
    for d in selected:
        meta = case_meta.read_task_meta(d)
        owner_tps, basis = _owner_tps_for_case(meta, tp_by_id, tp_by_test)
        if sampled and not owner_tps:
            continue
        rec = _evaluate_case(od, d, owner_tps, basis,
                             require_wave=require_wave, force=force,
                             contract=contract)
        if rec.get("error"):
            errors.append(f"{rec['task']}: {rec.get('error_detail') or rec['error']}")
        cases.append(rec)

    # ── 汇总：每条测试点被哪些用例证明 ──
    by_tp = {str(tp.get("tp_id") or ""): _summarize_tp(
        tp, _entries_for(str(tp.get("tp_id") or ""), cases)) for tp in tps}
    unsigned = [{"tp_id": tid, "kind": v["kind"], "reasons": v["reasons"]}
                for tid, v in by_tp.items() if v["status"] == "UNSIGNED"]
    missing_wave = [{"tp_id": tid, "signed_off_by": v["signed_off_by"],
                     "owner_case": v["owner_case"]}
                    for tid, v in by_tp.items()
                    if v["signed_off"] and not v.get("wave_abs")]
    timing_warn = [{"tp_id": tid, "kind": v["kind"]}
                   for tid, v in by_tp.items()
                   if v.get("timing_ok") is False and v.get("kind") == "sequence"]
    result = {
        "schema": CASE_TP_SCHEMA, "run": od.name,
        "counts": _counts(by_tp, unsigned), "by_tp": by_tp,
        "by_case": _by_case(cases), "unsigned": unsigned,
        "signed_off_missing_wave": missing_wave,
        "timing_warn": timing_warn,
        "evidence_sampled": sampled, "case_count": len(cases),
        "notes": notes, "errors": errors[:50], "cases": cases,
    }
    _write_case_tp(od, result)
    return result


def _write_case_tp(od: Path, result: dict) -> None:
    """`coverage/case_tp.json` —— 用例 ↔ 测试点证据表（签核材料）。"""
    p = od / "coverage" / "case_tp.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: v for k, v in result.items() if k != "cases"}
        payload["case_count"] = len(result.get("cases") or [])
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                     encoding="utf-8", newline="\n")
    except OSError:
        pass


def case_coverage_patch(case_index: dict) -> dict:
    """`run()` 用的摘要补丁：有逐用例证据才返回 `{"case_coverage": …}`。

    收成函数是为了让 `run` 少一个分支（架构复杂度预算把 `run` 钉在基线上）。
    """
    if not case_index.get("case_count"):
        return {}
    return {"case_coverage": {
        "case_count": case_index.get("case_count", 0),
        "counts": case_index.get("counts") or {},
        "evidence_sampled": bool(case_index.get("evidence_sampled")),
        "case_tp": "coverage/case_tp.json",
        "notes": list(case_index.get("notes") or []),
        "errors": list(case_index.get("errors") or [])[:10],
    }}
