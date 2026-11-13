"""回归视图 —— 回归状态矩阵 / 运行对比（只读一次运行目录）。"""
from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.layers.l1_infrastructure.layout import (
    latest_root as _layout_latest_root,
    regression_root as _layout_regression_root,
    stage_roots as _layout_stage_roots,
    test_dirs as _layout_test_dirs,
)
from src.layers.l2_orchestration.flow_shared import (
    _COV_FIELDS, _artifacts_of, _payload_line, _read_json, _resolve_run_dir,
    _size_kb, _stages_of,
)

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


_UVM_TALLY_RE = re.compile(r"UVM_(?:ERROR|FATAL)\s*:\s*([1-9]\d*)")


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


def _tp_ids_by_task(run_root: Path) -> Dict[str, List[str]]:
    """`waves/manifest.json` → `{task: [tp_id…]}`；没有就给空。

    **读不到不是错误**：老 run / 没做逐用例取证时没有 manifest，界面那一列
    空着就是事实（不是"这条没有测试点"）。
    """
    try:
        from src.tools.common.lib.case_meta import read_wave_manifest
        manifest = read_wave_manifest(run_root)
    except Exception:                                  # noqa: BLE001 旁路
        return {}
    return {str(e.get("task")): list(e.get("tp_ids") or [])
            for e in (manifest.get("entries") or []) if isinstance(e, dict)}


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
        from src.layers.l3_decision.evidence.cov_api import file_facts

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
        from src.layers.l3_decision.evidence.cov_api import find_coverage_db

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

    # 用例 → 测试点：`waves/manifest.json` 是回归收尾写的唯一映射（task → tp_ids）。
    # 没有 manifest（老 run / 没做逐用例取证）就是空 —— 不猜。
    tp_by_task = _tp_ids_by_task(root)

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
            # 这条用例证明哪些测试点（`waves/manifest.json` 的 task → tp_ids）。
            # 空列表 = 没登记（批次用例 / 老 run），不是"没有测试点"。
            "tp_ids": tp_by_task.get(name, []),
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
