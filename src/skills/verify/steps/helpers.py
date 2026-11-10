"""verify 的纯函数助手 —— 位图 / 发现 / 约束端口 / case 模型桥。

从 `executors/verify/main.py` 抽出（Phase 2.1）；行为不变，main 通过 import 使用。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


def _main_phase_objection_at(text: str) -> int:
    """`main_phase` 里那句 `phase.raise_objection(this);` 的**下标**（没有则 -1）。

    为什么要专门找它：`configure_phase` 里有一模一样的一句，而那个相位**拿不到
    sequencer 的事务递送**（sequencer 的 run_phase 还没开始）—— 把激励注进那里
    等于注进一个永远等不到应答的地方。见调用处那段注释。
    """
    import re

    m = re.search(r"\btask\s+main_phase\s*\(", text)
    if not m:
        return -1
    return text.find("    phase.raise_objection(this);\n", m.end())


def _test_files_defining(tests_dir: Path, class_name: str) -> list:
    """在 `env/tests/` 里找出**定义了 `class <class_name>`** 的文件。

    **不能按文件名找**：文件名和类名不是一回事（实测：文件是
    `apb_uart_env_direct_test.sv`，里面的类叫 `apb_uart_env_directed_test`）——
    按 `<类名>.sv` 去找会找不到，然后退回"猜一个测试文件"，注入到永远不跑的那个。
    """
    import re

    pattern = re.compile(rf"\bclass\s+{re.escape(class_name)}\b")
    found = []
    for sv in sorted(tests_dir.glob("*.sv")):
        try:
            if pattern.search(sv.read_text(encoding="utf-8", errors="replace")):
                found.append(sv)
        except OSError:
            continue
    return found


def _regression_test_name(output_root: Path) -> str:
    """回归配置里 `<build>/<test>` 实际跑的 UVM 测试名（`+UVM_TESTNAME=...`）。

    读 `<运行目录>/inputs/yaml/regression.yaml`。读不到返回空串 —— 调用方会退回
    "按名字猜测试文件"，但那只是权宜：**猜错了定向激励就等于没补**。
    """
    import re

    cfg = Path(output_root) / "inputs" / "yaml" / "regression.yaml"
    if not cfg.exists():
        return ""
    try:
        m = re.search(r"\+UVM_TESTNAME=(\w+)",
                      cfg.read_text(encoding="utf-8", errors="replace"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def _spec_of(output_dir: Path) -> Dict[str, Any]:
    """这次运行的 spec —— 从 `<run>/spec.json` 读（verify 自己在 UVM 生成前落的那份）。

    写盘器（field_bins / DUT 探针）拿不到调用栈里的 `spec` 变量，而
    `spec.json` 就是"这次运行的 spec"的落点，读它比把 spec 一路透传干净。
    """
    try:
        return json.loads((output_dir / "spec.json").read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def _load_runtime_model_doc(text: str) -> Dict[str, Any]:
    """运行期模型文本 → dict（`vplan/runtime/coverage_parse`）。"""
    from src.layers.l3_decision.vplan.runtime.coverage import parse_model_text

    return parse_model_text(text)


def _assertion_signals(decls: Dict[str, Any]) -> List[Dict[str, Any]]:
    """`assertions[].signals` → 覆盖率接口要额外引的信号（实现同一处）。"""
    from src.layers.l3_decision.vplan.runtime.coverage import assertion_signals

    return assertion_signals(decls)


def _bitmap_patch(output_dir: Path, tp_payload: Dict[str, Any],
                  cov_payload: Dict[str, Any],
                  agent_fields: Dict[str, List[str]]) -> Dict[str, Any]:
    """位图 → 落盘 + 返回可并进 `env_cov_bins` 的补丁（`{}` = 没有位图）。"""
    bitmap = _build_tp_bitmap(tp_payload or {}, cov_payload, agent_fields)
    _write_tp_bitmap(output_dir, bitmap)
    if not bitmap.get("width"):
        return {}
    tracked = sum(1 for e in bitmap["entries"] if e["trackable"])
    logger.info(f"测试点位图：{bitmap['width']} 位（{tracked} 位可追踪）"
                f"→ coverage/tp_bitmap.json")
    return {"tp_bitmap": bitmap}


def _retire_stale_probe(iface_path: Path) -> None:
    """删掉上一版的独立探针 —— 它和接口采同一批信号，会重复计量。"""
    stale = iface_path.parent / "dut_probe.sv"
    if not stale.exists():
        return
    stale.unlink()
    logger.info(f"清掉上一版的 DUT 探针 {stale.name}：DUT 通道已改走 "
                f"{iface_path.name} + env 覆盖率组件（两个 covergroup 采同一批"
                f"信号会重复计量）")


def _timing_signals(tp_payload: Dict[str, Any] = None) -> List[Dict[str, Any]]:
    """TP 的 `timing.start/end` → 覆盖率接口要额外引的信号。

    只收合法 SV 标识符：接口端口只能同名连接，`a && b` 这种表达式引不出来。
    非标识符由 `_build_tp_bitmap` 标成 `checkable=False`，不生成假检查。
    """
    out: List[Dict[str, Any]] = []
    for tp in (tp_payload or {}).get("testpoints") or []:
        if not isinstance(tp, dict):
            continue
        timing = tp.get("timing") or {}
        for key in ("start", "end"):
            name = str(timing.get(key) or "").strip()
            if name and re.fullmatch(r"[A-Za-z_][\w$]*", name):
                out.append({"name": name, "width": 1})
    return out


def _sv_ident(name: str) -> str:
    return name if re.fullmatch(r"[A-Za-z_][\w$]*", name or "") else ""


def _bitmap_timing(tp: Dict[str, Any]) -> Dict[str, Any] | None:
    """TP 的 timing → 位图里那一格（没有 / 不可判都给 `checkable=False`）。"""
    timing = tp.get("timing") or {}
    if not timing:
        return None
    spec = timing.get("expect_cycles") or {}
    start = _sv_ident(str(timing.get("start") or ""))
    end = _sv_ident(str(timing.get("end") or timing.get("sample") or ""))
    tm = {"min": int(spec.get("min", 0) or 0),
          "max": int(spec.get("max", 0) or 0),
          "tolerance": int(timing.get("tolerance") or 0),
          "start": start, "end": end,
          "sample": _sv_ident(str(timing.get("sample") or ""))}
    tm["checkable"] = bool(start and end and tm["max"] >= tm["min"])
    return tm


def _bitmap_agent(tp: Dict[str, Any], signal: str,
                  agent_fields: Dict[str, List[str]]) -> str:
    """激励字段 → 承载它的 agent（模型声明的优先，其次按字段反查）。"""
    declared = str((tp.get("realization") or {}).get("agent") or "")
    if signal in (agent_fields.get(declared) or []):
        return declared
    return next((a for a, fields in agent_fields.items() if signal in fields), "")


def _untrackable_note(tid: str, cp_name: str, bin_name: str, cp: dict,
                      bin_spec: Any, source: str, agent: str,
                      signal: str, literal: str) -> str:
    """不可追踪的原因（空串 = 可追踪）。**不编位**，如实说为什么。"""
    if not tid or not cp_name or not bin_name:
        return "没有 coverpoint/bin（行为域或未追踪）"
    if not cp:
        return "覆盖率模型里没有这个覆盖点（模型/生成漂移）"
    if bin_spec is None:
        return "覆盖点没有显式 bin（自动分箱无法逐 bin 追踪）"
    if source == "stimulus" and not agent:
        return "找不到承载字段的 agent（激励通道不可追踪）"
    if "$" in literal:
        return "开区间 `[lo:$]` 无法在 `inside` 里表达"
    if not signal or not literal:
        return "信号名/bin 字面量缺失"
    return ""


def _bitmap_entry(bit: int, tp: Dict[str, Any], covs: Dict[str, Any],
                  agent_fields: Dict[str, List[str]]) -> Dict[str, Any]:
    """一条 TP → 位图的一格（bit / 仓 / 通道 / 可追踪性 / 时序）。"""
    tid = str(tp.get("tp_id") or "")
    cp_name = str(tp.get("coverpoint") or "")
    bin_name = str(tp.get("bin") or "")
    cp = covs.get(cp_name) or {}
    bin_spec = next((b for b in cp.get("bins") or []
                     if isinstance(b, dict) and b.get("name") == bin_name), None)
    source = str(cp.get("source") or "")
    signal = _sv_ident(str(cp.get("signal") or ""))
    literal = str((bin_spec or {}).get("literal") or "")
    agent = _bitmap_agent(tp, signal, agent_fields) if source == "stimulus" else ""
    note = _untrackable_note(tid, cp_name, bin_name, cp, bin_spec,
                             source, agent, signal, literal)
    entry: Dict[str, Any] = {
        "bit": bit, "tp_id": tid, "coverpoint": cp_name, "bin": bin_name,
        "kind": str((tp.get("realization") or {}).get("kind") or ""),
        "source": source, "agent": agent, "signal": signal,
        "literal": literal, "trackable": not note, "note": note,
    }
    timing = _bitmap_timing(tp)
    if timing:
        entry["timing"] = timing
    return entry


def _build_tp_bitmap(tp_payload: Dict[str, Any],
                     cov_payload: Dict[str, Any],
                     agent_fields: Dict[str, List[str]] = None) -> Dict[str, Any]:
    """TP IR + 覆盖率模型 → **位序固定的测试点位图**（+ 时序判据）。

    位序 = `testpoints.yaml` 的序号，**一旦发布不重排**（历史波形靠它对号）。
    每一格回答三件事：这条 TP 打哪个仓（`literal`）、在哪个通道比（dut /
    stimulus + agent）、有没有时序窗口。

    `trackable=False` 的情形（自动分箱无显式 bin、覆盖点没生成、开区间
    `[lo:$]` 在 `inside` 里表达不了）**如实标出来**：不生成一个"永远不点亮"
    的假位，也不假装它被追踪了。
    """
    tps = [tp for tp in (tp_payload or {}).get("testpoints") or []
           if isinstance(tp, dict)]
    covs = {str(cp.get("cp_name") or ""): cp
            for cp in (cov_payload or {}).get("coverpoints") or []
            if isinstance(cp, dict)}
    agent_fields = agent_fields or {}
    entries = [_bitmap_entry(bit, tp, covs, agent_fields)
               for bit, tp in enumerate(tps)]
    notes = [f"{e['tp_id']}: timing 缺 start/end 或不是合法信号名 —— "
             f"不生成时序检查（不编假期望）"
             for e in entries
             if e.get("timing") and not e["timing"]["checkable"]]
    return {"schema": "tp_bitmap_v1", "width": len(entries),
            "entries": entries, "notes": notes}


def _write_tp_bitmap(output_dir: Path, bitmap: Dict[str, Any]) -> None:
    """`coverage/tp_bitmap.json` —— 位序 ↔ tp_id（一旦发布不重排）。"""
    if not (bitmap or {}).get("width"):
        return
    path = output_dir / "coverage" / "tp_bitmap.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bitmap, ensure_ascii=False, indent=2),
                        encoding="utf-8", newline="\n")
    except OSError as e:
        logger.warning(f"测试点位图落盘失败: {e}")


#: agent 类名的后缀 —— 去掉它再加 `_seq_item` 就是事务类型名。
_AGENT_SUFFIX = "_agent"


def _seq_item_type(agent: Dict[str, Any]) -> str:
    """env.yaml 的一个 agent → 它的 seq_item 类型名。

    **从 `type` 推，不是从 `name`**：env.yaml 里 `name: npu_sched_in` 而
    `type: npu_sched_in_master_agent`，生成的事务类是
    `npu_sched_in_master_seq_item` —— 照 `name` 拼出来的
    `npu_sched_in_seq_item` **不存在**（而那个错只会在 vlog 编译时才冒出来）。

    规则与 `gen_uvm.AgentModel.seq_item_type` 逐字一致（那边也是去 `_agent`
    再加 `_seq_item`）；`master` / `slave` 的区别已经编码在 `type` 里，不用再判
    `is_master`。
    """
    typ = str(agent.get("type") or "").strip()
    base = typ[:-len(_AGENT_SUFFIX)] if typ.endswith(_AGENT_SUFFIX) else typ
    return f"{base}_seq_item" if base else ""


def _constraint_ports(output_dir: Path) -> List[Dict[str, str]]:
    """`find_spec_yaml` 写下的 env.yaml → `build_constraint` 要的 ports。

    端口**从 env.yaml 推**，不写进 case 模型：case 模型说的是建模概念
    （中文维度名），端口名/事务类型是**实现名** —— 两边的对应没有建模，
    混在一起只会让"改名"变成两处都要改。
    """
    import yaml as _yaml

    path = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    try:
        doc = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return []
    env = (doc or {}).get("environment") or {}
    ports: List[Dict[str, str]] = []
    seen: set = set()
    for agent in (env.get("agents") or []):
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name") or "").strip()
        item = _seq_item_type(agent)
        if not name or not item or name in seen:
            continue
        seen.add(name)
        ports.append({"name": name, "type": item})
    return ports
