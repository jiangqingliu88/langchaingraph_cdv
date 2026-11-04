"""覆盖率视图 —— 覆盖率汇总 / 功能覆盖率明细（只读一次运行目录）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from src.layers.l2_orchestration.flow_shared import (
    UVM_SCHEMA, _COV_FIELDS, _artifact, _line_of, _num, _read_json, _rel_to,
    _resolve_run_dir, _schema_issues, _short, _size_kb, _spec_of_run,
)

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
        from src.layers.l3_decision.evidence.cov_api import find_run_coverage

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


def _tp_evidence_section(root: Path, notes: List[str]) -> Dict[str, Any]:
    """TP Cov 证据视图（四层）—— 失败只在 notes 里说，不拖垮整页。"""
    try:
        from src.layers.l3_decision.evidence.tp_evidence import build_tp_evidence

        return build_tp_evidence(root)
    except Exception as exc:                        # noqa: BLE001 页面不该挂
        notes.append(f"TP 证据视图构建失败：{exc}")
        return {}


def _case_view_section(root: Path, notes: List[str]) -> Dict[str, Any]:
    """Case 关联视图（用例/契约/矩阵/缺口四张表）—— 失败只在 notes 里说。"""
    try:
        from src.layers.l3_decision.case_view.builder import build_case_view

        return build_case_view(root)
    except Exception as exc:                        # noqa: BLE001 页面不该挂
        notes.append(f"Case 证据视图构建失败：{exc}")
        return {}


def _case_gates_section(root: Path, notes: List[str]) -> Dict[str, Any]:
    """Case 门禁（blocker / warning / info）—— 有生成物就读，没有就是空。

    **直接读 JSON，不 import workbench**：工具层不能反向依赖工作台
    （工作台经 `bridge/catalog.py` 调工具，反了就成了环）。
    """
    doc = _read_json(root / "coverage" / "gates.json") or {}
    if not doc:
        return {}
    return {
        "verdict": doc.get("verdict", ""),
        "counts": doc.get("counts") or {},
        "blockers": list(doc.get("blockers") or [])[:20],
        "warnings": list(doc.get("warnings") or [])[:20],
        "infos": list(doc.get("infos") or [])[:20],
    }


def _summary_line(coverpoint_rows: List[Dict[str, Any]],
                  testpoint_rows: List[Dict[str, Any]], measured: bool,
                  gates: Dict[str, Any]) -> str:
    """页面顶部一句话摘要（覆盖点 / 测试点 / 实测 / Case Gate）。"""
    text = f"{len(coverpoint_rows)} 个覆盖点 / {len(testpoint_rows)} 条测试点"
    text += (f"　·　实测 {sum(1 for r in coverpoint_rows if r['measured'])} 个"
             if measured else "　·　（还没有实测数据）")
    if gates.get("verdict"):
        blockers = (gates.get("counts") or {}).get("blocker", 0)
        text += f"　·　Case Gate {gates['verdict']}（blocker {blockers}）"
    return text


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
        from src.layers.l3_decision.evidence.cov_api import functional_coverage_details

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

    tp_evidence = _tp_evidence_section(root, notes)
    case_view = _case_view_section(root, notes)
    case_gates = _case_gates_section(root, notes)

    return {
        "run_id": root.name,
        "run_dir": str(root),
        "coverpoints": coverpoint_rows,
        "testpoints": testpoint_rows,
        "tp_evidence": tp_evidence,
        "case_view": case_view,
        "case_gates": case_gates,
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
        "summary": _summary_line(coverpoint_rows, testpoint_rows,
                                 bool(measured), case_gates),
    }
