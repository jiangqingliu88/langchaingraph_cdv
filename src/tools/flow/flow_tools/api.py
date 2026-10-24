"""流程与证据工具层 —— 读一次运行目录，吐结构化的视图数据。

五个函数，都**只读一次运行目录**：

    run_task(run_dir)                 一次运行作为一个「验证任务」的总览
                                      （目标 / 进度 / 收敛预测 / 卡在哪）
    run_signoff(run_dir)              门禁 + 六层证据链 + 总判定
    run_agent_outputs(run_dir, role)  某个 agent 这次做了什么、产出了哪些文件
    run_decision_trace(run_dir)       每轮的决策与驾驭裁决（从运行日志里挖）
    run_manifest_info(run_dir)        运行清单 + 文件变更链

**数据从哪来**（全部是已经落盘的，不需要重跑、不碰运行中的进程）：
  · `report.json`              —— audit agent 写的四道门禁与 verdict
  · `docs/evidence_chain.json` —— n_finalize 写的六层领域证据链与 signoff_ready
  · `docs/run_events.jsonl`    —— 运行日志（阶段事件自带 `agent`，按 agent 过滤不必
                                  去 import 领域代码）
  · `docs/manifest.json` / `docs/file_change_chain.json`
  · 产物目录（`rtl/` `model/` `agents/` `sim/` `coverage/` …）

**两份来源都要看**：门禁回答"该跑的都跑了吗"，证据链回答"证据链每一层都闭合了吗"。
一份缺失不算错 —— 运行可能还没跑到那一步；如实标 `available: false`，
**不拿空数据冒充通过**（全仓库的"失败响亮"纪律）。

失败**响亮**：目录不在 / 不是一个目录 / 文件不是目录 → `{"error": ...}`，不抛异常。
"""
from __future__ import annotations

import json
import platform
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# 运行目录布局 —— **契约只有一处**（`regression_run` 那一层在哪、分几级、
# 读的时候怎么认）。这里只许调它的函数，不许再拼一次字符串。
from src.layers.l1_infrastructure.layout import regression_root as _layout_regression_root
from src.layers.l1_infrastructure.layout import latest_root as _layout_latest_root
from src.layers.l1_infrastructure.layout import stage_roots as _layout_stage_roots
from src.layers.l1_infrastructure.layout import test_dirs as _layout_test_dirs

#: 门禁 id → 中文名。顺序即**显示顺序**（audit agent 的 gates 是 dict，无序）。
#: 这些是 audit 的布尔门禁；`rtl_files` / `model_placeholder_reason` 是附注不是门禁，
#: 单独取出来当说明用。
GATE_TITLES = (
    ("rtl_present", "① RTL 存在"),
    ("rtl_real", "② RTL 非占位"),
    ("regression_passed", "③ 回归全过"),
    ("coverage_collected", "④ 覆盖率已收集"),
    ("model_real", "⑤ 参考模型非占位"),
)

#: 证据链层 id → 中文名（与 config/evidence_schema.yaml 的层对应）。
LAYER_TITLES = {
    "requirement_layer": "需求层",
    "design_layer": "设计层",
    "verification_layer": "验证层",
    "execution_layer": "执行层",
    "functional_coverage_layer": "功能覆盖层",
    "signoff_layer": "签核层",
}

#: 检查项 id → 中文名。认不出的原样显示（界面里出现一个生词，好过出现空白）。
CHECK_TITLES = {
    "req_spec_completeness": "规格完整",
    "req_test_mapping": "需求→测试映射",
    "rtl_signal_mapping": "RTL 信号/接口映射",
    "register_mapping": "寄存器映射",
    "case_coverage_P0": "P0 用例覆盖",
    "case_coverage_P1": "P1 用例覆盖",
    "case_coverage_P2": "P2 用例覆盖",
    "case_coverage_P3": "P3 用例覆盖",
}


def run_signoff(run_dir: str = "") -> Dict[str, Any]:
    """一次运行目录 → 签核判定模型。

    返回：
        {"run_dir", "verdict", "signoff_status", "pass_rate", "coverage",
         "gates": [{id,title,passed,detail}], "chain": {...}, "summary"}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    report = _read_json(root / "report.json")
    chain_raw = _read_json(root / "docs" / "evidence_chain.json")

    gates = _build_gates(report)
    chain = _build_chain(chain_raw)

    return {
        "run_dir": str(root),
        "verdict": str((report or {}).get("verdict", "") or ""),
        "signoff_status": str((report or {}).get("signoff_status", "") or ""),
        "pass_rate": str((report or {}).get("pass_rate", "") or ""),
        "coverage": _num((report or {}).get("coverage")),
        "gates": gates,
        "chain": chain,
        # 测试点维度的签核口径（audit 写进 report.json）：
        # `{total, drivable, drivable_hit, drivable_pct, observe_only,
        #   observed, missed, unmapped}`。空 = 这一轮没有 TP IR，不是全过。
        "testpoints": (report or {}).get("testpoints") or {},
        # 软缺口（约束部分生效 / 测试点未命中等）—— 签核时要写清保留了什么。
        "caveats": list((report or {}).get("caveats") or []),
        "summary": _summary(report, gates, chain),
    }


# ════════════════════════════════════════════════════════════════
# report.json → 门禁
# ════════════════════════════════════════════════════════════════

def _build_gates(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(report, dict):
        return {"available": False, "rows": [],
                "note": "没有 report.json —— 这次运行还没跑到 audit（签核审查）"}
    raw = report.get("gates") or {}
    if not isinstance(raw, dict):
        raw = {}
    rows: List[Dict[str, Any]] = []
    for gate_id, title in GATE_TITLES:
        if gate_id not in raw:
            continue                      # 老报告可能没有某道门 —— 不凭空补
        rows.append({"id": gate_id, "title": title,
                     "passed": bool(raw.get(gate_id)),
                     "detail": _gate_detail(gate_id, report, raw)})
    return {"available": True, "rows": rows, "note": ""}


def _gate_detail(gate_id: str, report: Dict[str, Any], raw: Dict[str, Any]) -> str:
    """给每道门配一句"为什么"——门禁不给理由的话，人只会看到一片红。"""
    if gate_id == "rtl_present":
        files = raw.get("rtl_files") or []
        return f"{len(files)} 个 .sv" + (f"：{'、'.join(files[:4])}" if files else "")
    if gate_id == "rtl_real":
        return "RTL 是真实互连" if raw.get("rtl_real") else "顶层是占位骨架（LLM 连线失败回退）"
    if gate_id == "regression_passed":
        return f"通过 {report.get('pass_rate', '?')}"
    if gate_id == "coverage_collected":
        cov = _num(report.get("coverage"))
        return f"覆盖率 {cov:g}%" if cov is not None else "覆盖率缺失"
    if gate_id == "model_real":
        if raw.get("model_real"):
            return "参考模型为真实实现"
        return str(raw.get("model_placeholder_reason", "") or "参考模型是模板占位")
    return ""


# ════════════════════════════════════════════════════════════════
# evidence_chain.json → 六层证据链
# ════════════════════════════════════════════════════════════════

def _build_chain(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(raw, dict) or not isinstance(raw.get("layers"), dict):
        return {"available": False, "layers": [], "signoff_ready": False,
                "checks_passed": 0, "checks_total": 0,
                "note": "没有 docs/evidence_chain.json —— 这次运行还没跑到 finalize"}
    layers: List[Dict[str, Any]] = []
    for layer_id, body in (raw.get("layers") or {}).items():
        if not isinstance(body, dict):
            continue
        layers.append({
            "id": layer_id,
            "title": LAYER_TITLES.get(layer_id, layer_id),
            "description": str(body.get("description", "") or ""),
            "passed": int(body.get("passed", 0) or 0),
            "total": int(body.get("total", 0) or 0),
            "checks": _checks_of(body),
        })
    return {
        "available": True,
        "layers": layers,
        "signoff_ready": bool(raw.get("signoff_ready")),
        "overall_status": str(raw.get("overall_status", "") or ""),
        "checks_passed": int(raw.get("checks_passed", 0) or 0),
        "checks_total": int(raw.get("checks_total", 0) or 0),
        "note": "",
    }


def _checks_of(layer: Dict[str, Any]) -> List[Dict[str, Any]]:
    checks = layer.get("checks") or {}
    if not isinstance(checks, dict):
        return []
    return [{"id": name, "title": CHECK_TITLES.get(name, name),
             "passed": bool(value)} for name, value in checks.items()]


# ════════════════════════════════════════════════════════════════
# 汇总
# ════════════════════════════════════════════════════════════════

def _summary(report: Optional[Dict[str, Any]], gates: Dict[str, Any],
             chain: Dict[str, Any]) -> str:
    """一句话总判定 —— 界面顶部那行大字。

    口径：**门禁与证据链都通过才算真正可签核**。任一缺失都如实说出来，
    不因为"文件还没生成"就报绿。
    """
    if not gates.get("available") and not chain.get("available"):
        return "这次运行还没有签核信息（既没有 report.json 也没有证据链）。"

    bits: List[str] = []
    if gates.get("available"):
        rows = gates["rows"]
        ok = sum(1 for r in rows if r["passed"])
        verdict = str((report or {}).get("verdict", "") or "")
        bits.append(f"门禁 {ok}/{len(rows)} 通过" + (f"（{verdict}）" if verdict else ""))
    else:
        bits.append("门禁未知（未跑到 audit）")

    if chain.get("available"):
        state = "证据链闭合" if chain["signoff_ready"] else "证据链未闭合"
        bits.append(f"{state} {chain['checks_passed']}/{chain['checks_total']}")
    else:
        bits.append("证据链未知（未跑到 finalize）")

    ready = (gates.get("available") and chain.get("available")
             and all(r["passed"] for r in gates["rows"]) and chain["signoff_ready"])
    return ("可以签核：" if ready else "暂不可签核：") + "；".join(bits) + "。"


# ════════════════════════════════════════════════════════════════
# 某个 agent 这次做了什么
# ════════════════════════════════════════════════════════════════

#: agent 角色 → 它写产物的目录（相对 run 根）。**这是界面上「产出」一栏的来源**。
#: debug / audit 刻意是空的 —— debug 就地改文件、audit 只写根下的 report.json，
#: 都没有独立产物目录；如实说"没有"比硬塞一个空目录好。
ROLE_ARTIFACT_DIRS: Dict[str, tuple] = {
    "design":   (("rtl", "RTL"),),
    "model":    (("model", "参考模型"),),
    "verify":   (("agents", "UVM 组件"), ("env", "环境"),
                 ("assertions", "断言"), ("inputs", "输入 YAML")),
    "ops":      (("sim", "仿真 / 回归"),),
    "coverage": (("coverage", "覆盖率"),),
    "debug":    (),
    "audit":    (),
}

ROLE_TITLES = {
    "design": "设计构建", "model": "参考模型", "verify": "验证构建",
    "ops": "编译与回归", "coverage": "覆盖率", "debug": "调试技术",
    "audit": "签核审查",
}

#: 单个产物目录最多列这么多文件 —— 界面是给人扫读的，不是 rsync 的进度条
MAX_FILES_PER_DIR = 40


def run_coverage(run_dir: str = "") -> Dict[str, Any]:
    """一次运行的**总覆盖率** —— 数字 + 合并库 + 报告在哪。

    「逐条用例的覆盖率」和「整个环境的覆盖率」是两件事：前者在
    `run_regression_status` 的每行里，后者在这里。人对不上账的时候两边都要看 ——
    "每条都挺高，总的就是上不去"和"某一条特别低"是完全不同的结论。

    数字口径与别处一致（`sim/coverage/coverage_result.json` 的 `coverage`，
    分项按 `_COV_FIELDS`）。文件两样，都只报"在不在、多大、什么时候写的"，
    **不重跑也不解析**（解析/出报告是 `coverage_tools` 的事）。

    返回 `{run_dir, coverage_dir, overall, functional, fields, db, report, notes}`。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    cov_dir = root / "sim" / "coverage"
    raw = _read_json(cov_dir / "coverage_result.json") or {}
    cov = raw.get("coverage") or {}

    fields = [{"key": key, "label": label, "pct": _num(cov.get(key))}
              for key, label in _COV_FIELDS]

    try:
        from src.tools.checking.coverage_tools.cov_api import find_run_coverage

        files = find_run_coverage(root)
    except Exception:                                  # noqa: BLE001 扫盘失败不该拖垮这页
        files = {"dir": str(cov_dir), "db": {}, "report": {}}

    notes: List[str] = []
    if not raw:
        notes.append("没有 `sim/coverage/coverage_result.json` —— 这次运行还没跑到"
                     "覆盖率收集（或收集中断），下面的数字是空的，不是 0。")
    if not (files.get("db") or {}).get("exists"):
        notes.append("没有合并覆盖率库（`sim/coverage/merged.ucdb`）。")
    elif not (files.get("report") or {}).get("exists"):
        notes.append("覆盖率阶段没留下 HTML 报告 —— 打开时会现生成一份（要起 vcover）。")

    return {"run_dir": str(root), "coverage_dir": str(cov_dir),
            "overall": _num(cov.get("overall_pct")),
            "functional": _num(cov.get("functional_pct")),
            "fields": fields, "db": files.get("db") or {},
            "report": files.get("report") or {}, "notes": notes}


def run_agent_outputs(run_dir: str = "", role: str = "") -> Dict[str, Any]:
    """某个 agent 在这次运行里**做了什么**（阶段）+ **产出了什么**（文件）。

    阶段来自运行日志 —— 日志事件自带 `agent` 字段（写日志时就解析好了），
    所以这里不需要 import 任何领域代码就能按 agent 过滤。

    返回：
        {"role", "role_title", "run_dir", "stages": [...], "artifacts": [...],
         "notes": [...], "counts": {"stages", "files"}}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    role = str(role or "").strip()
    if not role:
        return {"error": "没有给 agent 角色（清单里该模块的 params.role）"}

    events = _read_journal(root)
    stages = _stages_of(events, role)
    artifacts, notes = _artifacts_of(root, role)

    if not stages and not artifacts:
        notes.append(f"这次运行里没有 {role} 的痕迹 —— 可能还没跑到，或者被跳过了。")

    return {
        "role": role,
        "role_title": ROLE_TITLES.get(role, role),
        "run_dir": str(root),
        "stages": stages,
        "artifacts": artifacts,
        "notes": notes,
        "counts": {"stages": len(stages),
                   "files": sum(a["file_count"] for a in artifacts)},
    }


#: UVM 消息行的判别式。
#
#  实测形状（QuestaSim）：`# UVM_INFO <file>(392) @ 0: reporter [UVM/RELNOTES] ...`
#  —— 消息行**带 `@ <时间>`**，而结尾的汇总行是 `UVM_ERROR :    4`（没有 `@`）。
#  用 `@` 做判别符能把「真消息」与「计数汇总」分开，不会把汇总数字当成消息条数。
_UVM_MSG_RE = re.compile(r"(?m)^[^\n]*?\bUVM_(INFO|WARNING|ERROR|FATAL)\b[^\n]*@")


def _is_assert_error(line: str) -> bool:
    """这一行是不是断言失败。

    按「同时提到 assert 和 fail/error」判，而不是写死某个仿真器的措辞 ——
    ExecMan 报表里这列叫 `Vcs_Assertion_Error`，但措辞随仿真器变（Questa 上是
    `** Error: ... Assertion ... failed`）。规则就写在这里，便于按实际日志调整。
    """
    low = line.lower()
    return "assert" in low and ("fail" in low or "error" in low)


def _pick_sim_log(test_dir: Path) -> Optional[Path]:
    """挑这个用例**真正**的仿真日志。

    框架自己写一份 `sim.log`（脚本里 `> sim.log 2>&1`），但配置里的 `run_cmd` 往往
    还带 `-l <自己的日志>` —— 那才是仿真器的原始输出，框架那份可能是 0 字节。
    优先级：`sim_vsim.log` → `sim.log` → 其它 `*.log`（取最大的，排除记账文件）。
    """
    for name in ("sim_vsim.log", "sim.log", "vsim.log"):
        p = test_dir / name
        if p.is_file() and p.stat().st_size > 0:
            return p
    skip = {"sim_time.log", "tr_db.log", "wave.log"}
    candidates = [p for p in test_dir.glob("*.log")
                  if p.name not in skip and p.stat().st_size > 0]
    return max(candidates, key=lambda p: p.stat().st_size) if candidates else None


def _count_log(log_path: Optional[Path]) -> Dict[str, Any]:
    """数一个用例日志里的 UVM 消息与断言错误。"""
    out = {"uvm_info": 0, "uvm_warning": 0, "uvm_error": 0,
           "assert_error": 0, "log": ""}
    if log_path is None:
        return out
    out["log"] = str(log_path)
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for sev in _UVM_MSG_RE.findall(text):
        key = f"uvm_{sev.lower()}"
        if key in out:
            out[key] += 1
    out["assert_error"] = sum(1 for line in text.splitlines()
                              if _is_assert_error(line))
    return out


def _read_sim_time(test_dir: Path) -> Optional[float]:
    """用例耗时。框架在 `sim_time.log` 里写 `SIM_TIME=<秒>`（整数秒）。"""
    try:
        for line in (test_dir / "sim_time.log").read_text(
                encoding="utf-8", errors="replace").splitlines():
            if line.startswith("SIM_TIME="):
                return float(line.split("=", 1)[1])
    except (OSError, ValueError):
        pass
    return None


#: 「日志里出现了非零的 UVM 错误计数」的判别式 —— 与配置里那条判定规则同源：
#: 生产 `regression.yaml` 的 run_cmd 结尾就是
#: `! grep -qE "UVM_ERROR : *[1-9]|UVM_FATAL : *[1-9]|FATAL ERROR|Errors: *[1-9]"`
#: （见 `tool_find_spec_yaml._sim_run_cmd`）。删减这里的分支就是让"推断"与
#: "框架判的"两套判据分家 —— 那条 grep 是**唯一**的失败判据，读者要跟它一致。
_UVM_TALLY_RE = re.compile(r"UVM_(?:ERROR|FATAL)\s*:\s*([1-9]\d*)")

#: 「仿真根本没起来」的判别式 —— UVM 那两条计数盖不住这一类。
#: 实测：8 条用例挂在 `vsim-3772 Failed to load DPI auto compile shared library`，
#: vsim 直接 `FATAL ERROR while loading design` 退出，日志里一条 `UVM_ERROR :`
#: 都没有，于是被记成 PASS（波形、覆盖率自然也没有）。末尾 `# Errors: 2, Warnings: 0`
#: 是 vsim 自己的结算，按它判才盖得住。
_SIM_FATAL_RE = re.compile(r"FATAL ERROR|Errors:\s*[1-9]")


def _derive_status(counts: Dict[str, Any], log_path: Optional[Path]) -> str:
    """**从日志推断**结论 —— 只在没有权威记录时才用。

    这不是「猜」：它用的正是配置里那条判定规则（日志里有没有非零的 UVM 错误
    计数 / 断言失败 / 仿真致命错）。但它是**推断**，与框架判完落盘的 `status.env`
    不是一回事，所以调用方必须把它标成 `derived_from_log`，不能冒充权威结论。

    返回 "pass" / "fail" / ""（推不出来就别推）。
    """
    if log_path is None:
        return ""
    if counts.get("uvm_error") or counts.get("assert_error"):
        return "fail"
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if _UVM_TALLY_RE.search(text) or _SIM_FATAL_RE.search(text):
        return "fail"
    return "pass"


def _read_status_env(test_dir: Path) -> str:
    """框架判完落的 `status.env`（`EMAN_BASE_STATUS=pass|fail|unknown`）。

    这是**最贴近真实判定**的一手来源：调度器判完之后写的，不依赖报告文件。
    """
    try:
        for line in (test_dir / "status.env").read_text(
                encoding="utf-8", errors="replace").splitlines():
            if line.startswith("EMAN_BASE_STATUS="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return ""


#: 波形文件的后缀 —— 本环境是 Questa，波形业务产的是 `*.db`（`vsim -qwavedb`
#: 的 qwave.db，Visualizer 原生格式）；`*.wlf` 是旧产物 / `vsim -wlf`；
#: fsdb/vcd 是别家/别路（VCS+Verdi、UVM 的 vcd 导出）留下的，一样认，
#: 别只认自家那一种。这里只扫**用例目录**（覆盖率库 `questa.db` 在 `cov/`
#: 子目录，也不在此列）；回归趋势库已统一到 `database/ic_verification.db`，
#: 不再出现在运行根，所以不会与波形 `.db` 混淆。
_WAVE_EXTS = (".db", ".wlf", ".fsdb", ".vcd")


def _find_wave(test_dir: Path, reported: str = "") -> tuple:
    """这条用例的**波形文件** → `(路径, 来源)`；没有就 `("", "none")`。

    两个来源，分成两级（与状态那三级同一个口径：记录 > 现场）：

      · `report_json`  —— 回归框架自己判完写的 `wave_path`（`<test_dir>/waves/
        <test>.db`）。**不改成败**：通过用例也会写（`Scheduler._parse_task_result`
        已不再只对失败用例解析 wave.log）。当线索用，仍不能当唯一来源。
      · `waves_dir` / `sim_dir` —— **扫磁盘上真实存在的波形文件**（`waves/` 下的，
        以及用例目录里的 `vsim.wlf`）。这是"现场"，波形在不在、有多大，一眼可查。

    都不在就老实地给空 —— 不返回一个"看起来能打开"的假路径。
    """
    if reported:
        cand = Path(str(reported))
        if cand.is_file():
            return str(cand), "report_json"

    def _pick(paths) -> str:
        """候选里挑**最新写的**那个；没有就给空。

        一条用例可能有多个波形（重跑留下的）。按 mtime 挑才对得上"最后跑出来的那一次"
        —— 按名字排会变成按扩展名字母序，那是在挑格式，不是在挑时间。
        """
        files = [p for p in paths if p.is_file() and p.stat().st_size > 0]
        return str(max(files, key=lambda p: p.stat().st_mtime)) if files else ""

    if not test_dir.is_dir():
        return "", "none"

    # ① 配置指定的落点：`<test_dir>/waves/`（框架建目录 + 波形业务往这儿写）
    waves_dir = test_dir / "waves"
    if waves_dir.is_dir():
        hit = _pick(waves_dir.iterdir())
        if hit:
            return hit, "waves_dir"
    # ② 仿真器默认落点：用例目录下的 vsim.wlf / 别路留下的 vcd、fsdb
    hit = _pick(p for p in test_dir.iterdir()
                if p.is_file() and p.suffix.lower() in _WAVE_EXTS)
    if hit:
        return hit, "sim_dir"
    return "", "none"


def _newest_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _dir_has_artifact(test_dir: Path) -> bool:
    """这个用例目录里有没有波形或覆盖率库。"""
    return bool(_find_wave(test_dir)[0] or _find_coverage(test_dir)[0])


def _dir_has_evidence(test_dir: Path) -> bool:
    """这一级的这个目录**跑过没有** —— 判据是框架判完落的 `status.env` 或仿真日志。

    空壳（`ShellGenerator` 铺了目录但这一级没跑它）两样都没有。
    """
    if (test_dir / "status.env").is_file():
        return True
    try:
        return any(p.is_file() and p.stat().st_size > 0
                   for p in test_dir.glob("*.log"))
    except OSError:
        return False


def _case_dirs(run_root: Path) -> Dict[str, List[Path]]:
    """run 根 → **{用例名: 它在每一级的目录}**（旧 → 新），分级布局也不例外。

    `layout.test_dirs()` 会把每一级的 `build_*/test_*` 全扫出来 —— 那是"证据"该有
    的样子（见它的 docstring）。但分级回归**给每个用例在每一级都建了目录**：实测
    一轮里 265 个目录只对应 53 个用例，真跑过那条用例的那一级才有 `status.env` /
    日志 / 波形，其余是空壳。

    **为什么不能用 `latest_root`（最后一级）枚举用例**：那是读 `report.json` 该用的
    层，不是"用例全集"该用的层。分级回归把用例分给各级去跑，最后一级往往只剩
    "随机/通用"那批（跑完什么都不落），于是整页看着像坏了 —— 而证据明明在 p0/p1/p2。

    **为什么要留全每一级、而不是挑一个**：一条用例的状态和它的产物未必在同一级 ——
    状态取"跑过它的那一级"，波形/覆盖率取"落了产物的那一级"，两者可能不是同一个。
    收成一个目录就得二选一，实测立刻错：`test_apb_slave_throughput` 在 p2 跑过
    （有 status.env）但那一级没落波形，而 p3 有个空壳更新 —— 挑"最新"就挑到空壳，
    页面上那条成了 `unknown`、波形也没有。
    """
    by_name: Dict[str, List[Path]] = {}
    for d in _layout_test_dirs(run_root):
        by_name.setdefault(d.name[len("test_"):], []).append(d)
    for dirs in by_name.values():
        dirs.sort(key=_newest_mtime)                 # 旧 → 新：末尾是最后跑的那一级
    return by_name


def _primary_dir(dirs: List[Path]) -> Path:
    """这条用例的**状态 / 日志**取哪一级的目录。

    优先"真跑过"的那一级（有 `status.env` / 日志），同样跑过的取**最新**的那次 ——
    重跑会覆盖 `status.env`，最新的那个才是现在的结论。一个都没跑过时才退到最新的
    空壳（那时 `unknown` 就是实话：声明了但哪一级都没跑）。
    """
    ran = [d for d in dirs if _dir_has_evidence(d)]
    return (ran or dirs)[-1]


def _first_artifact(dirs: List[Path], finder) -> tuple:
    """这条用例的产物：**从最新一级往回找**，第一个有的就算它。"""
    for d in reversed(dirs):
        hit = finder(d)
        if hit[0]:
            return hit
    return "", "none"


def _artifact_facts(path: str) -> tuple:
    """`(大小 KB, 修改时间)` —— 给波形/覆盖率那几列用；没有就给 `(None, "")`。

    "什么算产物文件"的判断在 `cov_api.file_facts` 里（一处实现），这里只转发，
    省得两处各写一遍 stat 与时间格式。
    """
    try:
        from src.tools.checking.coverage_tools.cov_api import file_facts

        facts = file_facts(path)
        return facts["kb"], facts["time"]
    except Exception:                                  # noqa: BLE001 统计是旁路
        return None, ""


def _find_coverage(test_dir: Path) -> tuple:
    """这条用例的**覆盖率库** → `(路径, 来源)`。

    "什么算覆盖率库"是覆盖率这条路自己的领域知识（`vcover` 认 `questa.db`、
    不认旁边的 `.data`），所以判定在 `coverage_tools.cov_api` 里，这里只转发 ——
    抄一份到这边就是第二份真相。**读不到就给空**，让它自己解释。
    """
    try:
        from src.tools.checking.coverage_tools.cov_api import find_coverage_db

        return find_coverage_db(test_dir)
    except Exception:                                  # noqa: BLE001 扫描失败不该拖垮这页
        return "", "none"


def run_regression_status(run_dir: str = "") -> Dict[str, Any]:
    """这次运行的**回归用例状态** —— 一个用例一行。

    回答「这次回归哪条挂了、挂的是什么错」，形状对齐 ExecMan 的回归报表
    （用例 / 状态 / 耗时 / UVM 计数 / 日志 / 备注）。

    数据全部来自**已落盘**的产物，不重跑、不碰运行中的进程：

      · `<run>/regression_run/build_*/test_*/`  框架的用例目录 —— **永远存在**
      · 其中 `status.env`                       框架判完的结论（一手来源）
      · 用例的仿真日志                          数 UVM_INFO / UVM_ERROR / 断言错误
      · `<run>/regression_run/report.json`      有就用（耗时是权威值）

    **为什么以目录为准、report.json 只作补充**：`report.json` 要跑到
    `_generate_report` 才有，中途中断的回归没有它 —— 而恰恰那时最需要看用例状态。
    所以缺 report.json 不算错，如实记进 `sources`。

    返回：
        {"run_dir", "regression_dir", "sources", "stats", "rows", "notes"}

    失败**响亮**：目录不在 / 不像回归产物 → `{"error": ...}`，不抛。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    # 回归产物在**哪一层** —— 判据只有一处（`layout.latest_root`）。
    #
    # 它认三种入参，**这是实测补上的**：一开始这里只当"运行根"处理，而调用方
    # （含 workbench 夹具）实际会传**回归目录本身**；收口那版直接扫到 0 行、
    # 17 个用例变红。容忍进 `layout` 之后，两个读端共用同一套判据。
    reg_root = _layout_latest_root(root)
    if reg_root is None:
        return {"error": f"这个运行目录里没有回归产物"
                         f"（找过 {_layout_regression_root(root)} 和 {root}）"}

    report = _read_json(reg_root / "report.json") or {}
    # `report.json` 是**每一级各一份**（框架只写本级）。只读最后一级的那份，
    # 前面几级跑过的用例在"状态回退到报告值"这条路上就查无此人。按级合并，
    # 后面的级覆盖前面的（同一条用例重跑，最新那次才是现在的结论）。
    report_tasks: Dict[str, Dict[str, Any]] = {}
    for stage_dir in _layout_stage_roots(root):
        for t in (_read_json(stage_dir / "report.json") or {}).get("tasks") or []:
            if isinstance(t, dict) and t.get("name"):
                report_tasks[str(t["name"])] = t
    comments = _read_json(reg_root / "test_comments.json") or {}

    rows: List[Dict[str, Any]] = []
    host = platform.node()
    # 用例枚举**看全每一级**（`layout.test_dirs` 的口径），按用例名收口 ——
    # 只扫 `reg_root`（最后一级）会漏掉前面几级跑出来的全部证据。见 `_case_dirs`。
    cases = _case_dirs(root)
    test_dirs = [d for dirs in cases.values() for d in dirs]
    for name, dirs in sorted(cases.items(),
                             key=lambda kv: (kv[1][-1].parent.name, kv[0])):
        # 状态/日志取"真跑过的那一级"，波形/覆盖率各自从最新一级往回找 ——
        # 两者未必在同一级（见 `_case_dirs` 的 docstring）。
        test_dir = _primary_dir(dirs)
        reported = report_tasks.get(name) or {}
        # 状态来源三级：框架判完的 status.env（一手）> report.json > 从日志推断。
        # 前两者是**记录**，第三者是**推断** —— 分开标注，别让推断冒充权威结论。
        status = _read_status_env(test_dir)
        status_source = "status_env"
        if not status:
            status = str(reported.get("status") or "")
            status_source = "report_json"
        log_path = _pick_sim_log(test_dir)
        counts = _count_log(log_path)
        if not status:
            status = _derive_status(counts, log_path)
            status_source = "derived_from_log"
        if not status:
            status, status_source = "unknown", "none"

        sim_time = _read_sim_time(test_dir)
        if sim_time is None:
            sim_time = reported.get("sim_time")
        uvm_err = counts["uvm_error"]
        assert_err = counts["assert_error"]
        wave_path, wave_source = _first_artifact(
            dirs, lambda d: _find_wave(d, reported.get("wave_path") or ""))
        cov_path, cov_source = _first_artifact(dirs, _find_coverage)
        wave_kb, wave_time = _artifact_facts(wave_path)
        cov_kb, cov_time = _artifact_facts(cov_path)

        # 状态细化：失败再按日志里的错因分类 —— ExecMan 的 Status 列就是这个语义
        # （不只是 pass/fail）。分类只依据**从日志里数出来的**事实，不猜。
        if status == "fail":
            detail = ("assertion_error" if assert_err
                      else ("uvm_error" if uvm_err else "fail"))
        else:
            detail = status

        rows.append({
            "name": name,
            "build": test_dir.parent.name[len("build_"):],
            "status": status,
            "status_source": status_source,
            "detail": detail,
            "sim_time": "" if sim_time is None else round(float(sim_time), 2),
            "uvm_error": uvm_err or "-",
            "uvm_warning": counts["uvm_warning"],
            "uvm_info": counts["uvm_info"],
            "assert_error": assert_err or "-",
            "host": host,
            "log": counts["log"],
            "work_dir": str(test_dir),
            "comment": str(comments.get(name, "") or ""),
            # 波形：这轮跑出波形业务（`wave`）才会有。`wave_source` 说明它哪来的
            # ——`report_json`（框架记的）/ `waves_dir`（配置指定落点）/ `sim_dir`
            # （仿真器默认落点）—— 三者含义不同，界面上不能揉成一个"有波形"。
            "wave": wave_path,
            "wave_source": wave_source,
            "wave_kb": wave_kb,
            "wave_time": wave_time,
            # 覆盖率库同样：这轮开了 `cov` 业务才有。`cov_source` 同上面那套口径。
            "cov": cov_path,
            "cov_source": cov_source,
            "cov_kb": cov_kb,
            "cov_time": cov_time,
        })

    stats = {"total": len(rows), "pass": 0, "fail": 0, "unknown": 0}
    for r in rows:
        stats[r["status"]] = stats.get(r["status"], 0) + 1

    sources = {
        "regression_dir": str(reg_root),
        "report_json": bool(report),
        "status_env": any(_read_status_env(p) for p in test_dirs),
    }
    notes: List[str] = []
    if not rows:
        notes.append("回归目录里一个用例都没有 —— 可能还没跑到，或者编译阶段就失败了。")
    if rows and not sources["report_json"]:
        notes.append("没有 report.json（回归可能中途中断）—— 状态取自各用例的 "
                     "status.env 与日志，耗时可能缺。")
    if rows and not sources["status_env"]:
        notes.append("没有 status.env（这轮回归早于该产物的引入）—— 状态回退到报告值。")
    derived = sum(1 for r in rows if r["status_source"] == "derived_from_log")
    if rows and not any(r.get("wave") for r in rows):
        # 一个波形都没有时把原因说出来：不是"这页坏了"，是这轮没开波形业务。
        # 不说的话，空列会被读成"波形丢了"。
        notes.append("这轮没有任何波形文件 —— 说明仿真业务里没开 `wave`"
                     "（工作台工具栏「仿真业务」下拉，或 CLI `--sim-mode wave`）。")
    if rows and not any(r.get("cov") for r in rows):
        notes.append("这轮没有任何覆盖率库 —— 说明仿真业务里没开 `cov`。")
    if derived:
        # 「推断」必须说出来。用的时候是同一套判定规则，但它不是框架判完落盘的记录。
        sources["derived_rows"] = derived
        notes.append(f"其中 {derived} 条的结论是**从日志推断**的（按配置同源的规则："
                     f"日志里有无非零 UVM 错误/断言失败），不是框架判完落盘的记录。")

    return {"run_dir": str(root), "regression_dir": str(reg_root),
            "sources": sources, "stats": stats, "rows": rows, "notes": notes}


def _stages_of(events: List[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    """该 agent 的阶段事件 → 行。用 finished/failed（它们带状态与耗时）。"""
    rows: List[Dict[str, Any]] = []
    for event in events:
        if str(event.get("agent", "")) != role:
            continue
        if event.get("kind") not in ("stage.finished", "stage.failed"):
            continue
        rows.append({
            "stage": str(event.get("stage", "")),
            "title": str(event.get("title") or event.get("stage") or ""),
            "round": int(event.get("round", 0) or 0),
            "status": str(event.get("status", "")),
            "duration_s": round(float(event.get("duration_s", 0.0) or 0.0), 2),
            "summary": _payload_line(event.get("payload") or {}),
        })
    return rows


def _payload_line(payload: Dict[str, Any]) -> str:
    """阶段事件 payload → 一行摘要。`delta` 是节点写回的全量状态，别整个铺出来。"""
    if not isinstance(payload, dict):
        return ""
    bits = [f"{key}={payload[key]}" for key in
            ("status", "passed", "failed", "count", "score", "reason",
             "coverage", "verdict", "message") if key in payload]
    if bits:
        return " ".join(bits)
    delta = payload.get("delta")
    if isinstance(delta, dict):
        return "、".join(sorted(str(k) for k in delta)[:6])
    error = payload.get("error")
    return str(error) if error else ""


def _artifacts_of(root: Path, role: str) -> tuple:
    """该 agent 的产物目录 → 每个目录一行（含文件数与文件名，超量截断并记账）。"""
    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    for dirname, title in ROLE_ARTIFACT_DIRS.get(role, ()):
        target = root / dirname
        if not target.is_dir():
            continue
        files = sorted(p for p in target.rglob("*") if p.is_file())
        listed = files[:MAX_FILES_PER_DIR]
        rows.append({
            "dir": dirname,
            "title": title,
            "file_count": len(files),
            "files": [{"name": str(p.relative_to(target)),
                       "size_kb": _size_kb(p)} for p in listed],
        })
        if len(files) > len(listed):
            # 截断要记账 —— 静默截断会让人以为"产出就这么多"
            notes.append(f"{dirname}/ 有 {len(files)} 个文件，界面只列前 "
                         f"{MAX_FILES_PER_DIR} 个。")
    return rows, notes


# ════════════════════════════════════════════════════════════════
# 决策轨迹
# ════════════════════════════════════════════════════════════════

def run_decision_trace(run_dir: str = "") -> Dict[str, Any]:
    """每轮的决策与驾驭裁决。

    来源是 `decide` / `governor` 两个阶段的**结束事件**：节点写回的状态增量整个
    挂在 `payload.delta` 里（`RunJournal._summarise` 把它保留了），决策动作就在
    `delta.pending_action`、驾驭结论在 `delta.governance_outcome`。

    为什么不去读 `decision` 事件：`RunJournal.decision()` **定义了但没有任何调用点**
    —— 日志里根本没有那种事件。拿它当数据源会画出一张永远空的表。

    返回：`{"run_dir", "available", "rounds": [...], "note"}`
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    events = _read_journal(root)
    if not events:
        return {"run_dir": str(root), "available": False, "rounds": [],
                "note": "没有运行日志（docs/run_events.jsonl）—— 这次运行还没开始写，或目录不对"}

    by_round: Dict[int, Dict[str, Any]] = {}
    for event in events:
        stage = str(event.get("stage", ""))
        if event.get("kind") not in ("stage.finished", "stage.failed"):
            continue
        if stage not in ("decide", "governor"):
            continue
        round_no = int(event.get("round", 0) or 0)
        row = by_round.setdefault(round_no, {
            "round": round_no, "action": "", "reason": "", "priority": "",
            "params": "", "governance": ""})
        delta = (event.get("payload") or {}).get("delta") or {}
        if stage == "decide":
            action = delta.get("pending_action") or {}
            if isinstance(action, dict):
                row["action"] = str(action.get("action_type", "") or "")
                row["reason"] = str(action.get("reason", "") or "")
                row["priority"] = str(action.get("priority", "") or "")
                params = action.get("params")
                row["params"] = ("、".join(f"{k}={v}" for k, v in sorted(params.items()))
                                 if isinstance(params, dict) and params else "")
        elif stage == "governor":
            row["governance"] = str(delta.get("governance_outcome", "") or "")

    rounds = [by_round[k] for k in sorted(by_round)]
    note = "" if rounds else ("日志里没有 decide/governor 阶段事件 —— 这次运行可能停在"
                              "更早的阶段，或者只是还没转第一轮。")
    return {"run_dir": str(root), "available": bool(rounds), "rounds": rounds, "note": note}


# ════════════════════════════════════════════════════════════════
# 运行清单与文件变更链
# ════════════════════════════════════════════════════════════════

#: manifest.json 里值得在界面上列出来的标量键（其余是明细，不铺）
_MANIFEST_KEYS = (
    ("architecture", "架构"), ("run_id", "运行 id"), ("iterations", "轮次"),
    ("final_coverage", "最终覆盖率"), ("effective_coverage", "有效覆盖率"),
    ("target", "目标"), ("generator", "生成器"),
)


def run_manifest_info(run_dir: str = "") -> Dict[str, Any]:
    """运行清单（`docs/manifest.json`）+ 文件变更链（`docs/file_change_chain.json`）。

    **只展示、不校验**：哈希链的完整性校验要调 L2 的 `FileAuditTrail.verify_persisted`
    —— 工具层不该反向依赖层代码。校验属于「治理动作」，留给 P3（见
    docs/design/agent_gui_business_architecture.md §6）。

    返回：`{"run_dir", "manifest": {...}, "change_chain": {...}, "notes"}`
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    notes: List[str] = []
    raw = _read_json(root / "docs" / "manifest.json")
    manifest: Dict[str, Any] = {"available": False, "rows": []}
    if raw is None:
        notes.append("没有 docs/manifest.json —— 这次运行还没跑完（manifest 是收尾时写的）")
    else:
        rows = [{"key": title, "value": _short(raw.get(key))}
                for key, title in _MANIFEST_KEYS if raw.get(key) not in (None, "")]
        hashes = raw.get("rtl_hashes")
        if isinstance(hashes, dict):
            rows.append({"key": "RTL 文件哈希", "value": f"{len(hashes)} 个"})
        manifest = {"available": True, "rows": rows,
                    "manifest_hash": str(raw.get("manifest_hash", "") or ""),
                    "evidence_hash": str(raw.get("evidence_hash", "") or "")}

    chain_raw = _read_json(root / "docs" / "file_change_chain.json")
    chain: Dict[str, Any] = {"available": False, "entries": 0, "rows": []}
    if chain_raw is None:
        notes.append("没有 docs/file_change_chain.json —— 没有记录到文件变更")
    else:
        changes = chain_raw.get("changes") if isinstance(chain_raw, dict) else None
        if not isinstance(changes, list):
            changes = []
        chain = {
            "available": bool(changes),
            "entries": len(changes),
            "rows": [{"seq": str(c.get("seq", "")),
                      "agent": str(c.get("agent", "")),
                      "file": str(c.get("file", c.get("file_path", ""))),
                      "reason": str(c.get("reason", ""))} for c in changes[:MAX_FILES_PER_DIR]],
        }
        if len(changes) > MAX_FILES_PER_DIR:
            notes.append(f"变更链有 {len(changes)} 条，界面只列前 {MAX_FILES_PER_DIR} 条。")

    return {"run_dir": str(root), "manifest": manifest,
            "change_chain": chain, "notes": notes}


# ════════════════════════════════════════════════════════════════
# 一次运行 = 一个「验证任务」的总览
# ════════════════════════════════════════════════════════════════

#: 运行日志的终态事件 → 任务的对外状态
_TERMINAL_STATES = {
    "run.finished": "completed",
    "run.failed": "failed",
    "run.cancelled": "cancelled",
    "run.interrupted": "waiting",       # 挂着等人审批
}


def run_task(run_dir: str = "") -> Dict[str, Any]:
    """一次运行**作为一个验证任务**的总览：目标 / 进度 / 收敛判断 / 卡在哪。

    面向的问题只有一个 —— **这个任务现在什么情况、还差多少、该不该继续。**

    数据源两条，按"谁更权威"取：
      · 跑完了 → `docs/manifest.json`（含 `planning.convergence_forecast`，规划器
        按最近提升速率算的"还要几轮"）
      · 还在跑 → `docs/run_events.jsonl`（逐轮的 coverage.updated 与阶段事件）

    返回：
        {"run_dir", "available", "state", "target",
         "coverage": {history, final, effective, target, gap, converged},
         "forecast": {rounds_to_target, converging, note},
         "phases": {total, passed, failed, skipped, rows},
         "current": {stage, title, status}, "blockers": [...], "summary"}
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    events = _read_journal(root)
    manifest = _read_json(root / "docs" / "manifest.json")
    if not events and manifest is None:
        return {"run_dir": str(root), "available": False,
                "state": "unknown", "target": None,
                "coverage": _empty_coverage(), "forecast": {},
                "phases": {"total": 0, "passed": 0, "failed": 0, "skipped": 0, "rows": []},
                "current": {}, "blockers": [],
                "summary": "这次运行还没有任何记录（既没有运行日志也没有运行清单）。"}

    state = _task_state(events, manifest)
    coverage = _task_coverage(events, manifest)
    forecast = _forecast_of(manifest)
    phases = _phases_of(manifest, events)
    current = _current_stage(events)
    blockers = _blockers_of(events, phases)

    return {
        "run_dir": str(root),
        "available": True,
        "state": state,
        "target": coverage.get("target"),
        "coverage": coverage,
        "forecast": forecast,
        "phases": phases,
        "current": current,
        "blockers": blockers,
        "summary": _task_summary(state, coverage, forecast, phases, blockers),
    }


def _empty_coverage() -> Dict[str, Any]:
    return {"history": [], "final": None, "effective": None, "target": None,
            "gap": None, "converged": None}


def _task_state(events: List[Dict[str, Any]], manifest: Optional[Dict[str, Any]]) -> str:
    """任务的生命周期状态。

    `completed_with_errors` 是沿用 DB 里 `PipelineRun.state` 的既有取值 ——
    "跑完了"和"跑成功了"是两件事：跑完但没达标/有卡点，得能一眼看出来。
    """
    for event in reversed(events):
        mapped = _TERMINAL_STATES.get(str(event.get("kind", "")))
        if mapped:
            return mapped
    if isinstance(manifest, dict) and manifest:
        # 有 manifest = 收尾过；再按"达标了没"细分
        return "completed" if manifest.get("converged") else "completed_with_errors"
    return "running"


def _task_coverage(events: List[Dict[str, Any]],
                   manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """逐轮覆盖率曲线 + 最终值 + 与目标差多少。"""
    history: List[List[Any]] = []
    for event in events:
        if event.get("kind") != "coverage.updated":
            continue
        payload = event.get("payload") or {}
        total = _num(payload.get("total"))
        if total is None:
            continue
        # 与 evidence / run_common 同一口径：事件里的 round 本身就是 1-based
        round_no = max(1, int(event.get("round", 0) or 0))
        history.append([round_no, total])

    out = _empty_coverage()
    out["history"] = history

    if isinstance(manifest, dict) and manifest:
        target = _num(manifest.get("target"))
        final = _num(manifest.get("final_coverage"))
        effective = _num(manifest.get("effective_coverage"))
        converged = manifest.get("converged")
        if effective is None:
            effective = final
    else:
        target, final, effective, converged = None, None, None, None
        # 跑完了的 run 会在 run.finished 里带最终值
        for event in reversed(events):
            if event.get("kind") == "run.finished":
                payload = event.get("payload") or {}
                target = _num(payload.get("target"))
                final = _num(payload.get("final_coverage"))
                effective = _num(payload.get("effective_coverage")) or final
                converged = payload.get("converged")
                break
        if final is None and history:
            final = effective = history[-1][1]

    out["target"] = target
    out["final"] = final
    out["effective"] = effective
    out["converged"] = bool(converged) if converged is not None else None
    # 差多少 —— 用「有效覆盖率」算，那是决策层真正看的数
    base = effective if effective is not None else final
    out["gap"] = (round(target - base, 1)
                  if target is not None and base is not None else None)
    return out


def _forecast_of(manifest: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """规划器的收敛预测。`inf` 在 JSON 里不是合法值，这里换成 None + 说明。"""
    if not isinstance(manifest, dict):
        return {}
    planning = manifest.get("planning")
    if not isinstance(planning, dict):
        return {}
    raw = planning.get("convergence_forecast")
    if not isinstance(raw, dict):
        return {}
    rounds = raw.get("rounds_to_target")
    note = str(raw.get("note", "") or "")
    if isinstance(rounds, float) and rounds == float("inf"):
        return {"rounds_to_target": None, "converging": False,
                "note": note or "覆盖率停滞，需换策略"}
    return {"rounds_to_target": rounds, "converging": raw.get("converging"),
            "note": note}


def _phases_of(manifest: Optional[Dict[str, Any]],
               events: List[Dict[str, Any]] = ()) -> Dict[str, Any]:
    """阶段统计。

    跑完了看 `manifest.phases`；**还在跑时没有 manifest** —— 退回到运行日志里的
    阶段结束事件，否则"运行中"那一行会是空的（看不到跑到第几步了）。
    """
    rows: List[Dict[str, Any]] = []
    counts = {"total": 0, "passed": 0, "failed": 0, "skipped": 0}
    source = (manifest or {}).get("phases") if isinstance(manifest, dict) else None
    if source:
        for phase in source:
            if not isinstance(phase, dict):
                continue
            status = str(phase.get("status", "") or "")
            rows.append({"name": str(phase.get("name", "")), "status": status,
                         "score": phase.get("score", "")})
    else:
        for event in events:
            kind = str(event.get("kind", ""))
            if kind not in ("stage.finished", "stage.failed"):
                continue
            status = "failed" if kind == "stage.failed" else "passed"
            rows.append({"name": str(event.get("title") or event.get("stage") or ""),
                         "status": status, "score": ""})

    for row in rows:
        counts["total"] += 1
        if row["status"] in counts:
            counts[row["status"]] += 1
    return {**counts, "rows": rows}


def _current_stage(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """最后一条阶段事件的落点 —— 还在跑时用来看「现在在哪一步」。"""
    for event in reversed(events):
        if not str(event.get("kind", "")).startswith("stage."):
            continue
        return {"stage": str(event.get("stage", "")),
                "title": str(event.get("title") or event.get("stage") or ""),
                "status": str(event.get("status", ""))}
    return {}


def _blockers_of(events: List[Dict[str, Any]], phases: Dict[str, Any]) -> List[Dict[str, Any]]:
    """卡在哪：失败/出错的阶段（阶段事件 + manifest.phases 两处都收）。"""
    blockers: List[Dict[str, Any]] = []
    for event in events:
        if event.get("kind") != "stage.failed":
            continue
        blockers.append({"title": str(event.get("title") or event.get("stage") or ""),
                         "round": int(event.get("round", 0) or 0),
                         "error": str((event.get("payload") or {}).get("error", ""))})
    if not blockers:
        for row in phases.get("rows") or []:
            if row["status"] in ("failed", "error"):
                blockers.append({"title": row["name"], "round": 0, "error": ""})
    return blockers


def _task_summary(state: str, coverage: Dict[str, Any], forecast: Dict[str, Any],
                  phases: Dict[str, Any], blockers: List[Dict[str, Any]]) -> str:
    """一句话总览 —— 界面顶部那行。**先说要紧的（卡住 / 差距），再说过程。**"""
    bits: List[str] = []
    state_cn = {"completed": "已完成", "completed_with_errors": "完成但有错",
                "running": "运行中", "failed": "失败", "cancelled": "已取消",
                "waiting": "等待审批", "unknown": "未知"}.get(state, state)
    bits.append(state_cn)

    target, final = coverage.get("target"), coverage.get("final")
    if final is not None:
        cov = f"覆盖率 {final:g}%"
        if target is not None:
            cov += f" / 目标 {target:g}%"
        bits.append(cov)
        if coverage.get("converged") is True:
            bits.append("已达标")
        elif coverage.get("gap") is not None and coverage["gap"] > 0:
            bits.append(f"还差 {coverage['gap']:g} 个点")

    if phases["total"]:
        bits.append(f"阶段 {phases['passed']}/{phases['total']} 过")
    if blockers:
        bits.append(f"{len(blockers)} 处卡点：" + "、".join(b["title"] for b in blockers[:3]))
    if forecast.get("rounds_to_target") is not None:
        bits.append(f"预测还需 {forecast['rounds_to_target']} 轮")
    elif forecast.get("converging") is False:
        bits.append("覆盖率停滞")
    return "　".join(bits) + "。"


# ════════════════════════════════════════════════════════════════
# 小工具
# ════════════════════════════════════════════════════════════════

def _resolve_run_dir(run_dir: str):
    """(Path, error) —— 给四个入口共用同一套「目录得像个运行目录」的检查。

    出来的一定是**绝对路径**：下面报出去的 `db` / `report` / `wave` / `cov` 都是
    在这个 root 上拼出来的，root 相对，报出来的产物路径就全是相对的 —— 而界面拿
    这些路径去 `QUrl.fromLocalFile()` 打开时，相对路径**什么都不做也不报错**。
    在这里落一次绝对化，四个入口一起修好，好过在每个调用点各拼一次。
    """
    if not isinstance(run_dir, str) or not run_dir.strip():
        return None, {"error": "没有给运行目录（先在「运行历史」里选一次运行）"}
    root = Path(run_dir)
    if not root.exists():
        return None, {"error": f"运行目录不存在：{root}"}
    if not root.is_dir():
        return None, {"error": f"运行目录不是目录（是个文件）：{root}"}
    return root.resolve(), None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """读 JSON；不在 / 坏了一律返回 None（由调用方按"缺失"处理，不抛）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_journal(root: Path) -> List[Dict[str, Any]]:
    """读 `docs/run_events.jsonl`。**逐行解析、坏行跳过** —— 日志是追加写的，
    进程被杀时最后一行可能只写了一半，那一行不该让整份日志读不出来。

    只读磁盘，不调 run_service：工具层不该依赖 L2 的读接口。
    """
    path = root / "docs" / "run_events.jsonl"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue                      # 半行 —— 跳过，不因它丢掉整份日志
        if isinstance(item, dict):
            events.append(item)
    return events


def _size_kb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1024, 1)
    except OSError:
        return 0.0


def _short(value: Any, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ═══════════════════════════════════════════════════════════════
# 中间产物目录 —— 一次运行里"人该看、也该能改"的那些文件
# ═══════════════════════════════════════════════════════════════
#
# 为什么单列这一项：产物在此之前只以**原始文件树**的形式存在（`flow.evidence`），
# 看得见文件名，但看不出哪份有问题、哪份是谁写的、改了会怎样。而卡住运行的
# 恰恰是这些中间 YAML —— 实测一次：`bench.yaml` 的 schema 不符让整次运行挂在
# verify，从日志一路挖到生成器才定位到。有个审查台的话那是 30 秒的事。
#
# **刻意不含 `docs/*.json` 与 `report.json`**：那几份是**证据**（机器写下的结论
# 与哈希链），不是"中间产物"。改了它们等于篡改结论，所以这里不给编辑入口。

#: UVM 中间产物用的 schema。`spec.json` / `regression.yaml` **没有** schema ——
#: 如实标成 `schema: null`，不假装校验过。
UVM_SCHEMA = "uvm_config"


def _spec_of_run(root: Path) -> Dict[str, Any]:
    """运行目录里的 `spec.json` —— `find_case_model` 认 `specs/<模块>/` 时要用它。"""
    return _read_json(root / "spec.json") or {}


def _rel_to(path, root: Path, fallback: str = "") -> Path:
    """展示用：能相对化就相对化，不能就原样；**`None` 退回 `fallback`**。

    `path` 会是 `None`（模型没找到），而调用方那边是 `root / rel` —— 直接把
    `None` 传下去就是 `TypeError`，而那个异常会**把前面攒的 notes 一起带走**
    （实测：页面上一句解释都没有，只剩一张空表）。
    """
    if path is None:
        return Path(fallback) if fallback else Path(".")
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def run_fcov(run_dir: str = "") -> Dict[str, Any]:
    """一次运行 → **功能覆盖率**三张表（覆盖点 / 测试点 / 资产）。

    「case 建模到底变成了什么、跑了没有、测到了没有」这三个问题各一张表 ——
    揉成一张的话，三件事会互相稀释（覆盖点的**声明**、用例的**名单**、
    文件的**存在性**，粒度根本不同）。

      · `coverpoints` —— 模型声明了哪些覆盖点、每个点有哪些 bin（**声明**），
        以及实测命中的百分比（来自覆盖率阶段的 `coverage_cvg.txt`，没有就留空）。
        **声明与命中分列**：一个是"该测什么"（模型），一个是"打到了没有"（仿真），
        把两者混成一个数字正是这一页要避免的。
      · `testpoints`  —— 模型摊平出来的用例（维度 / 字段 / 取值 / 优先级）。
      · `assets`      —— 这条链上的文件（模型 / 声明 / env_cov bin / 实测文本）。

    只读已落盘的东西，不重跑生成器、不重跑 vcover。
    """
    if not run_dir:
        return {"error": "没有指定运行目录（先在「运行历史」里选一次运行）"}
    root = Path(run_dir)
    if not root.is_dir():
        return {"error": f"run_dir not found: {run_dir}"}

    # **走统一判据**：`casemodel_path()` 只是 front 的草稿落点，人写的模型
    # （`specs/<模块>/casemodel.yaml`）优先级更高。直接读草稿的后果实测过 ——
    # NPU 那份 12 维度的手写模型被绕过，页面显示"1 覆盖点 / 4 测试点"。
    from src.layers.l1_infrastructure.layout import find_case_model

    cm_file = find_case_model(_spec_of_run(root), root)
    notes: List[str] = []
    cm_text = ""
    if cm_file is not None and cm_file.is_file():
        try:
            cm_text = cm_file.read_text(encoding="utf-8")
        except OSError:
            cm_text = ""

    # 模块名取模型的 `object`（`apb_uart`），**不是运行目录名** ——
    # 目录名会进用例名（`test_apb_uart_D_ADDR_0` vs
    # `test_output_e2e_fix2_jiang_..._D_ADDR_0`），那是两只手都数不过来的噪音。
    module_name = root.name
    if cm_text:
        import yaml as _yaml

        try:
            module_name = str((_yaml.safe_load(cm_text) or {}).get("object")
                              or root.name).strip() or root.name
        except Exception:                           # noqa: BLE001 解析失败就退回目录名
            pass

    # ── ① 覆盖点：模型的声明 + 实测的命中 ──
    points: Dict[str, Any] = {}
    if cm_text:
        try:
            from src.tools.generation.casemodel_tools.api import run_covergroups

            points = run_covergroups(cm_text, module_name)
            if points.get("error"):
                notes.append(f"case 模型构建失败：{points['error']}")
                points = {}
        except Exception as exc:                    # noqa: BLE001 旁路，别让页面挂
            notes.append(f"读 case 模型失败：{exc}")
    else:
        tried = "、".join(str(x) for x in
                         [Path("specs") / "<模块>" / "casemodel.yaml",
                          Path("config") / "casemodel" / "<模块>.yaml"]
                         + ([cm_file] if cm_file else []))
        notes.append(f"没有 case 模型（找过 {tried}）—— 覆盖点无从列起"
                     f"（front 阶段没产出它？）")

    measured, measured_path = {}, ""
    try:
        from src.tools.checking.coverage_tools.cov_api import functional_coverage_details

        cgs, measured_path = functional_coverage_details(root)
        for cg in cgs:
            for cp in cg.get("coverpoints") or []:
                measured.setdefault(cp["name"], cp["actual"])
            for cx in cg.get("crosses") or []:
                measured.setdefault(cx["name"], cx["actual"])
    except Exception as exc:                        # noqa: BLE001
        notes.append(f"读实测覆盖失败：{exc}")
    if points and not measured:
        # **两种"没有命中数据"要说清是哪一种**：文件根本没落盘（没跑到覆盖率
        # 收集）vs 文件在、但是旧格式（那一版只给了汇总行，没有逐 covergroup 的段）。
        # 说成同一句的话，人会对着一个存在的文件去找"为什么说文件不在"。
        if measured_path:
            notes.append(f"实测文本在（{measured_path}）但里面没有逐 covergroup 的段"
                         f"—— 那是**旧格式**（那一版 `vcover` 没带 `-details`）；"
                         f"重跑一轮覆盖率就有命中列了")
        else:
            notes.append("还没有实测的覆盖率文本"
                         "（`sim/coverage/reports/coverage_cvg.txt`）—— 这轮还没跑到"
                         "覆盖率收集，命中的那一列会是空的")

    coverpoint_rows: List[Dict[str, Any]] = []
    for cp in points.get("coverpoints") or []:
        # 实测里 coverpoint 的名字带 `cp_` 前缀（env_cov 生成时就那么叫），声明里
        # 是信号名。**两边都要能对上**：对不上就说明声明和被测的不是同一批，
        # 那正是这一页要看的，不能悄悄显示成"没命中"。
        actual = measured.get(f"cp_{cp['signal']}", measured.get(cp["signal"]))
        coverpoint_rows.append({
            # 编号是**文档里的那个**（`CP_NPU_QUEUE_001`），`signal` 是生成器给
            # 编译器用的名字（`queue_level`）。两个都摆出来，人对账时不用换算。
            "cover_id": cp.get("cover_id", ""),
            "requirement": cp.get("requirement", ""),
            "dimension": cp.get("dimension", ""),
            "signal": cp.get("signal", ""),
            "type": cp.get("type", ""),
            "bin_count": cp.get("bin_count", 0),
            "bins": "、".join(b["name"] for b in cp.get("bins") or []),
            "actual": "" if actual is None else actual,
            "measured": actual is not None,
        })
    for cx in points.get("crosses") or []:
        actual = measured.get(cx.get("name", ""))
        coverpoint_rows.append({
            "cover_id": "", "requirement": "",
            "dimension": "×".join(cx.get("dimensions") or []),
            "signal": cx.get("name", ""),
            "type": f"cross（{cx.get('level', '')}）",
            "bin_count": len(cx.get("bins") or []),
            "bins": "、".join(cx.get("signals") or []),
            "actual": "" if actual is None else actual,
            "measured": actual is not None,
        })

    # ── ② 测试点：模型摊平出来的用例（与 run_uvm_tests / 用例库同一份分母）──
    testpoint_rows: List[Dict[str, Any]] = []
    if cm_text:
        try:
            from src.tools.generation.casemodel_tools.registry_bridge import case_rows

            rows = case_rows(cm_text, module_name)
            for c in rows.get("cases") or []:
                cons = (c.get("constraints") or [{}])[0]
                testpoint_rows.append({
                    "name": c.get("name", ""),
                    "dimension": cons.get("dimension", ""),
                    "field": cons.get("field", ""),
                    "value": cons.get("value", ""),
                    "priority": c.get("priority", ""),
                    "coverage_bin": c.get("coverage_bin", ""),
                })
            notes.extend(rows.get("notes") or [])
        except Exception as exc:                    # noqa: BLE001
            notes.append(f"摊平测试点失败：{exc}")

    # ── ③ 批次 / 种子管理 + 需求追溯：从**计划**读（与 case 模型同批落盘的那份）──
    #
    # 覆盖点表回答"该测什么"，这两张表回答"**打算怎么测够**"与"**谁验了哪条需求**"。
    # 不读计划的话，页面上"声明了 12 个覆盖点"和"回归里只跑 8 条"永远对不上账
    # —— 而它们本来就摆在同一份文件里。
    batches: List[Dict[str, Any]] = []
    trace: List[Dict[str, Any]] = []
    plan_path = root / "coverage" / "coverage_plan.yaml"
    if plan_path.is_file():
        try:
            import yaml as _yaml

            plan = _yaml.safe_load(plan_path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, _yaml.YAMLError):
            plan = {}
        for b in (plan.get("batches") or []):
            if not isinstance(b, dict):
                continue
            seeds = b.get("seeds") or {}
            batches.append({
                "theme": b.get("theme", ""),
                "name": b.get("name", ""),
                "priority": b.get("priority", ""),
                "test": b.get("test", ""),
                "method": b.get("method", ""),
                "dimensions": ",".join(b.get("dimensions") or [])
                              if isinstance(b.get("dimensions"), list)
                              else str(b.get("dimensions") or ""),
                # 种子管理的三列拆开展示 —— "跑够没有"要一眼看出基线/探索各多少
                "base": seeds.get("base", ""),
                "count": seeds.get("count", ""),
                "explore": seeds.get("explore", ""),
                "total_runs": b.get("total_runs", ""),
            })
        for r in (plan.get("traceability") or []):
            if not isinstance(r, dict):
                continue
            trace.append({
                "requirement": r.get("requirement", ""),
                "coverpoints": "、".join(r.get("coverpoints") or []),
                "crosses": "、".join(r.get("crosses") or []),
                "batches": "、".join(r.get("batches") or []),
                "covered": bool(r.get("coverpoints") or r.get("crosses")),
            })
    # ── ④ 资产：这条链上的文件 ──
    assets: List[Dict[str, Any]] = []
    for label, rel in (
            ("case 模型（声明来源）",
             _rel_to(cm_file, root, "inputs/casemodel.yaml")),
            ("功能覆盖点声明", Path("coverage/coverage_points.json")),
            ("env_cov bin 注入", Path("inputs/yaml/uvm/env_cov_bins.yaml")),
            ("实测覆盖率文本", Path("sim/coverage/reports/coverage_cvg.txt"))):
        assets.append(_artifact(root, rel, "功能覆盖", None) | {"label": label})

    return {
        "run_id": root.name,
        "run_dir": str(root),
        "coverpoints": coverpoint_rows,
        "testpoints": testpoint_rows,
        "batches": batches,
        "traceability": trace,
        "assets": assets,
        "measured_path": measured_path,
        "counts": {
            "coverpoints": len(coverpoint_rows),
            "bins": points.get("bin_count", 0),
            "crosses": len(points.get("crosses") or []),
            "testpoints": len(testpoint_rows),
            "batches": len(batches),
            "total_runs": sum(int(b.get("total_runs") or 0) for b in batches),
            "requirements": len(trace),
            "measured": sum(1 for r in coverpoint_rows if r["measured"]),
        },
        "source": points.get("source", "") or ("casemodel" if points else ""),
        "notes": list(dict.fromkeys(notes)),
        "summary": (f"{len(coverpoint_rows)} 个覆盖点 / {len(testpoint_rows)} 条测试点"
                    + (f"　·　实测 {sum(1 for r in coverpoint_rows if r['measured'])} 个"
                       if measured else "　·　（还没有实测数据）")),
    }


def run_artifacts(run_dir: str = "") -> Dict[str, Any]:
    """一次运行的中间产物目录 + 每份的 schema 体检结果。

    只读落盘的文件，不碰运行中的进程。文件不在就 `exists: false` 照列 ——
    "这一份还没生成"本身就是有用的信息（说明那次运行没跑到产出它的阶段）。
    """
    if not run_dir:
        return {"error": "没有指定运行目录"}
    root = Path(run_dir)
    if not root.is_dir():
        return {"error": f"run_dir not found: {run_dir}"}

    items: List[Dict[str, Any]] = []

    # 设计阶段的产出、verify 的输入。"AI 把规格理解成了什么"全在这一份里，
    # 所以它排在最前面 —— 人最该先看的是这个，而不是 UVM 配置。
    items.append(_artifact(root, Path("spec.json"), "设计", None))

    # UVM 配置：数 per-agent 命名（`dut_in.yaml` / `apb_master.yaml`），所以是 glob
    uvm_dir = root / "inputs" / "yaml" / "uvm"
    for path in sorted(uvm_dir.glob("*.yaml")):
        items.append(_artifact(root, path.relative_to(root), "验证·UVM", UVM_SCHEMA))

    items.append(_artifact(root, Path("inputs/yaml/regression.yaml"), "回归", None))

    # ── 功能覆盖：case 模型的**声明** + 它派生的语义 cross ──
    #
    # `coverage_points.json` 是「功能覆盖率方法学」的落点：模型声明了哪些覆盖点、
    # 每个点有哪些 bin、哪些维度要交叉。它**不是**命中数据（命中在 ucdb 里，见
    # 覆盖率页），所以单列一组、和 uvmd 配置那组一样是"输入侧"的产物。
    items.append(_artifact(root, Path("inputs/casemodel.yaml"), "功能覆盖", None))
    items.append(_artifact(root, Path("coverage/coverage_points.json"), "功能覆盖", None))
    items.append(_artifact(root, Path("inputs/yaml/uvm/env_cov_bins.yaml"),
                           "功能覆盖", None))

    present = [i for i in items if i["exists"]]
    with_schema = [i for i in present if i["schema"]]
    bad = [i for i in with_schema if i["errors"]]
    return {
        "run_id": root.name,
        "run_dir": str(root),
        "artifacts": items,
        "present": len(present),
        "checked": len(with_schema),
        "with_errors": len(bad),
        # 一行话给界面顶部用 —— 数在这里算，免得界面自己再数一遍数出第二份真相
        "summary": (f"{len(present)} 份产物"
                    + (f"，{len(bad)} 份 schema 不符" if bad else "，schema 都过")),
    }


def _artifact(root: Path, rel: Path, group: str, schema: Optional[str]) -> Dict[str, Any]:
    """一份产物的体检：在不在 / 多大 / 什么哈希 / schema 过不过。"""
    path = root / rel
    exists = path.is_file()
    out: Dict[str, Any] = {
        "path": str(rel).replace("\\", "/"),
        "name": rel.name,
        "group": group,
        "schema": schema,
        "exists": exists,
        "size_kb": _size_kb(path) if exists else 0.0,
        "sha256": "",
        "issues": 0,
        "errors": 0,
        "warnings": 0,
        "messages": [],
    }
    if not exists:
        return out

    from src.layers.l1_infrastructure.infrastructure import sha256_file
    out["sha256"] = sha256_file(path)          # 与证据链同一份哈希实现

    if schema:
        issues = _schema_issues(path)
        out["issues"] = len(issues)
        out["errors"] = sum(1 for i in issues if i.get("severity") == "error")
        out["warnings"] = sum(1 for i in issues if i.get("severity") == "warning")
        # 只带前几条给界面定位用 —— 诊断面板是给人扫读的，不是日志转储
        out["messages"] = [
            {"severity": i.get("severity"), "line": i.get("line"),
             "text": _short(i.get("message", ""), 120)}
            for i in (issues if out["errors"] else issues[:2])[:5]
        ]
    return out


def _schema_issues(path: Path) -> List[Dict[str, Any]]:
    """按 UVM schema 校验一份 YAML，转成可 JSON 化的 dict 列表。

    校验器加载一次缓存着 —— 一张审查台上每次点开文件都重新 parse 一遍 schema
    是纯浪费，而 schema 是仓库里的静态文件。
    """
    try:
        from src.tools.generation.uvm_tools.tool_uvm.schema_check import get_checker

        issues = get_checker().check([path])
    except Exception as exc:                   # 依赖缺失 / schema 坏 —— 别把界面拖挂
        return [{"severity": "error", "line": None,
                 "message": f"schema 校验没能跑起来：{exc}"}]
    out = []
    for issue in issues:
        out.append({
            "severity": getattr(issue, "severity", "error"),
            "line": _line_of(getattr(issue, "target", ""), path),
            "message": str(issue),
        })
    return out


def _line_of(target: str, path: Path) -> Optional[int]:
    """从 issue 的 target（形如 `bench.yaml::bench.agents`）找它在文件里的行号。

    找不到就算了 —— 点不过去总比跳到一个错的行号好（那会让人以为问题在别处）。
    """
    if not target:
        return None
    field = target.split("::")[-1].split(".")[-1]
    if not field:
        return None
    try:
        for index, line in enumerate(path.read_text(encoding="utf-8",
                                                   errors="replace").splitlines(), 1):
            if line.strip().startswith(f"{field}:"):
                return index
    except OSError:
        return None
    return None


# ═══════════════════════════════════════════════════════════════
# 运行对比
# ═══════════════════════════════════════════════════════════════

#: 覆盖率里要逐项对比的分项（`sim/coverage/coverage_result.json` 的 coverage）
_COV_FIELDS = (("overall_pct", "总覆盖率"), ("functional_pct", "功能覆盖率"),
               ("statement_pct", "语句"), ("branch_pct", "分支"),
               ("toggle_pct", "翻转"), ("condition_pct", "条件"))


def _case_status_map(root: Path) -> Dict[str, str]:
    """这次运行的用例 → 状态（口径同 `run_regression_status`：目录为准）。"""
    payload = run_regression_status(str(root))
    rows = payload.get("rows") or []
    return {str(r.get("name", "")): str(r.get("status", "")) for r in rows
            if r.get("name")}


def _cov_of(root: Path) -> Dict[str, Any]:
    """一次运行的覆盖率：总/有效取 report.json，分项取 coverage_result.json。"""
    # `report.json` 在**运行根下**（audit agent 写的，见 `run_signoff`）——
    # 别去 docs/ 找，那里没有（第一次就写错了，实测读到 None）
    report = _read_json(root / "report.json") or _read_json(root / "docs" / "report.json") or {}
    raw = _read_json(root / "sim" / "coverage" / "coverage_result.json") or {}
    cov = raw.get("coverage") if isinstance(raw.get("coverage"), dict) else {}
    out = {"overall_pct": report.get("coverage"),
           "functional_pct": (cov or {}).get("functional_pct")}
    for key, _label in _COV_FIELDS:
        if key not in out:
            out[key] = (cov or {}).get(key)
    return out


def compare_runs(baseline: str = "", current: str = "") -> Dict[str, Any]:
    """两次运行的**逐项对比** —— 回答「这次比上次差在哪、是谁改坏的」。

    为什么这是「可审计」最该有的一个视图：单次报告只告诉你**这次**的结论，
    而"修好一个、改坏三个"这种事只有**两次并排**才看得见。数据全在磁盘上
    （每次运行都落了盘），所以这里不重跑、不碰进程，只做对齐。

    对齐口径：
      · 用例级：`<run>/regression_run/` 的用例目录（同 `run_regression_status`）
      · 覆盖率：`docs/report.json` 的 coverage + `sim/coverage/coverage_result.json` 分项
      · 判定：`docs/report.json` 的 verdict / signoff_status

    **"变坏"优先**：`newly_failing`（基线通过、现在没通过）是这张表存在的理由，
    所以它排在最前面，且在 `summary` 里单独给一个数。

    返回：
        {"baseline": {run_id, dir, verdict, signoff_status, coverage},
         "current":  {...},
         "coverage": {"<字段>": {"label", "baseline", "current", "delta"}},
         "cases": {"newly_failing", "fixed", "added", "removed", "common"},
         "summary": {…计数与一句话结论…}, "notes": [...]}
    """
    if not baseline or not current:
        return {"error": "要选两次运行才能对比（基线 / 对比）"}
    if str(baseline) == str(current):
        return {"error": "两次选的是同一个运行"}

    result: Dict[str, Any] = {"cases": {}, "coverage": {}, "notes": []}
    sides = {}
    for side, value in (("baseline", baseline), ("current", current)):
        root, error = _resolve_run_dir(str(value))
        if error:
            return {**error, "side": side}
        report = _read_json(root / "report.json") or _read_json(root / "docs" / "report.json") or {}
        sides[side] = {
            "run_id": root.name,
            "dir": str(root),
            "verdict": report.get("verdict", ""),
            "signoff_status": report.get("signoff_status", ""),
            "coverage": _cov_of(root),
            "cases": _case_status_map(root),
        }
    result.update(sides)

    # ── 覆盖率逐项 delta ──
    base_cov, cur_cov = sides["baseline"]["coverage"], sides["current"]["coverage"]
    for key, label in _COV_FIELDS:
        b, c = base_cov.get(key), cur_cov.get(key)
        if b is None and c is None:
            continue
        try:
            delta = round(float(c) - float(b), 1)
        except (TypeError, ValueError):
            delta = None
        result["coverage"][key] = {"label": label, "baseline": b, "current": c,
                                   "delta": delta}

    # ── 用例级变化 ──
    b_cases, c_cases = sides["baseline"]["cases"], sides["current"]["cases"]
    # `unknown` **不是"挂了"** —— 它是"框架没留下判定"（回归中断、没跑到那条）。
    # 所以"修复"这一档要求基线**确实 fail**；拿 `!= pass` 算的话，
    # unknown→pass 会被算成修复（实测一轮虚报 7 个）。
    # "变坏"那一档保留 `!= pass`：曾经 pass、现在连判定都没有了，本身就该看。
    newly_failing = sorted(n for n in (set(b_cases) & set(c_cases))
                           if b_cases[n] == "pass" and c_cases[n] != "pass")
    fixed = sorted(n for n in (set(b_cases) & set(c_cases))
                   if b_cases[n] == "fail" and c_cases[n] == "pass")
    added = sorted(set(c_cases) - set(b_cases))
    removed = sorted(set(b_cases) - set(c_cases))
    result["cases"] = {"newly_failing": newly_failing, "fixed": fixed,
                       "added": added, "removed": removed,
                       "common": len(set(b_cases) & set(c_cases))}

    verdict_changed = (sides["baseline"]["verdict"] != sides["current"]["verdict"]
                       or sides["baseline"]["signoff_status"]
                       != sides["current"]["signoff_status"])
    result["verdict"] = {"changed": verdict_changed,
                         "baseline": sides["baseline"]["verdict"],
                         "current": sides["current"]["verdict"]}
    result["summary"] = {
        "newly_failing": len(newly_failing),
        "fixed": len(fixed),
        "added": len(added), "removed": len(removed),
        "coverage_delta": (result["coverage"].get("overall_pct") or {}).get("delta"),
        "verdict_changed": verdict_changed,
    }

    # ── 不粉饰的说明 ──
    if not b_cases or not c_cases:
        result["notes"].append("有一侧没有回归产物 —— 用例级对比不完整（覆盖率对比不受影响）")
    if newly_failing:
        result["notes"].append(f"**{len(newly_failing)} 个用例从通过变成没通过** "
                               f"—— 这是这张表存在的理由，先看它们")
    if not newly_failing and result["summary"]["fixed"]:
        result["notes"].append("没有用例变坏；上一轮挂的有所修复")
    if verdict_changed:
        result["notes"].append(
            f"判定从 {sides['baseline']['verdict'] or '-'} 变为 "
            f"{sides['current']['verdict'] or '-'}")
    return result


# ═══════════════════════════════════════════════════════════════
# 待办 / 卡点 —— 「现在该干什么」
# ═══════════════════════════════════════════════════════════════

#: 待办类别 → （中文, 语气）。语气决定界面上的颜色：warn=要你处理、info=看一眼。
TODO_KINDS = {
    "approval": ("待审批", "warn"),
    "exclude": ("待签豁免", "warn"),
    "human": ("需人工确认", "warn"),
    "stuck": ("卡住的运行", "warn"),
    "harness": ("bench 侧挂死", "info"),
    "incomplete": ("产物不全", "info"),
}


def collect_todos(run_dir: str = "") -> Dict[str, Any]:
    """**「现在该干什么」** —— 把散在四个页面里的"需要人做的事"聚成一页。

    数据全是现成的，这页只做**聚合与排序**：

      · 待签的覆盖率豁免  —— 豁免登记册里 `pending` 的那几条（批了会动覆盖率分母）
      · 需人工确认        —— 阶段里的 `needs_human`（如 CDC："同步器对不对机器判不了"）
      · 待审批            —— 运行停在人工审批上（`approval` 阶段有 token 而没有结论）
      · 卡住的运行        —— 状态还是 running 但产物已经不再更新
      · bench 侧挂死      —— `harness_triage` 归过类的那几条（看一眼，**不改 RTL**）
      · 产物不全          —— 没有 `report.json`（没跑到 audit）→ 后面的页多半是空的

    排序：**要你动手的（warn）在前**，看一眼的（info）在后 —— 这页是"待办"，
    不是"概览"。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error

    rows: List[Dict[str, Any]] = []

    # ── 待签豁免（**全局登记册**，不只这次运行）──
    # 提议由覆盖率阶段的自动发现一直攒，而批准会动覆盖率分母（不可逆），
    # 所以"有没有攒着没人批的"是这页最该先说的一条。
    try:
        from src.tools.checking.coverage_tools.exclude_api import read_excludes

        pending = (read_excludes() or {}).get("pending") or []
        if pending:
            rows.append({
                "kind": "exclude", "priority": 10,
                "item": f"{len(pending)} 条覆盖率豁免待签字",
                "detail": "、".join(str(p.get("id") or p) for p in pending[:5]),
                "action": "在「覆盖率豁免」页签（批准会把该点从覆盖率分母里拿掉）",
            })
    except Exception:                                  # noqa: BLE001 注册册读不到不算待办
        pass

    progress = _read_json(root / "docs" / "progress.json") or {}
    phases = progress.get("phases") or []

    # ── 需人工确认（根因的验证计划里 needs_human 那一档）──
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        if phase.get("needs_human"):
            rows.append({
                "kind": "human", "priority": 20,
                "item": f"「{phase.get('name', '')}」需要人工确认（{phase.get('root_cause', '')}）",
                "detail": str(phase.get("needs_human"))[:160],
                "action": "看「决策轨迹」里这一轮的根因与验证计划",
            })

    # ── 待审批：停在人工审批上的运形 ──
    stuck_approval = [p for p in phases
                      if isinstance(p, dict) and p.get("name") == "approval"
                      and p.get("token") and not p.get("outcome")]
    if stuck_approval:
        rows.append({
            "kind": "approval", "priority": 5,
            "item": f"运行停在人工审批上（{len(stuck_approval)} 处）",
            "detail": "、".join(str(p.get("action", "")) for p in stuck_approval[:3]),
            "action": "在「验证流程」页批准或拒绝，然后继续",
        })

    # ── 卡住 / 产物不全 ──
    has_report = (root / "report.json").exists()
    events = _read_journal(root)
    finished = bool(events) and str(events[-1].get("kind", "")) == "run.finished"
    if events and not finished:
        rows.append({
            "kind": "stuck", "priority": 8,
            "item": "这次运行没有正常结束（没有 run.finished 事件）",
            "detail": f"最后一条事件：{events[-1].get('kind', '')} "
                      f"{events[-1].get('stage', '')} @ {events[-1].get('ts', '')}",
            "action": "看「控制台」尾部日志；必要时重起一次运行",
        })
    elif not has_report:
        rows.append({
            "kind": "incomplete", "priority": 30,
            "item": "这次运行没有 report.json（没跑到 audit）",
            "detail": "签核判定 / 运行清单那几页会因此是空的",
            "action": "让它跑完，或换一次完整运行（「运行历史」）",
        })

    # ── bench 侧挂死（归过类的）──
    for phase in phases:
        if not isinstance(phase, dict):
            continue
        triage = phase.get("harness_triage") or []
        if triage:
            prints = [str(t.get("fingerprint", "")) for t in triage if t.get("fingerprint")]
            rows.append({
                "kind": "harness", "priority": 40,
                "item": f"{len(triage)} 个 test 挂在 bench 侧（不是 DUT 功能错）",
                "detail": ("指纹：" + "、".join(p for p in prints[:3]) if prints
                           else str(triage[0].get("note", ""))[:120]),
                "action": "这些不改 RTL；看「回归状态」页的日志确认原因",
            })
            break

    rows.sort(key=lambda r: r.get("priority", 99))
    summary = {k: sum(1 for r in rows if r["kind"] == k) for k in TODO_KINDS}
    return {"run_dir": str(root), "rows": rows, "summary": summary,
            "notes": ([f"{sum(1 for r in rows if TODO_KINDS[r['kind']][1] == 'warn')} 项要你动手"]
                      if rows else ["没有待办 —— 这次运行没有需要人处理的事项"])}


# ═══════════════════════════════════════════════════════════════
# 规则草案（界面读入口）
# ═══════════════════════════════════════════════════════════════

#: 草案该拦在哪 → 中文（与 `rule_draft.STAGE_TITLES` 同源，界面只认键）
def run_rule_drafts(run_dir: str = "") -> Dict[str, Any]:
    """这次运行起草了哪些规则草案、**哪些还没被人接受**。

    只读 + 带粘贴骨架：这一页的价值是"让草案看得见、点一下就接走" ——
    原来它只写在 `docs/rule_drafts.md` 里，得有人想起来去翻。
    """
    root, error = _resolve_run_dir(run_dir)
    if error:
        return error
    try:
        from src.layers.l4_memory.rule_draft import (STAGE_TITLES, accepted_ids,
                                                    collect_drafts, rule_skeleton)

        drafts = collect_drafts(root)
        done = set(accepted_ids(root))
        rows = [{
            "rule_id": str(d.get("rule_id", "")),
            "stage": STAGE_TITLES.get(str(d.get("stage", "")), str(d.get("stage", ""))),
            "severity": str(d.get("severity", "")),
            "evidence": str(d.get("note", ""))[:160],
            "fingerprint": str(d.get("fingerprint", ""))[:12],
            "accepted": str(d.get("rule_id", "")) in done,
            "skeleton": rule_skeleton(d),
        } for d in drafts]
        pending = [r for r in rows if not r["accepted"]]
        return {"run_dir": str(root), "rows": rows, "pending": len(pending),
                "md_path": str(root / "docs" / "rule_drafts.md"),
                "notes": ([f"{len(pending)} 条草案等人拍板 —— 接了就写进 semantic_check"]
                          if pending else ["没有待拍板的草案"])}
    except Exception as exc:                           # noqa: BLE001
        return {"error": f"读草案失败：{exc}"[:200]}
