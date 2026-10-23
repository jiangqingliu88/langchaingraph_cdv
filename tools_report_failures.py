"""把一个 run 的**全部失败信息**收成一份文件。

## 为什么需要它

跑不通的时候，失败信息散在七八个地方，每一处都只说一部分：

    regression_stages.json      哪一级挂了 / 停在哪
    regression_run/<级>/report.json   那一级里哪几条用例挂了
    <用例>/sim.log                    那条用例**为什么**挂（判据的结论）
    <用例>/sim_vsim.log               仿真输出（真正的错误行在这里）
    <用例>/status.env                 框架自己的裁决
    report.json                       签核的门禁与 caveat
    docs/evidence_chain.json          七层证据各自几比几
    docs/run_events.jsonl             闭环每一轮发生了什么
    validation_report.txt / tr_db.log 其它旁证

逐个去翻很费事，而且**只看一处会漏掉根因**（这条链上实测过：日志里满屏的
断言错，真凶却是"编译没过、env_pkg 作废"或者"驱动器没驱动、输入全是 X"）。
所以一次性铺开，按"从结论到证据"的顺序排。

用法:
    python tools_report_failures.py <run_dir> [-o 输出.md]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

#: 每份仿真日志里最多摘这么多条错误行 —— 同一条规则每一拍都报，全抄会把文件淹掉。
MAX_ERR_LINES = 25


def _rd(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return default


def _lines(p: Path):
    try:
        return p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _sim_errors(log: Path):
    """仿真日志 → (错误行, 计数)。`** Error:` / `UVM_ERROR` / `UVM_FATAL` 都算。"""
    pat = re.compile(r"\*\* Error|\*\* Fatal|UVM_ERROR\b|UVM_FATAL\b|"
                     r"NO_CHECKER_EVIDENCE|Errors: *[1-9]")
    hits = [ln.strip() for ln in _lines(log) if pat.search(ln)]
    # 去重保序（同一条规则每拍都报，留一条 + 计数就够）
    seen, uniq = {}, []
    for h in hits:
        key = re.sub(r"@ *[\d.]+ *ns", "@ <t> ns", h)
        if key not in seen:
            seen[key] = 1
            uniq.append(h)
        else:
            seen[key] += 1
    return uniq, len(hits)


def _plan_stage_owners(run: Path) -> dict:
    """`regression.yaml` → `{测试目录名: 归属级}`。

    **为什么需要它**：每次 stage 的 build 都会把**全量**用例脚本铺出来
    （244 个 `sim.sh`），但每个 stage 只跑自己 tag 的那一部分。只看目录会
    以为"p0 里 194 条没跑"，其实它们分别是 p1/p2/p3/loopback 的用例 ——
    归属要对回 plan 才说得清。
    """
    # **这是 YAML，不是 JSON** —— `_rd` 走 `json.loads`，读它会静默得到空表，
    # 于是所有用例都被判成"归属不明"（实测）。
    try:
        import yaml as _yaml
    except ImportError:                               # 报告工具不该因缺依赖挂掉
        return {}
    try:
        reg = _yaml.safe_load(
            (run / "inputs" / "yaml" / "regression.yaml").read_text(
                encoding="utf-8", errors="replace")) or {}
    except (OSError, _yaml.YAMLError):
        return {}
    out = {}
    for t in reg.get("tests") or []:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        tags = [str(x) for x in (t.get("tags") or [])]
        owner = next((x for x in tags if x in ("p0", "p1", "p2", "p3")), "")
        if not owner and "loopback" in tags:
            owner = "loopback"
        try:
            cnt = int(t.get("count") or 1)
        except (TypeError, ValueError):
            cnt = 1
        seed = (t.get("variables") or {}).get("SEED")
        for i in range(max(1, cnt)):
            if cnt == 1:
                full = name
            elif isinstance(seed, (int, float)):
                full = f"{name}_run_{i + 1}_seed_{int(seed) + i}"
            else:
                full = f"{name}_run_{i + 1}"
            out[f"test_{full}"] = owner
    return out


def collect(run: Path) -> str:
    out = []
    w = out.append
    w(f"# 失败报告 — `{run.name}`\n")

    # ── 0. 结论 ──
    rep = _rd(run / "report.json", {}) or {}
    stages = _rd(run / "regression_stages.json", {}) or {}
    w("## 0. 结论\n")
    w(f"- 签核判定：**{rep.get('verdict', '（没有 report.json）')}**"
      f"（`{rep.get('signoff_status', '?')}`）")
    w(f"- 回归：passed={stages.get('passed', '?')} failed={stages.get('failed', '?')}"
      f" status={stages.get('status', '?')}"
      + (f" blocked_at={stages.get('blocked_at')}" if stages.get("blocked_at") else ""))
    if rep.get("caveats"):
        w("- 签核 caveat：")
        for c in rep["caveats"]:
            w(f"  - {c}")
    if rep.get("gates"):
        w("- 硬门禁：")
        for k, v in rep["gates"].items():
            if isinstance(v, bool):
                w(f"  - {k}: {'PASS' if v else '**FAIL**'}")
    w("")

    # ── 1. 分级回归（**跑了几条 ≠ 报告了几条**）──
    #
    # 框架的 `total` 里**混着编译任务**（`<module>` 那条 build），它不跑仿真；
    # 而 build 目录里还会生成**全部**用例脚本，每条都有一份 `sim.sh` ——
    # 所以"报告 7/7 PASS"与"目录里 218 个 sim.sh"看着都对，说的却是两件事。
    # 只报 total/pass 会让人以为**每一条都跑了**（实测：p0 报 7 条，真跑 6 条）。
    owners = _plan_stage_owners(run)
    w("## 1. 分级回归（**跑了几条 ≠ 报告了几条**）\n")
    w("| 级 | 状态 | 报告 total/pass | 其中编译任务 | **真执行的仿真** "
      "| **本级未跑** | 其它级预生成 | 跑了但没比对结论 |")
    w("|---|---|---|---|---|---|---|---|")
    for s in stages.get("stages", []) or []:
        name = s.get("name", "?")
        stage_dir = run / "regression_run" / name
        srep = _rd(stage_dir / "report.json", {}) or {}
        tasks = [t for t in (srep.get("tasks") or []) if isinstance(t, dict)]
        executed, builds = [], []
        for t in tasks:
            wd = Path(str(t.get("work_dir") or ""))
            (executed if (wd / "sim_vsim.log").is_file() else builds).append(t)
        # 生成的全部用例目录（每个含一份 sim.sh）
        generated = {p.parent for p in stage_dir.rglob("sim.sh")} if stage_dir.is_dir() else set()
        ran_dirs = {p.parent.name for p in stage_dir.rglob("sim_vsim.log")}
        unrun = {p.name for p in generated} - ran_dirs
        own_unrun = [n for n in unrun if owners.get(n) == name]
        other_unrun = [n for n in unrun if owners.get(n) != name]
        # 真跑了、但判据说"没有比对结论"的
        no_ev = sum(1 for t in executed
                    if any("NO_CHECKER_EVIDENCE" in ln
                           for ln in _lines(Path(str(t.get("work_dir"))) / "sim.log")))
        mark = "**FAIL**" if s.get("status") == "FAIL" else s.get("status", "?")
        w(f"| {name} | {mark} | {s.get('passed')}/{s.get('total')} | {len(builds)} "
          f"| **{len(executed)}** | **{len(own_unrun)}** | {len(other_unrun)} | {no_ev} |")
    w("")
    w("> 读法：**「报告 total/pass」含编译任务**；**「真执行的仿真」**= 有 "
      "`sim_vsim.log` 的用例数；**「本级未跑」**= 按 `regression.yaml` 的 tag "
      "应属于本级、但本级没跑的（**这才是真缺口**）；**「其它级预生成」**= "
      "非分级 / 旧 run 的 build 会铺全量脚本，属于别的分级、会在别处跑；"
      "**分级 run 已按 tag 裁剪，这一列通常为 0**；")
    w("> **「跑了但没比对结论」**= 仿真跑完、但判据打的是 "
      "`NO_CHECKER_EVIDENCE`（没接检查组件 / 检查组件没出结论）—— "
      "**那不是通过**。\n")

    # ── 1b. **生成了但没执行**的用例（真正的"没跑"）──
    #
    # 这一节回答的是"回归里到底哪些仿真没跑"。它不在 report.json 里 ——
    # 那份只列**调度过**的任务；没被调度的一个字都没有。
    w("## 1b. 生成了但没执行的用例（按归属级拆开）\n")
    any_unrun = False
    any_own = False
    for stage in stages.get("stages", []) or []:
        name = stage.get("name", "")
        stage_dir = run / "regression_run" / name
        if not stage_dir.is_dir():
            continue
        runs = {p.parent.name for p in stage_dir.rglob("sim_vsim.log")}
        gen = {p.parent.name for p in stage_dir.rglob("sim.sh")}
        unrun = sorted(gen - runs)
        if not unrun:
            continue
        any_unrun = True
        own = [n for n in unrun if owners.get(n) == name]
        other = [n for n in unrun if owners.get(n) != name]
        by_owner = {}
        unknown = []
        for n in other:
            owner = owners.get(n, "")
            if owner:
                by_owner[owner] = by_owner.get(owner, 0) + 1
            else:
                unknown.append(n)
        own_mark = f"**本级未跑 {len(own)}**" if own else "本级未跑 0"
        w(f"### {name}：生成 {len(gen)} / 执行 {len(runs)} —— {own_mark}，"
          f"其它级预生成 {len(other)}\n")
        if by_owner:
            w("- 其它级归属："
              + "、".join(f"{k} {v}" for k, v in sorted(by_owner.items())))
        if unknown:
            w(f"- 归属不明（plan 里找不到）：{len(unknown)} —— "
              f"`{'`、`'.join(unknown[:6])}`")
        if own:
            any_own = True
            w(f"- **本级该跑却没跑**：`{'`、`'.join(own[:10])}`"
              + (f" …（共 {len(own)}）" if len(own) > 10 else ""))
        else:
            w("- 本级 tag 的用例**全部跑了**；上面的未执行目录都属于其它级，"
              "每次 build 会铺全量脚本，属于既定设计。")
        w("")
    if not any_unrun:
        w("（每一级生成的用例都执行了）\n")
    elif not any_own:
        w("> 结论：**没有一条用例被漏跑**。每个 stage 的 build 都会铺出全量"
          " `sim.sh`，但只执行自己 tag 的那一批；其余目录会在各自的分级里跑。\n")

    # ── 2. 失败用例 ──
    w("## 2. 失败用例（逐条 + 为什么）\n")
    total_fail = 0
    for stage_dir in sorted((run / "regression_run").glob("*")):
        if not stage_dir.is_dir():
            continue
        srep = _rd(stage_dir / "report.json", {}) or {}
        fails = [t for t in (srep.get("tasks") or []) if t.get("status") == "fail"]
        if not fails and not (stage_dir / "fail").exists():
            continue
        w(f"### {stage_dir.name}（{len(fails)} 条 fail）\n")
        for t in fails:
            total_fail += 1
            # `work_dir` 是**相对仓库根**的路径，**已经含 run 目录名** ——
            # 写成 `run / work_dir` 会拼成 `run/run/...`（实测：整个第 2 节
            # 因此全空，而看不出哪里错了）。先按原样试，再退回相对 run 的拼法。
            _wd = str(t.get("work_dir") or "")
            wd = Path(_wd)
            if not wd.is_dir():
                wd = run / _wd.replace(f"{run.name}\\", "").replace(f"{run.name}/", "")
            w(f"**{t.get('name')}** — `{t.get('work_dir')}`\n")
            # 判据的结论（框架写的那一行）
            for f in ("sim.log", "build.log"):
                txt = [ln.strip() for ln in _lines(wd / f) if ln.strip()]
                if txt:
                    w(f"- `{f}`：")
                    for ln in txt[:4]:
                        w(f"  - `{ln[:200]}`")
            errs, n = _sim_errors(wd / "sim_vsim.log")
            if errs:
                w(f"- `sim_vsim.log` 共 {n} 条错误行，去重后 {len(errs)} 类：")
                for e in errs[:MAX_ERR_LINES]:
                    w(f"  - `{e[:200]}`")
                if len(errs) > MAX_ERR_LINES:
                    w(f"  - …（其余 {len(errs) - MAX_ERR_LINES} 类见原日志）")
            w("")
    if not total_fail:
        w("（没有 fail 用例）\n")

    # ── 3. 检查组件 / SCB 的结论 ──
    w("## 3. 检查组件的结论（`mismatched=0` 那半）\n")
    seen_scb = set()
    for log in sorted((run / "regression_run").rglob("sim_vsim.log")):
        for ln in _lines(log):
            if "SCB_DUT" in ln or "DUT_CHK" in ln:
                k = ln.strip()[:160]
                if k in seen_scb:
                    continue
                seen_scb.add(k)
                w(f"- `{log.parent.name}`：{ln.strip()[:220]}")
    if not seen_scb:
        w("（没有比对结论 —— 要么没跑到，要么没接检查组件）")
    w("")

    # ── 3b. 测试点矩阵（缺口归因到 tp_id）──
    #
    # 覆盖率报告只给"哪个 coverpoint 百分之几"，一个 coverpoint 可能对应十几条
    # 测试点。矩阵回答的是"缺的是哪一条、属于谁、是不是根本不可激励"。
    w("## 3b. 测试点矩阵（`coverage/tp_matrix.json`）\n")
    tp = _rd(run / "coverage" / "tp_matrix.json", {}) or {}
    if not tp:
        w("（这一轮没有测试点 IR —— 没有 case 模型或没跑覆盖率）\n")
    else:
        w(f"- 总计 **{tp.get('total', '?')}** 条："
          f"可激励 {tp.get('drivable', '?')}（命中 {tp.get('drivable_hit', '?')}，"
          f"{tp.get('drivable_pct', '?')}%）· "
          f"观测型 {tp.get('observe_only', '?')}（到达 {tp.get('observed', '?')}）")
        w(f"- 状态计数：`{json.dumps(tp.get('counts') or {}, ensure_ascii=False)}`")
        missed = tp.get("missed") or []
        if missed:
            w(f"\n### 未命中的测试点（{len(missed)} 条）\n")
            w("| tp_id | 维度=取值 | 覆盖仓 | 类型 | 级 | 需求 |")
            w("|---|---|---|---|---|---|")
            for r in missed[:40]:
                kind = "观测" if r.get("observe_only") else "激励"
                w(f"| `{r.get('tp_id')}` | {r.get('dimension')}={r.get('value')} "
                  f"| `{r.get('coverpoint')}.{r.get('bin')}` | {kind} "
                  f"| {r.get('stage', '')} | {r.get('requirement', '')} |")
            if len(missed) > 40:
                w(f"\n（其余 {len(missed) - 40} 条见 `coverage/tp_matrix.json`）")
        unmapped = tp.get("unmapped") or []
        if unmapped:
            w(f"\n- **{len(unmapped)} 条测试点的覆盖仓在报告里找不到** "
              f"（模型与覆盖率模型漂了）："
              f"`{'`、`'.join(str(r.get('tp_id')) for r in unmapped[:8])}`")
        w("")

    # ── 4. 证据链七层 ──
    w("## 4. 证据链七层\n")
    ev = _rd(run / "docs" / "evidence_chain.json", {}) or {}
    layers = ev.get("layers") or {}
    w(f"（`checks_passed`={ev.get('checks_passed')}/{ev.get('checks_total')}"
      f"  signoff_ready={ev.get('signoff_ready')}）\n")
    for name, v in layers.items():
        if not isinstance(v, dict):
            w(f"- **{name}**：{str(v)[:160]}")
            continue
        got, tot = v.get("passed", "?"), v.get("total", "?")
        bad = (isinstance(got, int) and isinstance(tot, int) and got < tot)
        mark = "**" if bad else ""
        w(f"- {mark}{name}{mark}（{got}/{tot}）— {v.get('description', '')}")
        for ck, ok in (v.get("checks") or {}).items():
            if not ok:
                w(f"  - ✗ `{ck}`")
        if bad and v.get("evidence"):
            w(f"  - 证据：`{json.dumps(v['evidence'], ensure_ascii=False)[:300]}`")
    fc = ev.get("functional_coverage") or {}
    if fc:
        w(f"- **functional_coverage**：{json.dumps(fc, ensure_ascii=False)[:200]}")
    w("")

    # ── 5. 闭环事件（每轮回归结论 + 决策）──
    #
    # **失败信息大多不在 `kind` 里**：`stage.finished` 的 `status` 恒为 `"ok"`
    #（那是"这一步跑完了"，不是"这一步的结论好"）。真正的结论在
    # `payload.delta` 里 —— 回归的 `status=FAIL` / `blocked_at` / `blocked_reason`
    # 都在那儿。只按 `kind.endswith(".failed")` 过滤会得到"一片空白"，
    # 而那一轮其实每一轮都挂着（实测）。
    w("## 5. 闭环每一轮发生了什么\n")
    jl = run / "docs" / "run_events.jsonl"
    shown = 0
    for ln in _lines(jl):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        kind = str(e.get("kind") or "")
        payload = e.get("payload") or {}
        delta = payload.get("delta") or {}
        reg = delta.get("regression") or {}
        cov = delta.get("coverage") or {}
        if kind == "stage.finished" and reg:
            st = reg.get("status", "?")
            mark = "**" if st != "PASS" else ""
            w(f"- 第 {e.get('round')} 轮 · 回归 {mark}{st}{mark} "
              f"passed={reg.get('passed')} failed={reg.get('failed')}"
              + (f" blocked_at=`{reg.get('blocked_at')}`" if reg.get("blocked_at") else ""))
            if reg.get("blocked_reason"):
                w(f"  - 原因：{str(reg['blocked_reason'])[:200]}")
            for s in (reg.get("stages") or []):
                if str(s.get("status", "")).upper() not in ("PASS", "SKIP", ""):
                    w(f"  - 级 {s.get('name')}: {s.get('status')} "
                      f"{s.get('passed')}/{s.get('total')} {str(s.get('reason') or '')[:120]}")
            shown += 1
        elif kind == "stage.finished" and cov:
            w(f"- 第 {e.get('round')} 轮 · 覆盖率 "
              f"{cov.get('functional_pct', cov.get('overall_pct', '?'))}%")
            shown += 1
        elif kind.endswith(".failed") or kind in ("run.failed", "run.interrupted"):
            w(f"- `{kind}` {e.get('stage') or ''} "
              f"{str(payload.get('error') or payload.get('reason') or '')[:180]}")
            shown += 1
    if not shown:
        w("（事件流里没有可读的轮次结论）")
    w("")

    # ── 5a. 非 PASS 阶段**各自的原因** ──
    #
    # 阶段表只有 status/score，"为什么失败"在 `payload.delta.phases[].reason` 里
    #（例如 `env_arch_check` 那条会说清是端口归属还是 scoreboard）。不收进来，
    # 读的人只知道"它挂了"。
    w("### 非 PASS 阶段的原因\n")
    reasons = []
    for ln in _lines(jl):
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if e.get("kind") != "stage.finished":
            continue
        for p in ((e.get("payload") or {}).get("delta") or {}).get("phases") or []:
            if not isinstance(p, dict):
                continue
            if str(p.get("status", "")).lower() in ("failed", "error", "blocked"):
                reasons.append((e.get("round"), e.get("stage"), p))
    if reasons:
        for rnd, stage, p in reasons[:20]:
            w(f"- 第 {rnd} 轮 · **{p.get('name') or stage}**（{p.get('status')}，"
              f"score={p.get('score', '-')}）")
            if p.get("reason"):
                w(f"  - {str(p['reason'])[:300]}")
    else:
        w("（没有非 PASS 阶段）")
    w("")

    # ── 5b. 阶段表（CLI 打的那张）──
    prog = _rd(run / "docs" / "progress.json", {}) or {}
    phases = prog.get("phases") or []
    if phases:
        w("### 阶段表（`docs/progress.json`）\n")
        w("| 阶段 | 状态 | 分数 |")
        w("|---|---|---|")
        for p in phases:
            st = str(p.get("status", "?"))
            mark = "**FAIL**" if st in ("failed", "error") else st
            w(f"| {p.get('name', '?')} | {mark} | {p.get('score', '-')} |")
        w("")

    # ── 6. 旁证 ──
    w("## 6. 旁证文件\n")
    for name in ("validation_report.txt", "tr_db.log"):
        p = run / name
        if p.is_file():
            body = _lines(p)
            w(f"### `{name}`（{len(body)} 行，前 12 行）\n")
            w("```")
            out.extend(body[:12])
            w("```")
    return "\n".join(out) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("-o", "--out", default="")
    a = ap.parse_args()
    run = Path(a.run_dir)
    if not run.is_dir():
        raise SystemExit(f"不是目录: {run}")
    text = collect(run)
    out = Path(a.out) if a.out else run / "FAILURES.md"
    out.write_text(text, encoding="utf-8")
    print(f"已写出 {out}（{len(text.splitlines())} 行）")


if __name__ == "__main__":
    main()
