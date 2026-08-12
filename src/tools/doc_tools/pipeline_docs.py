"""
Industrial-Grade Pipeline Documentation System
每个验证阶段输出固定格式的工业级 Markdown 文档。

文档体系:
  前端设计 (de/):
    01_specification.md            — 设计需求规格书
    02_micro_architecture.md       — 微架构设计文档
    03_reference_model.md          — 参考模型规格
    04_interface_specification.md  — 接口控制文档 (ICD)
    05_rtl_signoff.md              — RTL 签核报告
    frontend_design_summary.md     — 前端设计交付总结

  功能验证 (dv/):
    06_verification_plan.md        — 验证计划书
    07_testpoint_decomposition.md  — 测试点分解文档
    08_requirements_traceability.md— 需求追踪矩阵 (RTM)
    09_uvm_environment.md          — UVM 验证环境
    10_assertions.md               — 断言规范
    11_regression_report.md        — 回归测试报告
    12_coverage_analysis.md        — 覆盖率分析报告
    13_quality_review.md           — 质量评审报告
    14_final_signoff.md            — 最终签核报告
    15_verification_closure.md     — 验证收敛报告
    functional_verification_summary.md — 功能验证总结

  总览:
    flow.md                        — 完整流程总览 + RTM 视图
"""

from __future__ import annotations

import json, re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════
# Document Control — 工业级文档元信息
# ═══════════════════════════════════════════════════════════════

def _doc_header(doc_id: str, title: str, version: str = "1.0",
                author: str = "SignOffAI", status: str = "Draft") -> str:
    """工业级文档头部：文档控制信息 + 修订历史"""
    now = datetime.now().strftime("%Y-%m-%d")
    return f"""---
document_id: {doc_id}
title: "{title}"
project: "ALU IP"
version: {version}
date: {now}
author: {author}
status: {status}
---

# {title}

| 项目 | 内容 |
|------|------|
| **文档ID** | `{doc_id}` |
| **版本** | {version} |
| **日期** | {now} |
| **作者** | {author} |
| **状态** | {status} |
| **项目** | ALU IP — 32bit 算术逻辑单元 |

---

## 修订历史

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| {version} | {now} | {author} | 初始版本，由 SignOffAI 管道自动生成 |

---

"""


def _doc_footer(doc_id: str) -> str:
    """工业级文档尾部"""
    return f"""

---

*文档ID: {doc_id} | 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | SignOffAI Pipeline Documentation System*
"""


def _status_badge(status: str) -> str:
    badges = {
        "passed": "✅ **PASS**",
        "degraded": "⚠️ **DEGRADED**",
        "failed": "❌ **FAIL**",
        "skipped": "⏭️ **SKIPPED**",
        "pending": "⏳ **PENDING**",
    }
    return badges.get(status, f"❓ {status.upper()}")


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _safe(d: Any, *keys: str, default: Any = "-") -> Any:
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, default)
        else:
            return default
    return d if d is not None else default


def _parse_json(d: Any) -> Optional[Dict]:
    if isinstance(d, dict):
        return d
    if isinstance(d, str):
        try:
            r = json.loads(d)
            return r if isinstance(r, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass
    return None


def _write_doc(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", errors="replace")
    return path


def _write_csv(path: Path, headers: List[str], rows: List[List[str]]) -> Path:
    """Write CSV file, escaping commas and quotes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    import csv
    with open(str(path), "w", encoding="utf-8", errors="replace", newline="") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)
    return path


# ── CSV Builders ──

def _csv_spec(ctx: dict) -> Optional[Path]:
    """Generate spec CSV from ctx data."""
    data = _parse_json(ctx.get("spec"))
    if not data:
        return None
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "de"

    # Features CSV
    features = data.get("features", []) or []
    if features:
        rows = [[f.get("name","-"), f.get("description","-"), f.get("priority","-")]
                for f in features if isinstance(f, dict)]
        _write_csv(docs_dir / "01_features.csv",
                   ["Feature", "Description", "Priority"], rows)

    # Interfaces CSV
    interfaces = data.get("interfaces", []) or []
    if interfaces:
        rows = [[i.get("name","-"), i.get("type","-"), str(i.get("data_width","-")),
                 i.get("clock","-"), str(len(i.get("signals",[])))]
                for i in interfaces if isinstance(i, dict)]
        _write_csv(docs_dir / "01_interfaces.csv",
                   ["Interface", "Type", "DataWidth", "Clock", "SignalCount"], rows)

    # Registers CSV
    registers = data.get("registers", []) or []
    if registers:
        rows = [[r.get("name","-"), r.get("offset","-"), str(r.get("width","-")),
                 r.get("access","-"), r.get("description","-")]
                for r in registers if isinstance(r, dict)]
        _write_csv(docs_dir / "01_registers.csv",
                   ["Register", "Offset", "Width", "Access", "Description"], rows)

    # Test points CSV
    test_points = data.get("test_points", []) or []
    if test_points:
        rows = []
        for tp in test_points:
            if not isinstance(tp, dict):
                continue
            cat = tp.get("category", "?")
            for t in tp.get("tests", []):
                tn = t.get("name", str(t)) if isinstance(t, dict) else str(t)
                td = t.get("description", "-") if isinstance(t, dict) else "-"
                rows.append([cat, tn, td])
        _write_csv(docs_dir / "01_testpoints.csv",
                   ["Category", "TestName", "Description"], rows)

    return docs_dir


def _csv_design(ctx: dict) -> Optional[Path]:
    """Generate design CSV."""
    data = _parse_json(ctx.get("design_arch"))
    if not data:
        return None
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "de"

    # Signoff checklist CSV
    checklist = data.get("signoff_checklist", []) or []
    if checklist:
        rows = [[c.get("item","-"), c.get("cat", c.get("category","-")), c.get("status","-")]
                for c in checklist if isinstance(c, dict)]
        _write_csv(docs_dir / "02_signoff_checklist.csv",
                   ["CheckItem", "Category", "Status"], rows)

    # Registers CSV (detailed)
    registers = data.get("registers", []) or []
    if registers:
        rows = []
        for r in registers:
            if not isinstance(r, dict):
                continue
            fields = r.get("fields", [])
            fstr = "; ".join(f"{f.get('bits','?')}:{f.get('name','?')}"
                           for f in (fields if isinstance(fields, list) else []))
            rows.append([r.get("name","-"), r.get("offset","-"), str(r.get("width","-")),
                        r.get("access","-"), r.get("reset","-"), r.get("desc","-"), fstr])
        _write_csv(docs_dir / "02_registers.csv",
                   ["Register", "Offset", "Width", "Access", "Reset", "Description", "Fields"], rows)

    return docs_dir


def _csv_vplan(ctx: dict) -> Optional[Path]:
    """Generate verification plan CSV."""
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "dv"

    _write_csv(docs_dir / "04_verification_goals.csv",
               ["GoalID", "Goal", "Priority", "Criteria"],
               [["VGOAL-001", "功能正确性", "P0", "所有功能特性通过 directed + random 测试"],
                ["VGOAL-002", "接口协议合规", "P0", "所有接口协议检查通过"],
                ["VGOAL-003", "寄存器访问", "P0", "所有寄存器读写回环测试通过"],
                ["VGOAL-004", "代码覆盖率", "P1", "Line≥95%, Branch≥90%"],
                ["VGOAL-005", "功能覆盖率", "P1", "所有 covergroup 覆盖点 100%"],
                ["VGOAL-006", "跨时钟域", "P1", "CDC 检查通过"],
                ["VGOAL-007", "性能验证", "P2", "时序满足规格要求"]])

    _write_csv(docs_dir / "04_verification_schedule.csv",
               ["Phase", "Task", "EstimatedDays", "Dependency"],
               [["Phase 1", "Agent 开发与闭环调试", "3", "Spec 冻结"],
                ["Phase 2", "环境集成与编译", "2", "Agent 闭环 PASS"],
                ["Phase 3", "定向测试开发", "3", "环境编译 PASS"],
                ["Phase 4", "随机测试与回归", "5", "定向测试 PASS"],
                ["Phase 5", "覆盖率收敛", "3", "回归环境就绪"],
                ["Phase 6", "签核与报告", "1", "覆盖率达标"],
                ["Total", "", "17", ""]])

    _write_csv(docs_dir / "04_risk_register.csv",
               ["RiskID", "Description", "Impact", "Mitigation"],
               [["RSK-001", "Spec 变更导致环境返工", "高", "模块化 Agent 设计"],
                ["RSK-002", "覆盖率收敛慢", "中", "自动覆盖率驱动测试生成"],
                ["RSK-003", "仿真时间过长", "中", "并行回归 + LSF 调度"],
                ["RSK-004", "参考模型与 RTL 不一致", "低", "Spec 双重审查 + 交叉验证"]])

    return docs_dir


def _csv_tpoint(ctx: dict) -> Optional[Path]:
    """Generate testpoint decomposition CSV — the main one user asked for."""
    data = _parse_json(ctx.get("spec"))
    if not data:
        return None
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "dv"
    test_points = data.get("test_points", []) or []

    rows = []
    tp_id = 0
    for cat_idx, tp in enumerate(test_points, 1):
        if not isinstance(tp, dict):
            continue
        cat = tp.get("category", "?")
        tests = tp.get("tests", [])
        for j, t in enumerate(tests, 1):
            tp_id += 1
            tn = t.get("name", str(t)) if isinstance(t, dict) else str(t)
            td = t.get("description", "-") if isinstance(t, dict) else "-"
            stim = "Random" if "random" in tn.lower() else "Directed"
            check = "Scoreboard" if "flag" not in tn.lower() else "Assertion"
            pri = "P0" if cat_idx <= 2 else "P1" if cat_idx <= 4 else "P2"
            rows.append([f"TP-{tp_id:04d}", cat, tn, td, stim, check, pri,
                        f"VGOAL-{min(cat_idx, 4):03d}"])

    _write_csv(docs_dir / "05_testpoint_decomposition.csv",
               ["TP_ID", "Category", "TestName", "Description",
                "StimulusType", "CheckType", "Priority", "GoalMapping"], rows)
    return docs_dir


def _csv_regress(ctx: dict) -> Optional[Path]:
    """Generate regression report CSV."""
    data = _parse_json(ctx.get("regression"))
    if not data:
        return None
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "dv"
    tests = data.get("tests", []) or []

    rows = [[t.get("name","-"), t.get("status","?"),
             str(t.get("time", t.get("elapsed","-")))]

              for t in tests if isinstance(t, dict)]
    _write_csv(docs_dir / "08_regression_results.csv",
               ["TestName", "Status", "Time"], rows)
    return docs_dir


def _csv_cover(ctx: dict) -> Optional[Path]:
    """Generate coverage CSV."""
    data = _parse_json(ctx.get("coverage"))
    if not data:
        return None
    docs_dir = Path(ctx.get("working_dir", "output")) / "docs" / "dv"

    _write_csv(docs_dir / "09_coverage_summary.csv",
               ["CoverageType", "Value", "Target"],
               [["Line", str(_safe(data, "line_pct", default="-")), "95%"],
                ["Branch", str(_safe(data, "branch_pct", default="-")), "90%"],
                ["Toggle", str(_safe(data, "toggle_pct", default="-")), "85%"]])

    gaps = data.get("gaps", []) or []
    if gaps:
        rows = [[g.get("description", str(g)) if isinstance(g, dict) else str(g)]
                for g in gaps]
        _write_csv(docs_dir / "09_coverage_gaps.csv", ["GapDescription"], rows)

    return docs_dir


# ── CSV dispatch map ──
_CSV_BUILDERS = {
    "spec":    _csv_spec,
    "design":  _csv_design,
    "vplan":   _csv_vplan,
    "tpoint":  _csv_tpoint,
    "regress": _csv_regress,
    "cover":   _csv_cover,
}


# ═══════════════════════════════════════════════════════════════
# Phase Registry — 文档编号、标题、ctx_key、builder
# ═══════════════════════════════════════════════════════════════

# (phase_name, num, title, ctx_key, subdir)
# subdir: "de" = 前端设计  "dv" = 功能验证
PHASE_DOC_SPECS: List[Tuple[str, str, str, Optional[str], str]] = [
    # 前端设计 (de/)
    ("spec",      "01", "设计需求规格书",            "spec",           "de"),
    ("design",    "02", "微架构设计文档",            "design_arch",    "de"),
    ("model",     "03", "参考模型规格",              "model",          "de"),
    ("ifspec",    "04", "接口控制文档",              None,             "de"),
    ("rtlsign",   "05", "RTL签核报告",               None,             "de"),
    # 功能验证 (dv/)
    ("vplan",     "06", "验证计划书",                None,             "dv"),
    ("tpoint",    "07", "测试点分解文档",            None,             "dv"),
    ("rtm",       "08", "需求追踪矩阵",              None,             "dv"),
    ("UVM",       "09", "UVM验证环境",               "env",            "dv"),
    ("assert",    "10", "断言规范",                  "_phase_assert",  "dv"),
    ("regress",   "11", "回归测试报告",              "regression",     "dv"),
    ("cover",     "12", "覆盖率分析报告",            "coverage",       "dv"),
    ("qa",        "13", "质量评审报告",              "_phase_qa",      "dv"),
    ("report",    "14", "最终签核报告",              "_phase_report",  "dv"),
    ("vclose",    "15", "验证收敛报告",              None,             "dv"),
]


# ═══════════════════════════════════════════════════════════════
# Builder Registry
# ═══════════════════════════════════════════════════════════════

_BUILDERS: Dict[str, callable] = {}


def _builder(name: str):
    def deco(fn):
        _BUILDERS[name] = fn
        return fn
    return deco


# ═════════════════════════════════════════════════
# 01 — 设计需求规格书
# ═════════════════════════════════════════════════

@_builder("spec")
def _build_spec(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("spec"))
    if not data:
        return _build_placeholder("01", "设计需求规格书", "SPEC-DOC-001", "Specification phase skipped")

    name = _safe(data, "design_name", default="Unknown")
    ver = _safe(data, "version", default="1.0")
    overview = _safe(data, "overview", default="-")
    features = data.get("features", []) or []
    interfaces = data.get("interfaces", []) or []
    registers = data.get("registers", []) or []
    test_points = data.get("test_points", []) or []
    cov_goals = data.get("coverage_goals", {}) or {}
    va = data.get("verification_architecture", {}) or {}

    out = []
    out.append(_doc_header("SPEC-DOC-001", "设计需求规格书"))

    # 1. 概述
    out.append("## 1. 概述\n")
    out.append(f"**设计名称**: `{name}` | **版本**: {ver}\n")
    out.append(f"**概述**: {overview}\n")

    # 2. 功能特性
    if features:
        out.append("## 2. 功能特性\n")
        out.append("| 编号 | 特性名称 | 描述 | 优先级 |")
        out.append("|------|----------|------|--------|")
        for i, f in enumerate(features, 1):
            fn = f.get("name", "-") if isinstance(f, dict) else str(f)
            fd = f.get("description", "-") if isinstance(f, dict) else "-"
            fp = f.get("priority", "-") if isinstance(f, dict) else "-"
            out.append(f"| FEAT-{i:03d} | {fn} | {fd} | {fp} |")
        out.append("")

    # 3. 接口定义
    if interfaces:
        out.append("## 3. 接口定义\n")
        out.append("| 编号 | 接口名称 | 类型 | 数据宽度 | 时钟域 | 信号数 |")
        out.append("|------|----------|------|----------|--------|--------|")
        for i, iface in enumerate(interfaces, 1):
            if isinstance(iface, dict):
                out.append(f"| IF-{i:03d} | `{iface.get('name','-')}` | {iface.get('type','-')} | "
                          f"{iface.get('data_width','-')} | {iface.get('clock','-')} | "
                          f"{len(iface.get('signals',[]))} |")
        out.append("")

    # 4. 寄存器映射
    if registers:
        out.append("## 4. 寄存器映射\n")
        out.append("| 偏移 | 寄存器名称 | 位宽 | 访问 | 描述 |")
        out.append("|------|------------|------|------|------|")
        for reg in registers:
            if isinstance(reg, dict):
                out.append(f"| {reg.get('offset','-')} | `{reg.get('name','-')}` | "
                          f"{reg.get('width','-')} | {reg.get('access','-')} | "
                          f"{reg.get('description', reg.get('desc','-'))} |")
        out.append("")

    # 5. 测试点概览
    if test_points:
        out.append("## 5. 测试点概览\n")
        total_tests = 0
        for tp in test_points:
            if not isinstance(tp, dict):
                continue
            cat = tp.get("category", "Uncategorized")
            tests = tp.get("tests", [])
            total_tests += len(tests)
            out.append(f"### 5.{test_points.index(tp)+1} {cat}\n")
            out.append("| 编号 | 测试点 | 描述 |")
            out.append("|------|--------|------|")
            for j, t in enumerate(tests, 1):
                tn = t.get("name", str(t)) if isinstance(t, dict) else str(t)
                td = t.get("description", "-") if isinstance(t, dict) else "-"
                out.append(f"| TP-{cat[:4].upper()}-{j:03d} | {tn} | {td} |")
            out.append("")
        out.append(f"**测试点总计**: {total_tests}\n")

    # 6. 覆盖率目标
    if cov_goals:
        out.append("## 6. 覆盖率目标\n")
        if isinstance(cov_goals, dict):
            for k, v in cov_goals.items():
                out.append(f"- **{k}**: {v}")
        out.append("")

    # 7. 验证架构概览
    if va:
        out.append("## 7. 验证架构概览\n")
        if isinstance(va, dict):
            agents = va.get("agents", [])
            out.append(f"- **Agent 数量**: {len(agents) if isinstance(agents, list) else '-'}")
            out.append(f"- **Scoreboard**: {_safe(va, 'scoreboards', default='-')}")
            out.append(f"- **Virtual Sequencer**: {_safe(va, 'virtual_sequencer', default='-')}")
        out.append("")

    out.append(_doc_footer("SPEC-DOC-001"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 02 — 微架构设计文档
# ═══════════════════════════════════════════════════════════════

@_builder("design")
def _build_design(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("design_arch"))
    if not data:
        return _build_placeholder("02", "微架构设计文档", "ARCH-DOC-002", "Design phase skipped")

    module = _safe(data, "module_name", default="Unknown")
    func_hier = data.get("function_hier", {})
    registers = data.get("registers", []) or []
    checklist = data.get("signoff_checklist", []) or []

    out = []
    out.append(_doc_header("ARCH-DOC-002", "微架构设计文档"))

    # 1. 模块概览
    out.append("## 1. 模块概览\n")
    out.append(f"**模块名称**: `{module}`\n")

    # 2. 功能层次结构
    if isinstance(func_hier, dict):
        out.append("## 2. 功能层次结构\n")
        out.append("```")
        out.append(_render_hierarchy(func_hier))
        out.append("```\n")

    # 3. 寄存器详细设计
    if registers:
        out.append("## 3. 寄存器详细设计\n")
        out.append("| 寄存器 | 偏移 | 位宽 | 访问 | 复位值 | 描述 | 位域 |")
        out.append("|--------|------|------|------|--------|------|------|")
        for reg in registers:
            if isinstance(reg, dict):
                fields = reg.get("fields", [])
                fstr = ", ".join(
                    f"[{f.get('bits','?')}] {f.get('name','?')}"
                    for f in (fields if isinstance(fields, list) else [])
                )
                out.append(f"| `{reg.get('name','-')}` | {reg.get('offset','-')} | "
                          f"{reg.get('width','-')} | {reg.get('access','-')} | "
                          f"{reg.get('reset','-')} | {reg.get('desc','-')} | {fstr or '-'} |")
        out.append("")

    # 4. 签核检查清单
    if checklist:
        out.append("## 4. 签核检查清单\n")
        out.append("| 编号 | 检查项 | 分类 | 状态 |")
        out.append("|------|--------|------|------|")
        for i, item in enumerate(checklist, 1):
            if isinstance(item, dict):
                out.append(f"| CHK-{i:03d} | {item.get('item','-')} | "
                          f"{item.get('cat', item.get('category','-'))} | "
                          f"`{item.get('status','pending')}` |")
        out.append("")

    out.append(_doc_footer("ARCH-DOC-002"))
    return "\n".join(out)


def _render_hierarchy(node: dict, indent: int = 0) -> str:
    if not isinstance(node, dict):
        return ""
    prefix = "    " * indent
    name = node.get("name", "?")
    result = f"{prefix}├── {name}\n"
    for child in node.get("children", []):
        result += _render_hierarchy(child, indent + 1)
    return result


# ═══════════════════════════════════════════════════════════════
# 03 — 参考模型规格
# ═══════════════════════════════════════════════════════════════

@_builder("model")
def _build_model(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("model"))
    if not data:
        return _build_placeholder("03", "参考模型规格", "REFM-DOC-003", "Model phase skipped")

    module = _safe(data, "module", default=_safe(data, "module_name", default="Unknown"))
    mtype = _safe(data, "model_type", default="-")
    analysis = _parse_json(data.get("analysis", {})) or {}
    ref_model = _parse_json(data.get("ref_model", {})) or {}
    test_vectors = _parse_json(data.get("test_vectors", {})) or {}
    files = data.get("files", {}) or {}

    out = []
    out.append(_doc_header("REFM-DOC-003", "参考模型规格"))

    # 1. 模型概览
    out.append("## 1. 模型概览\n")
    out.append(f"| 属性 | 值 |")
    out.append(f"|------|-----|")
    out.append(f"| 模块 | `{module}` |")
    out.append(f"| 模型类型 | {mtype} |")
    out.append(f"| 寄存器数 | {_safe(ref_model, 'register_count', default='-')} |")
    out.append(f"| 操作数 | {_safe(ref_model, 'operation_count', default='-')} |")
    out.append("")

    # 2. 模型文件
    if files:
        out.append("## 2. 模型文件\n")
        if isinstance(files, dict):
            for k, v in files.items():
                out.append(f"- **{k}**: `{v}`")
        out.append("")

    # 3. 设计分析
    if analysis:
        out.append("## 3. 设计分析\n")
        out.append("| 项目 | 值 |")
        out.append("|------|-----|")
        for k in ("registers", "operations", "module_name", "input_signals", "output_signals"):
            v = analysis.get(k, "-")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            out.append(f"| {k.replace('_', ' ').title()} | {v} |")
        out.append("")

    # 4. 测试向量
    if test_vectors:
        out.append("## 4. 测试向量\n")
        out.append(f"- **测试数量**: {_safe(test_vectors, 'test_count', default='-')}")
        tc = _safe(test_vectors, "test_code", default="")
        if tc and tc != "-":
            out.append("\n```cpp")
            out.append(str(tc)[:2000])
            out.append("```")
        out.append("")

    out.append(_doc_footer("REFM-DOC-003"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 04 — 验证计划书 (NEW)
# ═══════════════════════════════════════════════════════════════

@_builder("vplan")
def _build_verification_plan(ctx: dict, ps: dict) -> str:
    """从 spec + design_arch 数据生成验证计划书"""
    spec = _parse_json(ctx.get("spec")) or {}
    design = _parse_json(ctx.get("design_arch")) or {}

    features = spec.get("features", []) or []
    interfaces = spec.get("interfaces", []) or []
    registers = spec.get("registers", []) or design.get("registers", []) or []
    test_points = spec.get("test_points", []) or []
    cov_goals = spec.get("coverage_goals", {}) or {}

    # 统计
    n_features = len(features)
    n_regs = len(registers)
    n_tp = sum(len(tp.get("tests", [])) for tp in test_points if isinstance(tp, dict))

    out = []
    out.append(_doc_header("VPLAN-DOC-006", "验证计划书", status="Review"))

    # 1. 验证目标
    out.append("## 1. 验证目标\n")
    out.append(f"本验证计划针对 **{_safe(spec, 'design_name', default='DUT')}** 模块，覆盖以下验证目标：\n")
    out.append("| 目标编号 | 验证目标 | 优先级 | 验收标准 |")
    out.append("|----------|----------|--------|----------|")
    goals = [
        ("VGOAL-001", "功能正确性", "P0", "所有功能特性通过 directed + random 测试"),
        ("VGOAL-002", "接口协议合规", "P0", "所有接口协议检查通过，无 protocol violation"),
        ("VGOAL-003", "寄存器访问", "P0", "所有寄存器读写回环测试通过"),
        ("VGOAL-004", "代码覆盖率", "P1", f"Line≥{_safe(cov_goals,'line',default='95')}%, Branch≥{_safe(cov_goals,'branch',default='90')}%"),
        ("VGOAL-005", "功能覆盖率", "P1", "所有 covergroup 覆盖点达到 100%"),
        ("VGOAL-006", "跨时钟域", "P1", "CDC 检查通过"),
        ("VGOAL-007", "性能验证", "P2", f"时序满足 {_safe(spec,'design_name')} 规格要求"),
    ]
    for g in goals:
        out.append(f"| {g[0]} | {g[1]} | {g[2]} | {g[3]} |")
    out.append("")

    # 2. 验证策略
    out.append("## 2. 验证策略\n")
    out.append("### 2.1 验证层次\n")
    out.append("| 层次 | 范围 | 方法 | 工具 |")
    out.append("|------|------|------|------|")
    out.append("| **Agent 闭环** | 单个接口 Agent | Driver→Monitor 自发自收 | QuestaSim + UVM")
    out.append("| **模块级** | 单个模块 | 约束随机 + 定向测试 | QuestaSim + UVM")
    out.append("| **子系统级** | 多模块集成 | Scoreboard + Reference Model | QuestaSim + UVM")
    out.append("")

    out.append("### 2.2 验证方法学\n")
    out.append("- **方法学**: UVM (Universal Verification Methodology)")
    out.append("- **激励生成**: 约束随机 (constrained-random) + 定向 (directed)")
    out.append("- **结果检查**: Scoreboard 自动比对 + Reference Model 预测")
    out.append("- **覆盖率驱动**: Covergroup + Coverpoint + Cross Coverage")
    out.append("")

    # 3. 验证环境架构
    out.append("## 3. 验证环境架构\n")
    out.append("```")
    out.append("                        ┌──────────────┐")
    out.append("                        │  Virtual     │")
    out.append("                        │  Sequencer   │")
    out.append("                        └──────┬───────┘")
    out.append("                               │")
    out.append("          ┌────────────────────┼────────────────────┐")
    out.append("          │                    │                    │")
    out.append("    ┌─────▼─────┐       ┌─────▼─────┐       ┌─────▼─────┐")
    out.append("    │ Agent In  │       │   DUT     │       │ Agent Out │")
    out.append("    │ ┌───────┐ │       │           │       │ ┌───────┐ │")
    out.append("    │ │Driver │─┼──────►│   ALU IP  ├───────►│ │Monitor│ │")
    out.append("    │ │Monitor│◄┼───────┤           │◄───────┤ │Driver │ │")
    out.append("    │ └───────┘ │       │           │       │ └───────┘ │")
    out.append("    └─────┬─────┘       └───────────┘       └─────┬─────┘")
    out.append("          │                                       │")
    out.append("    ┌─────▼───────────────────────────────────────▼─────┐")
    out.append("    │                  Scoreboard                       │")
    out.append("    │         (Expected vs Actual + Ref Model)          │")
    out.append("    └──────────────────────────────────────────────────┘")
    out.append("```\n")

    # 4. 验证资源与排期
    out.append("## 4. 验证资源与排期\n")
    out.append("| 阶段 | 任务 | 预计工时 | 依赖 |")
    out.append("|------|------|----------|------|")
    out.append("| Phase 1 | Agent 开发与闭环调试 | 3天 | Spec 冻结 |")
    out.append("| Phase 2 | 环境集成与编译 | 2天 | Agent 闭环 PASS |")
    out.append("| Phase 3 | 定向测试开发 | 3天 | 环境编译 PASS |")
    out.append("| Phase 4 | 随机测试与回归 | 5天 | 定向测试 PASS |")
    out.append("| Phase 5 | 覆盖率收敛 | 3天 | 回归环境就绪 |")
    out.append("| Phase 6 | 签核与报告 | 1天 | 覆盖率达标 |")
    out.append(f"| **总计** | | **17天** | |")
    out.append("")

    # 5. 风险与缓解
    out.append("## 5. 风险与缓解\n")
    out.append("| 风险编号 | 风险描述 | 影响 | 缓解措施 |")
    out.append("|----------|----------|------|----------|")
    risks = [
        ("RSK-001", "Spec 变更导致环境返工", "高", "模块化 Agent 设计，接口参数化"),
        ("RSK-002", "覆盖率收敛慢", "中", "自动覆盖率驱动的测试生成"),
        ("RSK-003", "仿真时间过长", "中", "并行回归 + LSF 调度"),
        ("RSK-004", "参考模型与 RTL 不一致", "低", "Spec 双重审查 + 交叉验证"),
    ]
    for r in risks:
        out.append(f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} |")
    out.append("")

    out.append(_doc_footer("VPLAN-DOC-006"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 05 — 测试点分解文档 (NEW)
# ═══════════════════════════════════════════════════════════════

@_builder("tpoint")
def _build_testpoint_decomp(ctx: dict, ps: dict) -> str:
    """从 spec test_points 生成详细的测试点分解文档"""
    spec = _parse_json(ctx.get("spec")) or {}
    test_points = spec.get("test_points", []) or []
    features = spec.get("features", []) or []
    design = _parse_json(ctx.get("design_arch")) or {}
    func_hier = design.get("function_hier", {})

    out = []
    out.append(_doc_header("TPOINT-DOC-007", "测试点分解文档", status="Review"))

    # 1. 概述
    total = sum(len(tp.get("tests", [])) for tp in test_points if isinstance(tp, dict))
    out.append("## 1. 概述\n")
    out.append(f"本文档将 {_safe(spec, 'design_name', default='DUT')} 模块的验证需求分解为可执行的测试点。\n")
    out.append(f"- **测试点总计**: {total}")
    out.append(f"- **测试分类**: {len(test_points)} 个类别")
    out.append(f"- **功能特性**: {len(features)} 个")
    out.append("")

    # 2. 功能覆盖率交叉矩阵
    out.append("## 2. 功能覆盖率交叉矩阵\n")
    out.append("将测试点与功能特性、接口进行交叉映射，确保全覆盖。\n")
    out.append("| 测试类别 | 特性覆盖 | 接口覆盖 | 优先级 |")
    out.append("|----------|----------|----------|--------|")
    feature_names = [f.get("name", str(f))[:20] for f in features[:6]] if features else ["-"]
    for tp in test_points:
        if not isinstance(tp, dict):
            continue
        cat = tp.get("category", "?")
        tests = tp.get("tests", [])
        out.append(f"| {cat} | {', '.join(feature_names[:2])} | "
                  f"{_safe(spec, 'interfaces', 0, 'name', default='-')} | "
                  f"P{test_points.index(tp) if 0 <= test_points.index(tp) <= 2 else '1'} |")
    out.append("")

    # 3. 逐类测试点分解
    out.append("## 3. 测试点详细分解\n")
    tp_counter = 0
    for cat_idx, tp in enumerate(test_points, 1):
        if not isinstance(tp, dict):
            continue
        cat = tp.get("category", "Uncategorized")
        tests = tp.get("tests", [])

        out.append(f"### 3.{cat_idx} {cat}\n")
        out.append(f"**类别描述**: {cat} 相关功能验证\n")
        out.append("| TP编号 | 测试点名称 | 描述 | 激励类型 | 检查类型 | 优先级 |")
        out.append("|--------|------------|------|----------|----------|--------|")

        for j, t in enumerate(tests, 1):
            tp_counter += 1
            tn = t.get("name", str(t)) if isinstance(t, dict) else str(t)
            td = t.get("description", "-") if isinstance(t, dict) else "-"
            stim = "Random" if "random" in tn.lower() else "Directed"
            check = "Scoreboard" if "flag" not in tn.lower() else "Assertion"
            pri = "P0" if cat_idx <= 2 else "P1" if cat_idx <= 4 else "P2"
            out.append(f"| TP-{tp_counter:04d} | {tn} | {td} | {stim} | {check} | {pri} |")
        out.append("")

    # 4. 测试点与验证目标映射
    out.append("## 4. 测试点→验证目标映射\n")
    out.append("| 验证目标 | 覆盖测试点 | 覆盖状态 |")
    out.append("|----------|------------|----------|")
    vgoals = [
        ("VGOAL-001 功能正确性", f"TP-0001 ~ TP-{tp_counter:04d}", "待验证"),
        ("VGOAL-002 接口协议合规", "APB/Native 接口测试点", "待验证"),
        ("VGOAL-003 寄存器访问", "寄存器读写测试点", "待验证"),
        ("VGOAL-004 代码覆盖率", "全部 directed + random", "待收集"),
        ("VGOAL-005 功能覆盖率", "Cross-coverage 检查", "待收集"),
    ]
    for vg in vgoals:
        out.append(f"| {vg[0]} | {vg[1]} | {vg[2]} |")
    out.append("")

    out.append(_doc_footer("TPOINT-DOC-007"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 06 — UVM 验证环境
# ═══════════════════════════════════════════════════════════════

@_builder("UVM")
def _build_env(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("env"))
    if not data:
        return _build_placeholder("06", "UVM验证环境", "UVM-DOC-006", "UVM phase skipped")

    env_name = _safe(data, "env_name", default="Unknown")
    from src.core.output_config import make_output_root
    output_dir = _safe(data, "output_dir", default=make_output_root())
    agent_count = _safe(data, "agent_count", default="-")
    filelist = _safe(data, "filelist", default="-")
    files = data.get("files", []) or []

    out = []
    out.append(_doc_header("UVM-DOC-009", "UVM验证环境"))

    # 1. 环境概览
    out.append("## 1. 环境概览\n")
    out.append(f"| 属性 | 值 |")
    out.append(f"|------|-----|")
    out.append(f"| 环境名称 | `{env_name}` |")
    out.append(f"| Agent 数量 | {agent_count} |")
    out.append(f"| 输出目录 | `{output_dir}` |")
    out.append("")

    # 2. 组件清单
    out.append("## 2. UVM 组件清单\n")
    agent_dir = Path(output_dir) / "agents"
    out.append("| Agent | Interface | 类型 | Transaction Fields |")
    out.append("|-------|-----------|------|--------------------|")
    if agent_dir.exists():
        for ad in sorted(agent_dir.iterdir()):
            if ad.is_dir():
                txn_file = ad / f"{ad.name}_transaction.sv"
                txn_fields = []
                if txn_file.exists():
                    txt = txn_file.read_text(encoding="utf-8", errors="replace")
                    txn_fields = re.findall(r'rand\s+\S+\s+(\w+)\s*;', txt)
                tfn = ", ".join(f"`{x}`" for x in txn_fields) if txn_fields else "-"
                agent_yml = ad / f"{ad.name}_agent.sv"
                is_active = "PASSIVE"
                if agent_yml.exists():
                    atxt = agent_yml.read_text(encoding="utf-8", errors="replace")
                    if "UVM_ACTIVE" in atxt:
                        is_active = "ACTIVE"
                out.append(f"| {ad.name} | `{ad.name}_interface` | {is_active} | {tfn} |")
    out.append("")

    # 3. 编译配置
    out.append("## 3. 编译配置\n")
    out.append(f"- **Filelist**: `{filelist}`")
    out.append(f"- **编译库**: `{output_dir}/build/work/`")
    out.append(f"- **仿真日志**: `{output_dir}/sim/agent/`")
    out.append(f"- **波形文件**: `{output_dir}/sim/agent/wave_*.wlf`")
    out.append("")

    # 4. Agent 文件清单
    if files:
        out.append("## 4. 生成文件清单\n")
        out.append("| 文件 | 描述 |")
        out.append("|------|------|")
        for f in files[:30]:
            out.append(f"| `{f}` | - |")
        if len(files) > 30:
            out.append(f"| ... | +{len(files)-30} more files |")
        out.append("")

    # 5. 质量检查
    qp = Path(output_dir) / "quality_report.json"
    if qp.exists():
        try:
            quality = json.loads(qp.read_text(encoding="utf-8", errors="replace"))
        except (json.JSONDecodeError, OSError):
            quality = {}
    else:
        quality = {}

    if quality:
        out.append("## 5. 质量检查结果\n")
        out.append("| 检查项 | 状态 | 详情 |")
        out.append("|--------|------|------|")
        details = quality.get("details", {})
        static = details.get("static", {})
        compile_ = details.get("compile", {})
        loopback = details.get("loopback", {})

        sp = "✅ PASS" if static.get("passed") else "❌ FAIL"
        out.append(f"| **静态检查** | {sp} | {static.get('present','?')} present, {static.get('missing','?')} missing |")

        cp = "✅ PASS" if compile_.get("passed") else "❌ FAIL"
        out.append(f"| **编译检查** | {cp} | {compile_.get('errors','?')} errors |")

        lp = "✅ PASS" if loopback.get("passed") else "❌ FAIL"
        lb_agents = loopback.get("agents", [])
        lb_detail = "; ".join(
            f"{a.get('agent','?')}: matched={a.get('matched',0)}"
            for a in (lb_agents if isinstance(lb_agents, list) else [])[:4]
        )
        out.append(f"| **闭环测试** | {lp} | {lb_detail or '-'} |")

        out.append(f"\n**综合评级**: {quality.get('grade','?')} | **判定**: {quality.get('verdict','?')}\n")

    out.append(_doc_footer("UVM-DOC-009"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 07 — 断言规范
# ═══════════════════════════════════════════════════════════════

@_builder("assert")
def _build_assert(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("_phase_assert"))
    if not data:
        return _build_placeholder("07", "断言规范", "ASRT-DOC-007", "Assertion phase skipped")

    design = _safe(data, "design_name", default="-")
    clk = _safe(data, "clock_signal", default="clk")
    rst = _safe(data, "reset_signal", default="rst")
    assertions = data.get("assertions", []) or []

    out = []
    out.append(_doc_header("ASRT-DOC-010", "断言规范"))

    out.append("## 1. 断言概述\n")
    out.append(f"| 属性 | 值 |")
    out.append(f"|------|-----|")
    out.append(f"| 设计模块 | `{design}` |")
    out.append(f"| 时钟 | `{clk}` |")
    out.append(f"| 复位 | `{rst}` |")
    out.append(f"| 断言数量 | {len(assertions)} |")
    out.append("")

    if assertions:
        out.append("## 2. 断言属性清单\n")
        out.append("| 编号 | 类型 | 属性名 | 严重级别 | 描述 |")
        out.append("|------|------|--------|----------|------|")
        for i, a in enumerate(assertions, 1):
            if isinstance(a, dict):
                out.append(f"| AST-{i:03d} | {a.get('type','-')} | "
                          f"`{a.get('property_name','-')}` | "
                          f"**{a.get('severity','-')}** | "
                          f"{a.get('message', a.get('description','-'))} |")
        out.append("")

        # SVA code blocks
        out.append("## 3. SVA 代码\n")
        for i, a in enumerate(assertions, 1):
            if isinstance(a, dict) and a.get("property"):
                out.append(f"### 3.{i} {a.get('property_name', f'Assertion-{i}')}\n")
                out.append("```systemverilog")
                out.append(str(a["property"])[:2000])
                out.append("```\n")

    out.append(_doc_footer("ASRT-DOC-010"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 08 — 回归测试报告
# ═══════════════════════════════════════════════════════════════

@_builder("regress")
def _build_regress(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("regression"))
    if not data:
        return _build_placeholder("08", "回归测试报告", "REGR-DOC-008", "Regression phase skipped")

    passed = int(_safe(data, "passed", default=0))
    failed = int(_safe(data, "failed", default=0))
    total = int(_safe(data, "total", default=0))
    compile_status = _safe(data, "compile_status", default=_safe(data, "compile", default="-"))
    tests = data.get("tests", []) or []

    try:
        pr = float(_safe(data, "pass_rate", default="0").replace("%", ""))
    except ValueError:
        pr = (passed / total * 100) if total > 0 else 0

    out = []
    out.append(_doc_header("REGR-DOC-011", "回归测试报告"))

    # 1. 回归摘要
    out.append("## 1. 回归摘要\n")
    out.append("| 指标 | 值 |")
    out.append("|------|-----|")
    out.append(f"| 编译状态 | {compile_status} |")
    out.append(f"| 总测试数 | {total} |")
    out.append(f"| 通过 | {passed} |")
    out.append(f"| 失败 | {failed} |")
    out.append(f"| 通过率 | **{pr:.1f}%** |")
    out.append("")

    # 2. 通过率可视化
    out.append("## 2. 通过率\n")
    bar_len = 30
    filled = int(pr / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    out.append(f"```")
    out.append(f"{bar} {pr:.1f}%")
    out.append(f"```\n")

    # 3. 测试结果明细
    if tests:
        out.append("## 3. 测试结果明细\n")
        out.append("| 编号 | 测试名称 | 状态 | 耗时 |")
        out.append("|------|----------|------|------|")
        for i, t in enumerate(tests, 1):
            if isinstance(t, dict):
                st = t.get("status", "?")
                icon = "✅" if st == "PASS" else "❌" if st == "FAIL" else "⚠️"
                out.append(f"| T-{i:03d} | {t.get('name','-')} | {icon} {st} | "
                          f"{t.get('time', t.get('elapsed','-'))} |")
        out.append("")

    out.append(_doc_footer("REGR-DOC-011"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 09 — 覆盖率分析报告
# ═══════════════════════════════════════════════════════════════

@_builder("cover")
def _build_cover(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("coverage"))
    if not data:
        return _build_placeholder("09", "覆盖率分析报告", "COV-DOC-009", "Coverage phase skipped")

    line_pct = _safe(data, "line_pct", default="-")
    branch_pct = _safe(data, "branch_pct", default="-")
    toggle_pct = _safe(data, "toggle_pct", default="-")
    gaps = data.get("gaps", []) or []
    suggestions = data.get("suggestions", []) or []

    def _bar(pct):
        try:
            v = float(pct)
        except (ValueError, TypeError):
            v = 0
        b = 20
        f = int(v / 100 * b)
        return f"`{'█'*f}{'░'*(b-f)}` **{v:.1f}%**"

    out = []
    out.append(_doc_header("COV-DOC-012", "覆盖率分析报告"))

    out.append("## 1. 覆盖率摘要\n")
    out.append("| 覆盖率类型 | 覆盖率 | 目标 | 状态 |")
    out.append("|------------|--------|------|------|")
    for label, key, target in [("行覆盖率", "line_pct", "95%"), ("分支覆盖率", "branch_pct", "90%"), ("翻转覆盖率", "toggle_pct", "85%")]:
        pct = _safe(data, key, default="-")
        try:
            v = float(pct)
            st = "✅" if v >= float(target.replace("%","")) else "❌"
        except (ValueError, TypeError):
            v = 0
            st = "⏳"
        out.append(f"| {label} | {_bar(pct)} | {target} | {st} |")
    out.append("")

    if gaps:
        out.append("## 2. 覆盖率缺口\n")
        out.append("| 编号 | 缺口描述 |")
        out.append("|------|----------|")
        for i, g in enumerate(gaps, 1):
            desc = g.get("description", str(g)) if isinstance(g, dict) else str(g)
            out.append(f"| GAP-{i:03d} | {desc} |")
        out.append("")

    if suggestions:
        out.append("## 3. 改进建议\n")
        for i, s in enumerate(suggestions, 1):
            if isinstance(s, dict):
                out.append(f"{i}. **{s.get('type','')}**: {s.get('description', str(s))}")
            else:
                out.append(f"{i}. {s}")
        out.append("")

    out.append(_doc_footer("COV-DOC-012"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 10 — 质量评审报告
# ═══════════════════════════════════════════════════════════════

@_builder("qa")
def _build_qa(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("_phase_qa"))
    if not data:
        return _build_placeholder("10", "质量评审报告", "QA-DOC-010", "QA phase skipped")

    score = _safe(data, "overall_score", default="?")
    issues = data.get("issues", []) or []
    best_practices = data.get("best_practices", []) or []
    verdict = _safe(data, "verdict", default="?")

    try:
        s = int(score)
    except (ValueError, TypeError):
        s = 0

    verdict_icon = {"READY": "✅", "NEEDS_FIX": "⚠️", "FAILED": "❌"}.get(str(verdict).upper(), "❓")

    out = []
    out.append(_doc_header("QA-DOC-013", "质量评审报告"))

    out.append("## 1. 评审结论\n")
    out.append("| 指标 | 值 |")
    out.append("|------|-----|")
    out.append(f"| 综合评分 | **{score}/100** |")
    out.append(f"| 判定 | {verdict_icon} **{verdict}** |")
    out.append("")

    # Score bar
    bar_len = 30
    filled = int(s / 100 * bar_len)
    bar = "█" * filled + "░" * (bar_len - filled)
    out.append(f"```")
    out.append(f"{bar} {score}/100")
    out.append(f"```\n")

    if issues:
        out.append("## 2. 问题清单\n")
        out.append("| 编号 | 严重级别 | 描述 |")
        out.append("|------|----------|------|")
        for i, issue in enumerate(issues, 1):
            if isinstance(issue, dict):
                sev = issue.get("severity", "info").upper()
                si = "🔴" if sev == "ERROR" else "🟡" if sev == "WARNING" else "🔵"
                out.append(f"| ISS-{i:03d} | {si} {sev} | {issue.get('message','-')} |")
        out.append("")

    if best_practices:
        out.append("## 3. 最佳实践\n")
        for i, bp in enumerate(best_practices, 1):
            if isinstance(bp, dict):
                out.append(f"{i}. **{bp.get('title', bp.get('name',''))}**: {bp.get('description', str(bp))}")
            else:
                out.append(f"{i}. {bp}")
        out.append("")

    out.append(_doc_footer("QA-DOC-013"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# 11 — 最终签核报告
# ═══════════════════════════════════════════════════════════════

@_builder("report")
def _build_report(ctx: dict, ps: dict) -> str:
    data = _parse_json(ctx.get("_phase_report")) or _parse_json(ctx.get("report"))
    if not data:
        return _build_placeholder("11", "最终签核报告", "SIGN-DOC-011", "Report phase skipped")

    reports = data.get("reports", {}) or {}
    signoff = data.get("signoff", {}) or {}
    summary = data.get("summary", {}) or {}
    verdict = _safe(data, "verdict", default="?")

    ss = _safe(signoff, "status", default="-")
    si = "✅" if "APPROVED" in str(ss).upper() else "⚠️" if "CONDITIONAL" in str(ss).upper() else "❌"

    out = []
    out.append(_doc_header("SIGN-DOC-014", "最终签核报告", status=str(ss)))

    out.append("## 1. 签核结论\n")
    out.append("| 项目 | 结论 |")
    out.append("|------|------|")
    out.append(f"| 签核状态 | {si} **{ss}** |")
    out.append(f"| 最终判定 | **{verdict}** |")
    out.append("")

    if summary:
        out.append("## 2. 测试摘要\n")
        out.append("| 指标 | 值 |")
        out.append("|------|-----|")
        out.append(f"| 总测试数 | {_safe(summary, 'total_tests', default='-')} |")
        out.append(f"| 通过 | {_safe(summary, 'passed', default='-')} |")
        out.append(f"| 失败 | {_safe(summary, 'failed', default='-')} |")
        out.append(f"| 通过率 | **{_safe(summary, 'pass_rate', default='-')}** |")
        out.append("")

    if reports:
        out.append("## 3. 交付物\n")
        if isinstance(reports, dict):
            for k, v in reports.items():
                out.append(f"- **{k}**: `{v}`")
        out.append("")

    out.append(_doc_footer("SIGN-DOC-014"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# DE-04 — 接口控制文档 (ICD)
# ═══════════════════════════════════════════════════════════════

@_builder("ifspec")
def _build_interface_spec(ctx: dict, ps: dict) -> str:
    spec = _parse_json(ctx.get("spec")) or {}
    design = _parse_json(ctx.get("design_arch")) or {}
    interfaces = spec.get("interfaces", []) or []

    out = []
    out.append(_doc_header("ICD-DOC-004", "接口控制文档 (ICD)", status="Review"))

    out.append("## 1. 概述\n")
    out.append(f"本文档定义 **{_safe(spec, 'design_name', default='DUT')}** 的所有外部接口，供前端设计(DE)和功能验证(DV)共同使用。\n")

    if interfaces:
        out.append("## 2. 接口清单\n")
        out.append("| 接口名 | 类型 | 数据宽度 | 时钟 | 方向 | 描述 |")
        out.append("|--------|------|----------|------|------|------|")
        for iface in interfaces:
            if isinstance(iface, dict):
                sigs = iface.get("signals", [])
                out.append(f"| `{iface.get('name','-')}` | {iface.get('type','-')} | "
                          f"{iface.get('data_width','-')} | {iface.get('clock','-')} | "
                          f"In/Out | {len(sigs)} signals |")
        out.append("")

    # Timing diagram placeholder
    out.append("## 3. 接口时序\n")
    out.append("```")
    out.append("         ┌───┐   ┌───┐   ┌───┐")
    out.append("  clk    │   │   │   │   │   │")
    out.append("       ──┘   └───┘   └───┘   └──")
    out.append("         ┌───────────┐")
    out.append("  valid  │           │")
    out.append("       ──┘           └──────────")
    out.append("         ┌───────────┐")
    out.append("  data   │XXXXXXXXXXX│")
    out.append("       ──┘           └──────────")
    out.append("                 ┌───┐")
    out.append("  ready          │   │")
    out.append("       ──────────┘   └──────────")
    out.append("```\n")

    # Signal mapping — derived from actual spec interfaces
    out.append("## 4. 信号映射 (DE ↔ DV)\n")
    out.append("| 信号名 | DE 端口 | DV Interface | 位宽 | 方向(DE) | 方向(DV) |")
    out.append("|--------|---------|-------------|------|----------|----------|")
    seen = set()
    for iface in interfaces:
        if not isinstance(iface, dict):
            continue
        ifname = iface.get("name", "?")
        for sig in iface.get("signals", []):
            sn = str(sig) if not isinstance(sig, dict) else sig.get("name", str(sig))
            if sn in seen:
                continue
            seen.add(sn)
            dw = iface.get("data_width", 1)
            direction = "input" if sn in ("clk", "rst", "rst_n", "ready") else "output"
            out.append(f"| {sn} | {sn} | vif.{sn} | {dw} | {direction} | {'input' if direction == 'output' else 'output'} |")
    if not seen:
        out.append("| *待从 spec 生成* | - | - | - | - | - |")
    out.append("")

    out.append(_doc_footer("ICD-DOC-004"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# DE-05 — RTL 签核报告
# ═══════════════════════════════════════════════════════════════

@_builder("rtlsign")
def _build_rtl_signoff(ctx: dict, ps: dict) -> str:
    design = _parse_json(ctx.get("design_arch")) or {}
    spec = _parse_json(ctx.get("spec")) or {}

    out = []
    out.append(_doc_header("RTL-DOC-005", "RTL 签核报告", status="Review"))

    out.append("## 1. RTL 质量检查\n")
    out.append("| 检查项 | 工具 | 状态 | 结果 |")
    out.append("|--------|------|------|------|")
    checks = [
        ("Lint (设计规则检查)", "SpyGlass / Verilator", "⏳", "待运行"),
        ("CDC (跨时钟域检查)", "SpyGlass CDC", "⏳", "待运行"),
        ("RDC (复位域检查)", "SpyGlass RDC", "⏳", "待运行"),
        ("Synthesis (综合)", "Design Compiler", "⏳", "待运行"),
        ("Formal Equiv (形式验证)", "Formality", "⏳", "待运行"),
        ("STA (静态时序分析)", "PrimeTime", "⏳", "待运行"),
    ]
    for c in checks:
        out.append(f"| {c[0]} | {c[1]} | {c[2]} | {c[3]} |")
    out.append("")

    out.append("## 2. 设计参数\n")
    out.append(f"- **模块名称**: `{_safe(design, 'module_name', default='-')}`")
    out.append(f"- **设计名称**: `{_safe(spec, 'design_name', default='-')}`")
    features = spec.get("features", []) or []
    regs = design.get("registers", spec.get("registers", [])) or []
    out.append(f"- **功能特性**: {len(features)} 项")
    out.append(f"- **寄存器数量**: {len(regs)} 个")
    out.append("")

    # Signoff checklist from design
    checklist = design.get("signoff_checklist", []) or []
    if checklist:
        out.append("## 3. 功能签核清单\n")
        out.append("| 编号 | 检查项 | 分类 | 状态 |")
        out.append("|------|--------|------|------|")
        for i, c in enumerate(checklist, 1):
            if isinstance(c, dict):
                st = c.get("status", "pending")
                icon = "✅" if st == "passed" else "⏳" if st == "pending" else "❌"
                out.append(f"| CHK-{i:03d} | {c.get('item','-')} | "
                          f"{c.get('cat', c.get('category','-'))} | {icon} {st} |")
        out.append("")

    out.append("## 4. 交付物\n")
    out.append("| 文件 | 类型 | 状态 |")
    out.append("|------|------|------|")
    out.append("| `rtl/alu_core.v`      | RTL (Verilog)  | ⏳ |")
    out.append("| `rtl/alu_apb_if.v`    | RTL (Verilog)  | ⏳ |")
    out.append("| `rtl/alu_top.v`       | RTL (Verilog)  | ⏳ |")
    out.append("| `constraints/alu.sdc` | SDC Constraints| ⏳ |")
    out.append("")

    out.append(_doc_footer("RTL-DOC-005"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# DV-08 — 需求追踪矩阵 (RTM)
# ═══════════════════════════════════════════════════════════════

@_builder("rtm")
def _build_rtm(ctx: dict, ps: dict) -> str:
    spec = _parse_json(ctx.get("spec")) or {}
    design = _parse_json(ctx.get("design_arch")) or {}
    features = spec.get("features", []) or []
    test_points = spec.get("test_points", []) or []

    out = []
    out.append(_doc_header("RTM-DOC-008", "需求追踪矩阵 (RTM)", status="Review"))

    out.append("## 1. 概述\n")
    out.append("本文档建立从 **需求 → 设计 → 测试点 → 覆盖率** 的完整追踪链。\n")
    out.append(f"- **需求数**: {len(features)} | **测试点数**: {sum(len(tp.get('tests',[])) for tp in test_points if isinstance(tp,dict))}")
    out.append("")

    # Read actual coverage + regression data (docs runs AFTER regress_cov)
    cov_data = _parse_json(ctx.get("coverage")) or {}
    reg_data = _parse_json(ctx.get("regression")) or {}

    def _cov_badge(pct, target):
        try:
            v = float(str(pct).replace("%",""))
            t = float(str(target).replace("%",""))
            return f"{v:.1f}% ✅" if v >= t else f"{v:.1f}% ❌"
        except (ValueError, TypeError):
            return "⏳"

    # Main RTM table
    out.append("## 2. 需求追踪矩阵\n")
    out.append("| REQ-ID | 需求 | 设计模块 | 测试点 | 覆盖率 | 状态 |")
    out.append("|--------|------|----------|--------|--------|------|")

    # 从 regress_cov 获取真实 pass/fail
    test_results = reg_data.get("tests", []) or []
    test_status_map = {}
    for t in test_results:
        if isinstance(t, dict):
            test_status_map[t.get("name", "")] = t.get("status", "⏳")

    tp_counter = 0
    for feat_idx, feat in enumerate(features, 1):
        if not isinstance(feat, dict):
            continue
        fn = feat.get("name", str(feat))
        fd = feat.get("description", "-")
        matching_tps = []
        tp_statuses = []
        for tp in test_points:
            if not isinstance(tp, dict):
                continue
            cat = tp.get("category", "")
            tests = tp.get("tests", [])
            for t in tests:
                tn = t.get("name", "") if isinstance(t, dict) else str(t)
                if fn.split("_")[0] in tn or cat.replace("_","") in fn.replace("_",""):
                    matching_tps.append(tn)
                    # 从真实回归结果查状态
                    st = test_status_map.get(tn, test_status_map.get(f"test_{tn}", "⏳"))
                    tp_statuses.append(st if st != "⏳" else "—")
        tp_str = ", ".join(f"`{t}`" for t in matching_tps[:3])
        if len(matching_tps) > 3:
            tp_str += f" +{len(matching_tps)-3}"
        status_icons = [{"PASS":"✅","FAIL":"❌","DEGRADED":"⚠️"}.get(s, "—") for s in tp_statuses[:3]]
        status_str = " ".join(status_icons) if status_icons else "—"

        # 覆盖率来自真实数据
        overall_pct = cov_data.get("overall_pct", cov_data.get("coverage_pct", "⏳"))
        cov_str = _cov_badge(overall_pct, "90") if overall_pct != "⏳" else "⏳"

        out.append(f"| REQ-{feat_idx:03d} | {fd[:40]} | `{fn}` | "
                  f"{tp_str or '待分配'} | {cov_str} | {status_str} |")
    out.append("")

    # Coverage mapping — 来自真实数据
    out.append("## 3. 覆盖率映射\n")
    out.append("| 覆盖率类型 | 目标 | 关联需求 | 当前状态 |")
    out.append("|------------|------|----------|----------|")
    cov_goals = spec.get("coverage_goals", {}) or {}
    cov_lines = [
        ("Line",    str(cov_data.get("line_pct", "⏳")) + "%" if cov_data.get("line_pct") is not None else "⏳",
         cov_goals.get("line_coverage", cov_goals.get("code_coverage", "95%"))),
        ("Branch",  str(cov_data.get("branch_pct", "⏳")) + "%" if cov_data.get("branch_pct") is not None else "⏳",
         cov_goals.get("branch_coverage", "90%")),
        ("Toggle",  str(cov_data.get("toggle_pct", "⏳")) + "%" if cov_data.get("toggle_pct") is not None else "⏳",
         cov_goals.get("toggle_coverage", "85%")),
        ("Functional", str(cov_data.get("functional_pct", "⏳")) + "%" if cov_data.get("functional_pct") is not None else "⏳",
         "100%"),
    ]
    for ct, current, target in cov_lines:
        badge = _cov_badge(current, target) if current != "⏳" else "⏳"
        out.append(f"| {ct} | {target} | REQ-001~REQ-004 | {badge} |")
    out.append("")

    out.append(_doc_footer("RTM-DOC-008"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# DV-15 — 验证收敛报告
# ═══════════════════════════════════════════════════════════════

@_builder("vclose")
def _build_verification_closure(ctx: dict, ps: dict) -> str:
    reg = _parse_json(ctx.get("regression")) or {}
    cov = _parse_json(ctx.get("coverage")) or {}
    qa = _parse_json(ctx.get("_phase_qa")) or {}
    rpt = _parse_json(ctx.get("_phase_report")) or _parse_json(ctx.get("report")) or {}

    out = []
    out.append(_doc_header("VCLS-DOC-015", "验证收敛报告", status="Review"))

    # 1. 签核判定标准（固定阈值，来自验证计划）
    out.append("## 1. 签核判定标准\n")
    out.append("| 判定项 | 阈值 | 说明 |")
    out.append("|--------|------|------|")
    out.append("| 回归通过率 | **100%** | 所有 planned 测试通过，无失败 |")
    out.append("| 行覆盖率 | **≥95%** | Statement coverage |")
    out.append("| 分支覆盖率 | **≥90%** | Branch coverage |")
    out.append("| QA 评审 | **≥80/100** | 质量评审综合评分 |")
    out.append("| 签核状态 | **APPROVED** | 最终签核审批 |")
    out.append("")

    # 2. 当前值 vs 目标
    pr = _safe(reg, "pass_rate", default="N/A")
    line = _safe(cov, "line_pct", default="N/A")
    branch = _safe(cov, "branch_pct", default="N/A")
    qa_score = _safe(qa, "overall_score", default="N/A")
    signoff = _safe(rpt, "signoff", "status", default="N/A")

    def judge(val, target_str):
        try:
            target = float(str(target_str).replace("%",""))
            v = float(str(val).replace("%",""))
            return "✅" if v >= target else "❌"
        except (ValueError, TypeError):
            return "⏳"

    out.append("## 2. 验证收敛判定\n")
    out.append("| 指标 | 当前值 | 目标 | 判定 |")
    out.append("|------|--------|------|------|")
    out.append(f"| 回归通过率 | {pr} | 100% | {judge(pr, '100')} |")
    out.append(f"| 行覆盖率 | {line}% | 95% | {judge(line, '95')} |")
    out.append(f"| 分支覆盖率 | {branch}% | 90% | {judge(branch, '90')} |")
    out.append(f"| QA 评审 | {qa_score}/100 | 80 | {judge(qa_score, '80')} |")
    out.append(f"| 签核 | {signoff} | APPROVED | {judge('100' if 'APPROVED' in str(signoff).upper() else '0', '100')} |")
    out.append("")

    # 3. Go/No-Go
    try:
        all_ok = (
            judge(pr, '100') == '✅' and
            judge(line, '95') == '✅' and
            judge(branch, '90') == '✅' and
            judge(qa_score, '80') == '✅'
        )
    except Exception:
        all_ok = False

    out.append("## 3. Go / No-Go 决策\n")
    if all_ok:
        out.append("### ✅ GO — 验证收敛，建议进入下一阶段\n")
    else:
        out.append("### ⏳ NO-GO — 验证未完全收敛\n")
        out.append("未达标项：\n")
        for label, val, target in [
            ("回归通过率", pr, "100"),
            ("行覆盖率", line, "95"),
            ("分支覆盖率", branch, "90"),
            ("QA评审", qa_score, "80"),
        ]:
            if judge(val, target) != "✅":
                out.append(f"- **{label}**: {val} / {target}\n")
    out.append("")

    # 4. Checklist
    out.append("## 4. 验证收敛 Checklist\n")
    out.append("| 检查项 | 状态 | 备注 |")
    out.append("|--------|------|------|")
    checklist = [
        ("所有 planned 测试通过", judge(pr, '100'), ""),
        ("代码覆盖率达标 (line≥95%, branch≥90%)",
         "✅" if judge(line, '95') == '✅' and judge(branch, '90') == '✅' else "⏳", ""),
        ("功能覆盖率 100%", "⏳", ""),
        ("所有 Bug 已修复并回归通过", "⏳", ""),
        ("断言覆盖率 review 完成", "⏳", ""),
        ("签核文档完成", "⏳" if signoff == 'N/A' else "✅", str(signoff)),
    ]
    for c in checklist:
        out.append(f"| {c[0]} | {c[1]} | {c[2]} |")
    out.append("")

    out.append(_doc_footer("VCLS-DOC-015"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# Placeholder — 缺失数据时的文档
# ═══════════════════════════════════════════════════════════════

def _build_placeholder(num: str, title: str, doc_id: str, reason: str) -> str:
    out = []
    out.append(_doc_header(doc_id, title, status="Pending"))
    out.append(f"> ⚠️ **状态**: 暂未生成\n")
    out.append(f"> **原因**: {reason}\n")
    out.append(f"> 请运行对应的管道阶段以生成完整文档。\n")
    out.append(_doc_footer(doc_id))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# Summary Documents
# ═══════════════════════════════════════════════════════════════

def _build_frontend_summary(ctx: dict, run_state: dict) -> str:
    """前端设计交付总结"""
    spec = _parse_json(ctx.get("spec")) or {}
    design = _parse_json(ctx.get("design_arch")) or {}
    model = _parse_json(ctx.get("model")) or {}

    out = []
    out.append(_doc_header("FS-DOC-000", "前端设计交付总结", status="Review"))
    out.append("本文档汇总前端设计阶段（Spec → Architecture → Reference Model）的关键交付物。\n")

    # 1. 交付清单
    out.append("## 1. 交付清单\n")
    out.append("| 编号 | 文档 | 文档ID | 状态 |")
    out.append("|------|------|--------|------|")
    out.append("| 01 | [设计需求规格书](./de/01_specification.md) | SPEC-DOC-001 | ✅ |")
    out.append("| 02 | [微架构设计文档](./de/02_micro_architecture.md) | ARCH-DOC-002 | ✅ |")
    out.append("| 03 | [参考模型规格](./de/03_reference_model.md) | REFM-DOC-003 | ✅ |")
    out.append("")

    # 2. 设计摘要
    out.append("## 2. 设计摘要\n")
    out.append(f"- **模块名称**: `{_safe(spec, 'design_name', default=_safe(design, 'module_name', default='-'))}`")
    out.append(f"- **模型类型**: {_safe(model, 'model_type', default='-')}")
    features = spec.get("features", []) or []
    out.append(f"- **功能特性数**: {len(features)}")
    regs = design.get("registers", spec.get("registers", [])) or []
    out.append(f"- **寄存器数**: {len(regs)}")
    out.append("")

    # 3. 设计质量
    out.append("## 3. 设计质量\n")
    checklist = design.get("signoff_checklist", []) or []
    total_chk = len(checklist)
    pending_chk = sum(1 for c in checklist if isinstance(c, dict) and c.get("status") == "pending")
    out.append(f"- 签核检查项: {total_chk} | 待完成: {pending_chk}")
    out.append("")

    out.append(_doc_footer("FS-DOC-000"))
    return "\n".join(out)


def _build_verification_summary(ctx: dict, run_state: dict) -> str:
    """功能验证总结"""
    phases = run_state.get("phases", [])

    out = []
    out.append(_doc_header("FV-DOC-000", "功能验证总结", status="Review"))
    out.append("本文档汇总功能验证阶段（Verification Plan → Signoff）的关键结果。\n")

    # 1. 验证阶段状态
    out.append("## 1. 验证阶段状态\n")
    out.append("| 编号 | 阶段 | 状态 | 文档 |")
    out.append("|------|------|------|------|")
    phase_map = {
        "vplan": ("04", "验证计划书", "04_verification_plan.md"),
        "tpoint": ("05", "测试点分解", "05_testpoint_decomposition.md"),
        "UVM": ("06", "UVM环境", "06_uvm_environment.md"),
        "assert": ("07", "断言", "07_assertions.md"),
        "regress": ("08", "回归测试", "08_regression_report.md"),
        "cover": ("09", "覆盖率", "09_coverage_analysis.md"),
        "qa": ("10", "质量评审", "10_quality_review.md"),
        "report": ("11", "签核", "11_final_signoff.md"),
    }
    ps_map = {p.get("name", ""): p for p in phases}
    for pn, (num, title, link) in phase_map.items():
        status = ps_map.get(pn, {}).get("status", "pending")
        badge = _status_badge(status)
        out.append(f"| {num} | {title} | {badge} | [{title}](./{link}) |")
    out.append("")

    # 2. 验证结果
    out.append("## 2. 验证结果摘要\n")
    reg = _parse_json(ctx.get("regression")) or {}
    cov = _parse_json(ctx.get("coverage")) or {}
    qa = _parse_json(ctx.get("_phase_qa")) or {}
    rpt = _parse_json(ctx.get("_phase_report")) or _parse_json(ctx.get("report")) or {}

    out.append(f"- **回归通过率**: {_safe(reg, 'pass_rate', default='N/A')}")
    out.append(f"- **行覆盖率**: {_safe(cov, 'line_pct', default='N/A')}%")
    out.append(f"- **QA 评分**: {_safe(qa, 'overall_score', default='N/A')}/100")
    out.append(f"- **签核状态**: {_safe(rpt, 'signoff', 'status', default='N/A')}")
    out.append("")

    # 3. 结论
    out.append("## 3. 结论\n")
    ov = ctx.get("_overall_score", "?")
    out.append(f"**综合评分**: {ov}/100\n")
    out.append("验证结果将根据覆盖率收敛和 QA 评审结论最终判定。\n")

    out.append(_doc_footer("FV-DOC-000"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# flow.md — 完整流程总览
# ═══════════════════════════════════════════════════════════════

def _build_flow(run_state: dict, ctx: dict) -> str:
    phases = run_state.get("phases", [])
    run_id = run_state.get("run_id", "?")
    workflow = run_state.get("workflow", "?")
    started = run_state.get("started_at", "?")
    overall = ctx.get("_overall_score", "?")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    out = []
    out.append(_doc_header("FLOW-DOC-000", "验证流程总览"))
    out.append(f"**Run ID**: `{run_id}` | **Workflow**: `{workflow}` | **更新时间**: {now}\n")
    out.append(f"\n📄 **系统架构与策略**: [CONTEXT.md](../CONTEXT.md)\n")
    # ── 1. 前端设计流程 ──
    out.append("## 1. 前端设计流程\n")
    out.append("| 阶段 | 文档 | 文档ID | 状态 |")
    out.append("|------|------|--------|------|")
    design_phases = [
        ("spec",    "设计需求规格书",   "SPEC-DOC-001", "de/01_specification.md"),
        ("design",  "微架构设计文档",   "ARCH-DOC-002", "de/02_micro_architecture.md"),
        ("model",   "参考模型规格",     "REFM-DOC-003", "de/03_reference_model.md"),
        ("ifspec",  "接口控制文档",     "ICD-DOC-004",  "de/04_interface_specification.md"),
        ("rtlsign", "RTL签核报告",      "RTL-DOC-005",  "de/05_rtl_signoff.md"),
    ]
    ps_map = {p.get("name", ""): p for p in phases}
    for pn, title, doc_id, link in design_phases:
        st = ps_map.get(pn, {}).get("status", "pending")
        out.append(f"| {title} | [{title}](./{link}) | `{doc_id}` | {_status_badge(st)} |")

    out.append(f"\n📄 **前端设计交付总结**: [frontend_design_summary.md](./de/frontend_design_summary.md)\n")

    # ── 2. 功能验证流程 ──
    out.append("## 2. 功能验证流程\n")
    out.append("| 阶段 | 文档 | 文档ID | 状态 | 评分 |")
    out.append("|------|------|--------|------|------|")
    verify_phases = [
        ("vplan",   "验证计划书",       "VPLAN-DOC-006",  "dv/06_verification_plan.md"),
        ("tpoint",  "测试点分解文档",   "TPOINT-DOC-007", "dv/07_testpoint_decomposition.md"),
        ("rtm",     "需求追踪矩阵",     "RTM-DOC-008",    "dv/08_requirements_traceability.md"),
        ("UVM",     "UVM验证环境",      "UVM-DOC-009",    "dv/09_uvm_environment.md"),
        ("assert",  "断言规范",         "ASRT-DOC-010",   "dv/10_assertions.md"),
        ("regress", "回归测试报告",     "REGR-DOC-011",   "dv/11_regression_report.md"),
        ("cover",   "覆盖率分析报告",   "COV-DOC-012",    "dv/12_coverage_analysis.md"),
        ("qa",      "质量评审报告",     "QA-DOC-013",     "dv/13_quality_review.md"),
        ("report",  "最终签核报告",     "SIGN-DOC-014",   "dv/14_final_signoff.md"),
        ("vclose",  "验证收敛报告",     "VCLS-DOC-015",   "dv/15_verification_closure.md"),
    ]
    for pn, title, doc_id, link in verify_phases:
        st = ps_map.get(pn, {}).get("status", "pending")
        sc = ps_map.get(pn, {}).get("score", "-")
        out.append(f"| {title} | [{title}](./{link}) | `{doc_id}` | {_status_badge(st)} | {sc} |")

    out.append(f"\n📄 **功能验证总结**: [functional_verification_summary.md](./dv/functional_verification_summary.md)\n")

    # ── 3. 质量仪表盘 ──
    out.append("## 3. 质量仪表盘\n")
    out.append("| 指标 | 值 | 状态 |")
    out.append("|------|-----|------|")

    # UVM quality
    wd = ctx.get("working_dir", "output")
    qp = Path(wd) / "quality_report.json"
    if qp.exists():
        try:
            quality = json.loads(qp.read_text(encoding="utf-8", errors="replace"))
            det = quality.get("details", {})
            for check, key, label in [("static", "static", "静态检查"), ("compile", "compile", "编译检查"), ("loopback", "loopback", "闭环测试")]:
                d = det.get(key, {})
                ok = d.get("passed", False)
                out.append(f"| UVM {label} | {d.get('errors', d.get('missing', 0))} | {'✅' if ok else '❌'} |")
        except (json.JSONDecodeError, OSError):
            pass

    reg = _parse_json(ctx.get("regression")) or {}
    if reg:
        out.append(f"| 回归通过率 | {_safe(reg, 'pass_rate', default='-')} | {'✅' if _safe(reg, 'failed', default=1) == 0 else '❌'} |")

    qa = _parse_json(ctx.get("_phase_qa")) or {}
    if qa:
        out.append(f"| QA 评审 | {_safe(qa, 'overall_score', default='-')}/100 | {'✅' if 'READY' in str(_safe(qa,'verdict',default='')).upper() else '⚠️'} |")

    rpt = _parse_json(ctx.get("_phase_report")) or _parse_json(ctx.get("report")) or {}
    if rpt:
        out.append(f"| 签核 | {_safe(rpt, 'signoff', 'status', default='-')} | {'✅' if 'APPROVED' in str(_safe(rpt,'signoff','status',default='')).upper() else '⚠️'} |")

    out.append(f"\n**综合评分**: {overall}/100\n")

    # ── 4. 文档索引 ──
    out.append("## 4. 完整文档索引\n")
    all_docs = [
        ("01", "设计需求规格书",           "de/01_specification.md"),
        ("02", "微架构设计文档",           "de/02_micro_architecture.md"),
        ("03", "参考模型规格",             "de/03_reference_model.md"),
        ("04", "接口控制文档",             "de/04_interface_specification.md"),
        ("05", "RTL签核报告",              "de/05_rtl_signoff.md"),
        ("06", "验证计划书",               "dv/06_verification_plan.md"),
        ("07", "测试点分解文档",           "dv/07_testpoint_decomposition.md"),
        ("08", "需求追踪矩阵",             "dv/08_requirements_traceability.md"),
        ("09", "UVM验证环境",              "dv/09_uvm_environment.md"),
        ("10", "断言规范",                 "dv/10_assertions.md"),
        ("11", "回归测试报告",             "dv/11_regression_report.md"),
        ("12", "覆盖率分析报告",           "dv/12_coverage_analysis.md"),
        ("13", "质量评审报告",             "dv/13_quality_review.md"),
        ("14", "最终签核报告",             "dv/14_final_signoff.md"),
        ("15", "验证收敛报告",             "dv/15_verification_closure.md"),
        ("FS", "前端设计交付总结",         "de/frontend_design_summary.md"),
        ("FV", "功能验证总结",             "dv/functional_verification_summary.md"),
    ]
    for num, title, link in all_docs:
        out.append(f"- **{num}** | [{title}](./{link})")

    out.append("")
    out.append(_doc_footer("FLOW-DOC-000"))
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════

def generate_phase_doc(phase_name: str, ctx: dict, docs_dir: str,
                       phases_status: List[dict] = None) -> Optional[str]:
    spec = None
    for pn, num, title, ck, subdir in PHASE_DOC_SPECS:
        if pn == phase_name:
            spec = (pn, num, title, ck, subdir)
            break
    if not spec:
        return None

    pn, num, title, ctx_key, subdir = spec
    builder = _BUILDERS.get(phase_name)
    if not builder:
        return None

    content = builder(ctx, phases_status or [])
    file_name = f"{num}_{_slug(title)}.md"
    md_path = str(_write_doc(Path(docs_dir) / subdir / file_name, content))

    # ── 同步生成 CSV ──
    csv_builder = _CSV_BUILDERS.get(phase_name)
    if csv_builder:
        try:
            csv_builder(ctx)
        except Exception:
            pass

    return md_path


def update_flow_doc(run_state: dict, ctx: dict, docs_dir: str) -> Optional[str]:
    docs_path = Path(docs_dir)
    docs_path.mkdir(parents=True, exist_ok=True)

    # flow.md (top-level)
    flow = _build_flow(run_state, ctx)
    _write_doc(docs_path / "flow.md", flow)

    # frontend_design_summary.md → de/
    fs = _build_frontend_summary(ctx, run_state)
    _write_doc(docs_path / "de" / "frontend_design_summary.md", fs)

    # functional_verification_summary.md → dv/
    fv = _build_verification_summary(ctx, run_state)
    _write_doc(docs_path / "dv" / "functional_verification_summary.md", fv)

    return str(docs_path / "flow.md")


def _slug(title: str) -> str:
    """中文标题 → 英文 slug"""
    slug_map = {
        "设计需求规格书": "specification",
        "微架构设计文档": "micro_architecture",
        "参考模型规格": "reference_model",
        "接口控制文档": "interface_specification",
        "RTL签核报告": "rtl_signoff",
        "验证计划书": "verification_plan",
        "测试点分解文档": "testpoint_decomposition",
        "需求追踪矩阵": "requirements_traceability",
        "UVM验证环境": "uvm_environment",
        "断言规范": "assertions",
        "回归测试报告": "regression_report",
        "覆盖率分析报告": "coverage_analysis",
        "质量评审报告": "quality_review",
        "最终签核报告": "final_signoff",
        "验证收敛报告": "verification_closure",
    }
    return slug_map.get(title, title.lower().replace(" ", "_"))
