"""覆盖率矩阵 / 证据（Phase 4 拆分）。"""
import json
import sys
import builtins
from pathlib import Path
from typing import Optional


def print(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


def _parse_cvg_bin_hits(*args, **kwargs):
    from src.ir_plane.decision.evidence.cvg_parse import _parse_cvg_bin_hits as _impl
    return _impl(*args, **kwargs)


def _read_testpoints(od: Path) -> list:
    """读 `coverage/testpoints.yaml`（verify 落的测试点 IR）。没有就空。"""
    p = od / "coverage" / "testpoints.yaml"
    try:
        import yaml as _yaml
        doc = _yaml.safe_load(p.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    tps = doc.get("testpoints") if isinstance(doc, dict) else None
    return tps if isinstance(tps, list) else []


def _lookup_hits(hits: dict, cp_name: str, bin_name: str) -> Optional[int]:
    """`(coverpoint, bin)` → 命中数；**报告里根本没有这一格时返回 `None`**。

    `None` 与 `0` 是两件事：
      · `0`      —— 仓声明了、这次没命中（该补激励）；
      · `None`   —— 报告里压根没有这个仓（模型/生成漂了，该修模型或生成器）。
    把后者记成 0 会让人去补一条**打不中**的用例。

    **优先 DUT 探针那个 covergroup**：`cg_dut` 用的是模型声明的仓名；env_cov 的
    事务通道用的是 `v_zero/v_one/v_rest` 这类自动仓。同一个 `cp_<字段>` 两边都有，
    但只有探针那边的 bin 名能和测试点对上 —— 所以先找 `cg_dut`，再全找。
    """
    if not cp_name or not bin_name:
        return None
    order = sorted(hits, key=lambda g: (not g.startswith("cg_dut"), g))
    for cg in order:
        v = (hits[cg].get(cp_name) or {}).get(bin_name)
        if v is not None:
            return v
    return None


def _stage_of(tp: dict) -> str:
    return str((tp.get("execution") or {}).get("stage") or "")


def _status_for(n, kind: str, observe: bool) -> tuple:
    """命中数 → 矩阵状态。`None` = 报告里没这一格（判不了），不是 0。

    **判定实现在 `verification_os.tp_shadow.status_for_hits`**（v3 M2）：
    本函数只做委托，保证"状态只推导"从 TP 级开始成立 —— 形态与返回值不变，
    但规则不再有两份。
    """
    from src.ir_plane.contract.tp_shadow import status_for_hits

    return status_for_hits(n, kind, observe)


def _behavior_row(tp: dict, cp_name: str, bin_name: str, kind: str,
                  observe: bool, stage: str) -> dict:
    """行为 TP 的矩阵行 —— 没有执行数据，单列 PENDING_BACKEND。"""
    return {
        "tp_id": tp.get("tp_id"),
        "dimension": tp.get("dimension"),
        "value": tp.get("value"),
        "coverpoint": cp_name,
        "bin": bin_name,
        "hits": 0,
        "kind": kind,
        "observe_only": observe,
        "status": "PENDING_BACKEND",
        "requirement": tp.get("requirement"),
        "stage": stage,
        "note": "行为域执行后端未接（P1b）—— 暂不参与覆盖率判定",
    }


def _attribute_rows(rows: list) -> list:
    return [r for r in rows if r.get("stage") != "behavior"]


def _count_stage(rows: list, stage: str) -> int:
    return sum(1 for r in rows if r.get("stage") == stage)


def _row_hits(tp: dict, hits: dict) -> tuple:
    """`(owned_bins, {bin: hits|None}, legacy_hit_count)`。

    多仓 TP 的 legacy 命中数取**最大**（"打到过"）；proof obligation 的
    全部命中判定在逐用例签核那边（`case_cov`），这里不重复。
    """
    cp_name = str(tp.get("coverpoint") or "")
    owned = _owned_bins(tp)
    bin_hits = {b: _lookup_hits(hits, cp_name, b) for b in owned}
    vals = [v for v in bin_hits.values() if v is not None]
    if owned and not vals:
        return owned, bin_hits, None
    return owned, bin_hits, (max(vals) if vals else 0)


def _tp_row(tp: dict, hits: dict, signoff: dict, counts: dict) -> dict:
    """一条测试点 → 矩阵行（合并库 status + 逐用例签核字段）。"""
    cp_name = str(tp.get("coverpoint") or "")
    bin_name = str(tp.get("bin") or "")
    observe = bool(tp.get("observe_only"))
    kind = str((tp.get("realization") or {}).get("kind") or "")
    if not kind:
        kind = "observe" if observe else "stimulus"
    stage = _stage_of(tp)
    if stage == "behavior":
        # 行为域（P1a）：TP 已进 IR，但执行后端（事件序列 → UVM）还没接，
        # 因此**没有覆盖率数据可判**。单列 PENDING_BACKEND，不进
        # drivable 分母、也不算 UNMAPPED（它不是"模型漂了"）。
        counts["PENDING_BACKEND"] = counts.get("PENDING_BACKEND", 0) + 1
        return _behavior_row(tp, cp_name, bin_name, kind, observe, stage)

    owned, bin_hits, n = _row_hits(tp, hits)
    # `_status_for` 对 UNMAPPED 会把 `None` 归成 `0`（"报告里没这一格"与
    # "打中了 0 次"在 **legacy status** 里不区分；逐用例签核那边用
    # `bin_hits` 保留 None，不把模型漂移记成"该补激励"）。
    status, n, is_backdoor = _status_for(n, kind, observe)
    counts[status] = counts.get(status, 0) + 1
    _s = signoff.get(str(tp.get("tp_id") or "")) or {}
    signed = bool(_s.get("signed_off"))
    counts["SIGNED_OFF" if signed else "UNSIGNED"] += 1
    return {
        "tp_id": tp.get("tp_id"),
        "dimension": tp.get("dimension"),
        "value": tp.get("value"),
        "coverpoint": cp_name,
        "bin": bin_name,
        "bins": owned,
        "bin_hits": bin_hits,
        "hits": n,
        "kind": kind,
        "observe_only": observe,
        "status": status,
        "requirement": tp.get("requirement"),
        "stage": ((tp.get("execution") or {}).get("stage") or ""),
        # ── 逐用例签核（与上面的合并库 status 是两回事）──
        "owner_test": (_s.get("owner_test")
                       or ((tp.get("execution") or {}).get("test") or "")),
        "owner_case": _s.get("owner_case", ""),
        "signed_off": signed,
        "signed_off_by": _s.get("signed_off_by", ""),
        "signoff_reasons": _s.get("reasons") or [],
        # 时序（P2）：None = 没声明/没检查，不是"通过"。
        "timing_ok": _s.get("timing_ok"),
        **_tp_contract_fields(tp, _s),
    }


def _tp_contract_fields(tp: dict, summary: dict) -> dict:
    """三集合引用（arch.md）：这条 TP 属于哪些组 / 受哪些 checker 保护。"""
    return {
        "case_id": tp.get("case_id", "") or summary.get("case_id", ""),
        "groups": list(tp.get("groups") or []),
        "sva": list(tp.get("sva") or []),
        "scb": list(tp.get("scb") or []),
        "case_status": summary.get("case_status", ""),
    }


def _matrix_counts(rows: list, counts: dict) -> dict:
    """**三类分开算**：激励 / 后门 / 观测。后门命中不冒充"激励覆盖"。"""
    attr = _attribute_rows(rows)
    out = {"drivable": 0, "drivable_hit": 0, "backdoor": 0,
           "backdoor_hit": 0, "observed": 0, "attr_total": len(attr)}
    for r in attr:
        kind, hits = r["kind"], r["hits"]
        if kind in ("stimulus", "sequence"):
            out["drivable"] += 1
            if hits > 0:
                out["drivable_hit"] += 1
        elif kind == "backdoor":
            out["backdoor"] += 1
            if hits > 0:
                out["backdoor_hit"] += 1
        elif kind == "observe" and hits > 0:
            out["observed"] += 1
    out["observe_only"] = sum(1 for r in rows if r["kind"] == "observe")
    out["signed_off_total"] = counts["SIGNED_OFF"]
    out["unsigned_total"] = counts["UNSIGNED"]
    return out


def _matrix_summary(rows: list, counts: dict, case_index: dict,
                    stats: dict) -> dict:
    drivable, backdoor = stats["drivable"], stats["backdoor"]
    attr_total = stats["attr_total"]
    return {
        "total": len(rows),
        "counts": counts,
        "drivable": drivable,
        "drivable_hit": stats["drivable_hit"],
        "drivable_pct": (round(100.0 * stats["drivable_hit"] / drivable, 2)
                         if drivable else 0.0),
        "backdoor": backdoor,
        "backdoor_hit": stats["backdoor_hit"],
        "backdoor_pct": (round(100.0 * stats["backdoor_hit"] / backdoor, 2)
                         if backdoor else 0.0),
        "observe_only": stats["observe_only"],
        "observed": stats["observed"],
        "behavior_pending": _count_stage(rows, "behavior"),
        # 签核口径（逐用例、逐 seed）
        "signed_off_total": stats["signed_off_total"],
        "unsigned_total": stats["unsigned_total"],
        "signed_off_pct": (round(100.0 * stats["signed_off_total"] / attr_total, 2)
                           if attr_total else 0.0),
        "timing_warn": sum(1 for r in rows
                           if r.get("timing_ok") is False
                           and r.get("kind") == "sequence"),
        "case_evidence": {
            "case_count": case_index.get("case_count", 0),
            "evidence_sampled": bool(case_index.get("evidence_sampled")),
            "counts": case_index.get("counts") or {},
        },
        "missed": [r for r in rows
                   if r["status"] in ("MISS", "UNOBSERVED", "BACKDOOR_MISS")],
        "unsigned": [r for r in rows
                     if not r.get("signed_off") and r.get("stage") != "behavior"],
        "unmapped": [r for r in rows if r["status"] == "UNMAPPED"],
        "rows": rows,
    }


def _tp_matrix(od: Path, coverage: dict, case_index: dict = None,
               *, require_wave: bool = True) -> dict:
    """测试点 × 覆盖仓 → 命中/缺口矩阵 + **逐 TP 签核状态**。

    命中状态（**四态，不把"没激励"混进"没覆盖"**，口径仍是**合并库**）：

        HIT         激励型测试点，它的仓命中了
        MISS        激励型测试点，仓一个都没中
        OBSERVED    观测型测试点，仓命中了（没有激励差异，但状态确实到达过）
        UNOBSERVED  观测型测试点，仓没命中
        UNMAPPED    模型给的 `coverpoint.bin` 在报告里找不到（模型/生成漂了）

    **`status` 回答的是"合并库里有没有"**；`signed_off` 回答的是完全另一个
    问题："有没有**一条用例、同一次 seed** 证明了这个测试点"。两者不能互相
    冒充 —— 合并库里有命中，只能说明某条用例打到过。
    """
    tps = _read_testpoints(od)
    if not tps:
        return {}

    # **优先用计划覆盖率报告**（回归全量用例合并）—— 单测报告只代表一条 test，
    # 拿它给 63 条测试点判命中会把"没跑过的仓"报成 MISS（其实只是那条 test 没打到）。
    report = (Path(str(coverage["tp_report"]))
              if coverage.get("tp_report")
              else Path(str(coverage.get("report_dir") or "")) / "coverage_cvg.txt")
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"error": f"读不到 {report}", "total": len(tps)}

    if case_index is None:
        case_index = _case_cov_matrix(od, require_wave=require_wave)
    signoff = case_index.get("by_tp") or {}
    hits = _parse_cvg_bin_hits(text)
    counts = {"HIT": 0, "MISS": 0, "OBSERVED": 0, "UNOBSERVED": 0,
              "BACKDOOR_HIT": 0, "BACKDOOR_MISS": 0, "UNMAPPED": 0,
              "SIGNED_OFF": 0, "UNSIGNED": 0}
    rows = [_tp_row(tp, hits, signoff, counts)
            for tp in tps if isinstance(tp, dict)]
    return _matrix_summary(rows, counts, case_index,
                           _matrix_counts(rows, counts))


def _write_tp_matrix(od: Path, matrix: dict) -> None:
    """把矩阵落到 `coverage/tp_matrix.json` —— 签核材料的一部分。"""
    p = od / "coverage" / "tp_matrix.json"
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(matrix, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError as e:
        print(f"[coverage] 测试点矩阵落盘失败: {e}")


# ════════════════════════════════════════════════════════════
# 逐用例取证 —— case_cov / case_tp（实现在检查层，解析器复用本模块）
# ════════════════════════════════════════════════════════════
#
# 签核的口径从「合并库里存在这个 bin」改成「**这一条用例自己的 ucdb** 里，
# 该测试点名下的全部覆盖仓命中，且这条用例本身是干净的」。
#
# 实现放在 `tools/checking/coverage_tools/case_cov.py`：那里读 vcover、写
# case_cov / case_tp，但**不复制任何解析器** —— `_parse_cvg_bin_hits` /
# `_lookup_hits` / proof obligation 都还是本模块这一份。


def _owned_bins(tp: dict) -> list:
    """测试点的 **proof obligation**：它名下必须全部命中的仓。

    `bins:`（多仓/交叉）优先；否则单个 `bin:`。空 = 模型没声明（判不了，
    不能当成"通过"）。
    """
    bins = tp.get("bins")
    owned = [str(b) for b in bins if str(b)] if isinstance(bins, list) else []
    if not owned and tp.get("bin"):
        owned = [str(tp["bin"])]
    return owned


def _case_cov_matrix(od: Path, *, max_cases: int = 0,
                     require_wave: bool = True, force: bool = False) -> dict:
    """逐用例解析回归目录 → 覆盖切片 + 用例 ↔ 测试点证据表（委托检查层）。"""
    from src.ir_plane.decision.evidence.case_cov import case_cov_matrix
    return case_cov_matrix(od, max_cases=max_cases, require_wave=require_wave,
                           force=force)


def _semantic_validations(od: Path, result: dict) -> dict:
    """`semantic_validations` —— 「这一步产出的数字到底有没有意义」。

    回答三个此前没人回答的问题，每个都对应一类**看着绿、其实空**的中间态：

        ucdb_nonzero_bins        库落了，可有一个 bin 被命中吗？
        cg_dut_hit_gt_zero       DUT 侧的 covergroup（内部信号/输出端口）真采到了吗？
        constraint_policy_applied 约束生成了，可 `apply()` 真的做事吗？

    ## 三值而不是两值

    `None` = **没测/测不了**，与 `False` = 测了、结论是"没生效"**必须分开**。
    混成一个的话，"这次没跑覆盖率"会被读成"覆盖率是空的"，而前者不是问题、
    后者是。整块读不到时整个键不出现（与 `_artifact_manifest` 同一条纪律）。

    `constraint_policy_applied` **读生成期落下的 `coverage/constraint_status.json`**，
    不去抓仿真日志 —— 策略体落 `default:` 是运行期分支，而那条 `uvm_info` 是
    `UVM_HIGH`，默认 verbosity 下根本不打（`sim.sh` 里也没有 `+UVM_VERBOSITY`）。
    生成期本来就知道答案，抓日志是舍近求远且抓不到。
    """
    notes: list = []
    cov = result.get("coverage") or {}
    cvg = cov.get("functional_detail") or {}

    bin_hits = int(cvg.get("bin_hits") or 0)
    bin_total = int(cvg.get("bin_total") or 0)
    ucdb_nonzero = (bin_hits > 0) if bin_total else None
    if ucdb_nonzero is False:
        notes.append(f"ucdb 落了库但**一个 bin 都没命中**（0/{bin_total}）—— "
                     f"覆盖率数字没有意义，检查仿真是否真跑到 DUT")
    elif ucdb_nonzero is None:
        notes.append("没拿到 bin 命中数（没跑覆盖率或解析失败）—— 判不了")

    # DUT 侧那个 covergroup 单独看：它采的是**内部状态与输出端口**，
    # 事务通道（`cg_<agent>`）采不到那些。它零命中而事务侧有命中，说明
    # bind 探针没接上（覆盖率数字会虚高）。
    cg_dut_actual = None
    for g in (cvg.get("covergroups") or []):
        if "cg_dut" in str(g.get("name") or ""):
            cg_dut_actual = float(g.get("actual") or 0.0)
            break
    if cg_dut_actual is None:
        notes.append("没有 `cg_dut`（这次没用 `sample: dut` 的覆盖点）")
    elif cg_dut_actual <= 0:
        notes.append("`cg_dut` 零命中 —— DUT 探针可能没挂上"
                     "（bind 接口 / config_db 句柄），内部状态与输出端口一个都没采到")

    # 约束：**生成期**的结论，读 verify 落下的状态文件
    cpa = None
    status_file = od / "coverage" / "constraint_status.json"
    if status_file.is_file():
        try:
            st = json.loads(status_file.read_text(encoding="utf-8", errors="replace"))
            cpa = bool(st.get("constraint_policy_applied"))
            if not cpa:
                _backed = st.get("backed_policy_count")
                _total = st.get("policy_count")
                if isinstance(_backed, int) and isinstance(_total, int) and _backed:
                    notes.append(
                        f"约束只部分生效：{_backed}/{_total} 条策略由模型编译出"
                        f"真实赋值，其余 {st.get('unbacked_policy_count', _total - _backed)} "
                        f"条仍落在 `default:` 分支（维度不可驱动）")
                else:
                    notes.append(
                        f"约束未激活：{st.get('unbacked_policy_count', 0)} 条策略的 "
                        f"apply() 落在 `default:` 分支、不做任何事"
                        f"（{st.get('note') or '策略体是空骨架'}）")
        except (OSError, ValueError):
            notes.append("约束状态文件读不出来 —— 判不了")
    else:
        notes.append("没有约束状态文件（这一轮没生成约束模型）")

    # 测试点：**每一个覆盖缺口都能归因到一条 tp_id** 才算"量到了该量的东西"。
    # 没有 TP IR 时是 `None`（这一轮没建模），不是 `False`（建模了但有断点）。
    tp_matrix = result.get("tp_matrix") or {}
    tp_traced = None
    if tp_matrix:
        tp_traced = not bool(tp_matrix.get("unmapped"))
        if tp_matrix.get("unmapped"):
            notes.append(
                f"{len(tp_matrix['unmapped'])} 条测试点的覆盖仓在报告里找不到 —— "
                f"模型与生成的覆盖率模型漂了（见 coverage/tp_matrix.json 的 unmapped）")
        missed = tp_matrix.get("missed") or []
        if missed:
            notes.append(
                f"{len(missed)} 条测试点的仓未命中"
                f"（激励型 {tp_matrix.get('drivable', 0)} 条中命中 "
                f"{tp_matrix.get('drivable_hit', 0)} 条，"
                f"{tp_matrix.get('drivable_pct', 0)}%）—— 逐条见 tp_matrix.json")

    # ── 种子多样性：**做过才给布尔**，没做仍是 `None` ──
    #
    # `None` 与 `False` 的区别很重要：
    #   None  = 没分析（没有 ≥2 颗种子 / vcover 不可用）
    #   False = 分析了，但各种子的命中集合完全一致（随机化没生效）
    #   True  = 分析了，且确实存在种子敏感的 bin
    sd = result.get("seed_diversity") or {}
    seed_verified = None
    if sd.get("analyzed"):
        seed_verified = (sd.get("verdict") == "DIVERSE")
        notes.append(
            f"种子多样性：{sd.get('verdict')}（{len(sd.get('seeds') or [])} 颗种子，"
            f"稳定 {sd.get('stable_bins', 0)} bin / 种子敏感 "
            f"{sd.get('variable_bins', 0)} bin / 并集 {sd.get('union_bins', 0)}）")
    elif sd:
        notes.append(f"种子多样性：{sd.get('verdict')} —— {sd.get('reason', '')}")

    return {
        "ucdb_nonzero_bins": ucdb_nonzero,
        "cg_dut_hit_gt_zero": (cg_dut_actual > 0) if cg_dut_actual is not None else None,
        "constraint_policy_applied": cpa,
        "testpoints_traced": tp_traced,
        "seed_diversity_verified": seed_verified,
        "seed_diversity": sd or None,
        "notes": notes,
    }


def _artifact_manifest(sim_result: dict) -> dict:
    """覆盖率库 / 波形 → `{ucdb: {...}, waveform: {...}}`（路径 + 哈希 + 大小）。

    **哈希不是装饰**：覆盖率数字的意义完全取决于"它出自哪一份库"。一份能被悄悄
    换掉的 ucdb 会让签核回溯失去意义 —— 而 `sim/coverage/` 是回归会反复写的目录，
    换掉它太容易了。记哈希是让"这一轮的数字 = 这一个文件"可核对。

    文件不在就给空串（不伪造）—— 比如这次仿真没落波形，那是事实，不是错误。
    """
    from src.runtime_plane.infrastructure.infrastructure import sha256_file

    def _entry(path_str: str, kind: str) -> dict:
        p = Path(path_str) if path_str else None
        if not p or not p.exists():
            return {"path": "", "sha256": "", "size": 0, "kind": kind}
        return {"path": str(p), "sha256": sha256_file(p),
                "size": p.stat().st_size, "kind": kind}

    return {
        "ucdb": _entry(sim_result.get("ucdb_path", ""), "coverage_db"),
        # `.vcd` 是覆盖率后端自己 dump 的那份（`simulate_with_coverage` 的
        # `vcd file ...`），**不是** `sim_modes` 那条 `-qwavedb` 的波形 ——
        # 是两条互不相干的 vsim 命令（见 `sim_modes.py` 与那里的说明）。
        "waveform": _entry(sim_result.get("vcd_path", ""), "waveform"),
    }


if __name__ == "__main__":
    od = sys.argv[1] if len(sys.argv) > 1 else "output/demo_apb_uart"
    top = sys.argv[2] if len(sys.argv) > 2 else ""
    result = run(od, top)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
