#!/usr/bin/env python3
"""tool_testgen —— 测试点 xlsx → UVM test case 生成器。

工作流:
  ① 验证计划填写 testpoints 表（功能/描述/checker/功能覆盖点/类名规划）
  ② 评审会填 review_status（门禁: 只有 approved 行生成可编译代码）
  ③ 本工具读 xlsx → 校验 → 渲染 {module}_tc_pkg.sv（GEN_TOP_TC 实例化）
     + testpoint_trace.md（测试点 ↔ test 类 ↔ checker ↔ 覆盖率 traceability）

xlsx 结构:
  testpoints  — 主表，一行 = 一个测试点 = 一个 test case（17 列）
  sequences   — 序列/重载类清单（生成器校验 testpoints 引用的类存在）
  review_log  — 评审记录
  meta        — module_name（env 名）等

用法:
  python -m src.generation_plane.uvm_tools.tool_testgen.main -i testpoint_apb.xlsx -d generated/
  python -m src.generation_plane.uvm_tools.tool_testgen.main --make-template -d .   # 生成模板 xlsx
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

# 复用生成层的文件头元数据（商标/权利/时间戳）
try:
    from ..tool_uvm.constants import DEFAULT_META, __version__ as GEN_UVN_VERSION
    from ..tool_uvm.render.region_injector import _make_banner
except ImportError:  # 直接脚本执行
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from generation.constants import DEFAULT_META, __version__ as GEN_UVN_VERSION
    from generation.render.region_injector import _make_banner

__version__ = "0.1.0"

# testpoints 表列定义: (表头, 必填, 说明)
TESTPOINT_COLUMNS: List[Tuple[str, bool, str]] = [
    ("feature_id", True, "功能点编号，多个 testpoint 归组（如 APB_FEAT_WR）"),
    ("id", True, "测试点编号，全文件唯一（如 APB_TP_001）"),
    ("feature", True, "功能点（如: APB back-to-back 写传输）"),
    ("description", True, "测试点描述: 检查什么、怎么查、期望结果"),
    ("spec_ref", False, "规格/寄存器章节引用"),
    ("priority", True, "P0 / P1 / P2"),
    ("tc_name", False, "test 类名（缺省 = {module}_gen_test_{id}）"),
    ("tc_com", True, "环境约束重载类（- = 不重载，渲染为默认 config 类）"),
    ("tc_reg", True, "configure_phase 配置序列类"),
    ("tc_seq", True, "main_phase 事务序列类"),
    ("seq_item_constraints", False,
     "定向约束 DSL（分号分隔）: field==v; field inside {[lo:hi]}; field dist {...}; "
     "→ 生成 {tc_name}_seq_item_c 派生类 + factory override"),
    ("seq_flow", False,
     "拆 seq 步骤。结构模式: seq_class(n); seq_class(n); （生成 flow_seq 骨架类）"
     "；简单模式: 自由文本步骤描述（生成注释）"),
    ("constraint_policy", False, "约束策略名（env constraint policy 包）"),
    ("checker", True, "检查器: sb:<名> / assert:<名> / ref_model:<名> / reg_mirror / 自由文本"),
    ("func_coverage", True, "功能覆盖点（coverpoint/cross 名，分号分隔）"),
    ("iterations", False, "随机次数（缺省走 num_transactions）"),
    ("review_status", True, "draft / reviewed / approved / rejected"),
    ("review_comment", False, "评审意见"),
    ("assignee", False, "负责人"),
]

class Priority(str, Enum):
    """测试点优先级（testpoints.priority 列，xlsx 下拉）。"""
    P0 = "P0"
    P1 = "P1"
    P2 = "P2"


class ReviewStatus(str, Enum):
    """评审状态（testpoints.review_status 列，xlsx 下拉；门禁：只有 APPROVED 生成可编译代码）。"""
    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    REJECTED = "rejected"


class SeqKind(str, Enum):
    """序列/重载类类型（sequences.kind 列，xlsx 下拉）。"""
    REG = "reg"      # configure_phase 配置序列
    SEQ = "seq"      # main_phase 事务序列
    COM = "com"      # 环境约束重载类


class ReviewConclusion(str, Enum):
    """评审结论（review_log.conclusion 列，xlsx 下拉）。"""
    PASS = "通过"
    CONDITIONAL = "有条件通过"
    FAIL = "不通过"


VALID_PRIORITY = tuple(p.value for p in Priority)
VALID_STATUS = tuple(s.value for s in ReviewStatus)
VALID_KIND = tuple(k.value for k in SeqKind)
VALID_CONCLUSION = tuple(c.value for c in ReviewConclusion)

SEQUENCE_COLUMNS = ["seq_class", "kind", "behavior", "source_pkg"]
REVIEW_LOG_COLUMNS = ["date", "reviewer", "conclusion", "affected_ids", "comment"]
META_KEYS = ["module_name", "dut_name", "output_pkg", "bus_seq_item"]

# ── 定向约束 DSL 与拆 seq 解析 ──
DIRECTED_RE = re.compile(r"^\s*(\w+)\s*(==|inside|dist)\s*(.+)$")
FLOW_STEP_RE = re.compile(r"^\s*([\w:]+)\s*\(\s*(\d+)\s*\)\s*$")


def parse_directed_constraints(text: str) -> Tuple[List[str], List[str]]:
    """定向约束 DSL → (渲染行列表, 解析错误列表)。

    支持: field==v; field inside {[lo:hi]}; field dist {...}; 分号分隔。
    """
    lines: List[str] = []
    errors: List[str] = []
    for stmt in (text or "").split(";"):
        stmt = stmt.strip()
        if not stmt:
            continue
        m = DIRECTED_RE.match(stmt)
        if not m:
            errors.append(f"无法解析定向约束 '{stmt}'"
                          f"（应为 field==v / field inside {{..}} / field dist {{..}}）")
            continue
        field, op, expr = m.group(1), m.group(2), m.group(3).strip()
        lines.append(f"{field} == {expr};" if op == "==" else f"{field} {op} {expr};")
    return lines, errors


def parse_seq_flow(text: str) -> Tuple[str, List[Tuple[str, int]]]:
    """拆 seq → ("structured", [(seq_class, count), ...]) 或 ("simple", [])。

    结构模式: seq_class(n); seq_class(n); （全部步骤匹配才生效）
    简单模式: 自由文本步骤描述（仅生成注释）
    """
    steps = [s.strip() for s in (text or "").split(";") if s.strip()]
    parsed: List[Tuple[str, int]] = []
    for s in steps:
        m = FLOW_STEP_RE.match(s)
        if not m:
            return "simple", []
        parsed.append((m.group(1), int(m.group(2))))
    return ("structured" if parsed else "simple"), parsed


# ════════════════════════════════════════════════════════════
# 读取
# ════════════════════════════════════════════════════════════

def _sheet_rows(ws) -> List[Dict[str, Any]]:
    """openpyxl 工作表 → [{表头: 值}]（第一行 = 表头）。"""
    rows = []
    headers = [str(c.value).strip() if c.value is not None else "" for c in ws[1]]
    for row in ws.iter_rows(min_row=2, values_only=True):
        if all(v is None or str(v).strip() == "" for v in row):
            continue
        d = {headers[i]: (str(row[i]).strip() if row[i] is not None and i < len(row) else "")
             for i in range(len(headers))}
        rows.append(d)
    return rows


def read_testpoints(xlsx_path: Path) -> Dict[str, Any]:
    """读 xlsx → {testpoints: [dict], sequences: [dict], review_log: [dict], meta: dict}。"""
    wb = load_workbook(xlsx_path, data_only=True)
    data: Dict[str, Any] = {
        "testpoints": _sheet_rows(wb["testpoints"]) if "testpoints" in wb.sheetnames else [],
        "sequences": _sheet_rows(wb["sequences"]) if "sequences" in wb.sheetnames else [],
        "review_log": _sheet_rows(wb["review_log"]) if "review_log" in wb.sheetnames else [],
        "meta": {},
    }
    if "meta" in wb.sheetnames:
        for row in _sheet_rows(wb["meta"]):
            key = row.get("key", "").strip()
            value = row.get("value", "").strip()
            if key in META_KEYS and value:
                data["meta"][key] = value
    return data


# ════════════════════════════════════════════════════════════
# 校验
# ════════════════════════════════════════════════════════════

def validate(data: Dict[str, Any], bus_seq_item: str = "",
             txn_fields: Optional[set] = None) -> List[str]:
    """校验 → 错误消息列表（空 = 通过）。

    bus_seq_item: bus seq_item 类型（meta.bus_seq_item 或 -y 接口 YAML 推导）
    txn_fields:   接口 YAML transaction_vars 字段集合（-y 提供时校验定向约束字段名）
    """
    errors: List[str] = []
    rows = data["testpoints"]
    module = data["meta"].get("module_name", "")
    if not module:
        errors.append("meta.module_name 缺失（env 名，如 APB_env）")
    if not rows:
        errors.append("testpoints 表为空")
        return errors

    ids = [r.get("id", "") for r in rows]
    for dup in {i for i in ids if ids.count(i) > 1}:
        errors.append(f"id '{dup}' 重复")

    seq_names = {s.get("seq_class", "") for s in data["sequences"]}
    for i, r in enumerate(rows, start=2):
        where = f"testpoints 第 {i} 行"
        for col, required, _doc in TESTPOINT_COLUMNS:
            if required and not r.get(col):
                errors.append(f"{where}: 必填列 '{col}' 为空")
        if r.get("priority") and r["priority"].upper() not in VALID_PRIORITY:
            errors.append(f"{where}: priority '{r['priority']}' 非法（{VALID_PRIORITY}）")
        if r.get("review_status") and r["review_status"].lower() not in VALID_STATUS:
            errors.append(f"{where}: review_status '{r['review_status']}' 非法（{VALID_STATUS}）")
        for col in ("tc_reg", "tc_seq"):
            cls = r.get(col, "")
            if cls and seq_names and cls not in seq_names:
                errors.append(f"{where}: {col} '{cls}' 不在 sequences 表（防类名笔误）")
        # ── 定向约束 DSL ──
        dsl_lines, dsl_errors = parse_directed_constraints(r.get("seq_item_constraints", ""))
        errors += [f"{where}: {e}" for e in dsl_errors]
        if dsl_lines and not bus_seq_item:
            errors.append(f"{where}: 有定向约束但无 bus seq_item 类型"
                          f"（用 -y 接口 YAML 推导或 meta.bus_seq_item 指定）")
        if txn_fields is not None and dsl_lines:
            for line in dsl_lines:
                field = line.split()[0]
                if field not in txn_fields and field != "xact_type":
                    errors.append(f"{where}: 约束字段 '{field}' 不在接口 transaction_vars 中")
        # ── 拆 seq ──
        mode, steps = parse_seq_flow(r.get("seq_flow", ""))
        if mode == "structured":
            for cls, _n in steps:
                if seq_names and cls not in seq_names:
                    errors.append(f"{where}: seq_flow 步骤 '{cls}' 不在 sequences 表")
    return errors


# ════════════════════════════════════════════════════════════
# 渲染
# ════════════════════════════════════════════════════════════

def render_tc_pkg(data: Dict[str, Any], bus_seq_item: str = "") -> str:
    """渲染 {module}_tc_pkg.sv（完整 test class；approved 可编译，其余注释保留）。"""
    module = data["meta"]["module_name"]
    lines: List[str] = []
    lines.append(_make_banner("// ").rstrip())
    lines.append("")
    lines.append("// ════════════════════════════════════════════════════════════════")
    lines.append(f"// Testpoint TC Package: {module}_tc_pkg")
    lines.append("// 来源: testpoint xlsx（仅 approved 行生成可编译代码，其余注释保留）")
    lines.append("// 定向约束类与拆 seq 骨架见 {module}_tc_constraints.svh")
    lines.append("// ════════════════════════════════════════════════════════════════")
    lines.append(f"package {module}_tc_pkg;")
    lines.append("  import uvm_pkg::*;")
    lines.append(f"  import {module}_test_pkg::*;")
    lines.append("  `include \"uvm_macros.svh\"")
    lines.append(f"  `include \"{module}_tc_constraints.svh\"   // 定向约束 seq_item_c + flow_seq 骨架")
    lines.append("")
    for r in data["testpoints"]:
        lines.extend(_render_test_class(r, module, bus_seq_item))
    lines.append("")
    lines.append(f"endpackage : {module}_tc_pkg")
    return "\n".join(lines) + "\n"


def _render_test_class(r: Dict[str, str], module: str, bus_seq_item: str) -> List[str]:
    status = r.get("review_status", "draft").lower()
    tc_name = r.get("tc_name") or f"{module}_gen_test_{r['id']}"
    tc_com = r.get("tc_com", "")
    if tc_com in ("", "-"):
        tc_com = f"{module}_config"   # 重载为默认配置类 = 不重载
    active = status == "approved"
    dsl_lines, _ = parse_directed_constraints(r.get("seq_item_constraints", ""))

    body = [
        f"class {tc_name} extends {module}_gen_test;",
        f"  `uvm_component_utils({tc_name})",
        "",
        "  function new(string name, uvm_component parent);",
        "    super.new(name, parent);",
        "  endfunction",
        "",
        "  function void build_phase(uvm_phase phase);",
        "    super.build_phase(phase);",
        f"    // 环境约束重载",
        f"    set_type_override_by_type({module}_config::get_type(), {tc_com}::get_type());",
    ]
    if bus_seq_item and dsl_lines:
        body.append(f"    // testpoint 定向约束（{tc_name}_seq_item_c，见 tc_constraints.svh）")
        body.append(f"    set_type_override_by_type({bus_seq_item}::get_type(), "
                    f"{tc_name}_seq_item_c::get_type());")
    body += [
        "    // configure_phase 配置序列 / main_phase 事务序列",
        f'    uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.configure_phase",'
        f'"default_sequence",{r["tc_reg"]}::type_id::get());',
        f'    uvm_config_db #(uvm_object_wrapper)::set(this,"env.vsqr.main_phase",'
        f'"default_sequence",{r["tc_seq"]}::type_id::get());',
        "  endfunction",
        f"endclass : {tc_name}",
        "",
    ]

    lines = []
    lines.append(f"// ── {r.get('feature_id', '-')}/{r['id']} [{r.get('priority', '-')}] "
                 f"{r.get('feature', '')} — {r.get('description', '')[:60]}")
    for extra in ("checker", "func_coverage", "constraint_policy", "iterations"):
        if r.get(extra):
            lines.append(f"//    {extra}: {r[extra]}")
    if r.get("seq_item_constraints"):
        lines.append(f"//    定向约束: {r['seq_item_constraints']}")
    if r.get("seq_flow"):
        lines.append(f"//    拆 seq: {r['seq_flow']}")
    if not active:
        lines.append(f"//    [status={status.upper()}] {r.get('review_comment', '')}")
    for line in body:
        lines.append(line if active else f"// {line}")
    return lines


def render_constraints_svh(data: Dict[str, Any], bus_seq_item: str) -> str:
    """渲染 {module}_tc_constraints.svh：每 TP 的 seq_item_c 定向约束类 + flow_seq 骨架。"""
    module = data["meta"]["module_name"]
    lines: List[str] = []
    lines.append("// ════════════════════════════════════════════════════════════════")
    lines.append(f"// Testpoint Constraints: {module}_tc_constraints")
    lines.append("// 定向约束 seq_item 派生类 + 拆 seq（flow_seq）骨架")
    lines.append("// ════════════════════════════════════════════════════════════════")
    for r in data["testpoints"]:
        status = r.get("review_status", "draft").lower()
        tc_name = r.get("tc_name") or f"{module}_gen_test_{r['id']}"
        dsl_lines, _ = parse_directed_constraints(r.get("seq_item_constraints", ""))
        if dsl_lines and bus_seq_item:
            active = status == "approved"
            lines.append(f"// ── {r['id']} 定向约束 ──")
            if not active:
                lines.append(f"//    [status={status.upper()}]")
            cls = [
                f"class {tc_name}_seq_item_c extends {bus_seq_item};",
                f"  `uvm_object_utils({tc_name}_seq_item_c)",
                "  constraint c_tp_directed {",
            ]
            cls += [f"    {l}" for l in dsl_lines]
            cls += ["  }", f"endclass : {tc_name}_seq_item_c", ""]
            for line in cls:
                lines.append(line if active else f"// {line}")
        mode, steps = parse_seq_flow(r.get("seq_flow", ""))
        if mode == "structured":
            active = status == "approved"
            lines.append(f"// ── {r['id']} 拆 seq 骨架 ──")
            if not active:
                lines.append(f"//    [status={status.upper()}]")
            cls = [
                f"class {tc_name}_flow_seq extends {module}_virtual_base_seq;",
                f"  `uvm_object_utils({tc_name}_flow_seq)",
                "  task body();",
            ]
            for idx, (seq, n) in enumerate(steps, start=1):
                cls += [
                    f"    // step{idx}: {seq} ×{n}",
                    f"    {seq} s{idx} = {seq}::type_id::create(\"s{idx}\");",
                    f"    s{idx}.num_transactions = {n};",
                    f"    s{idx}.start(m_sequencer);  // TODO: 按需绑定具体 bus sequencer（vsqr.<agent>_sqr）",
                ]
            cls += ["  endtask", f"endclass : {tc_name}_flow_seq", ""]
            for line in cls:
                lines.append(line if active else f"// {line}")
    return "\n".join(lines) + "\n"


def render_trace(data: Dict[str, Any]) -> str:
    """渲染 testpoint_trace.md（traceability 证据）。"""
    module = data["meta"]["module_name"]
    lines = [
        f"# Testpoint Traceability — {module}",
        "",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "| feature_id | id | feature | priority | tc_name | checker | func_coverage | "
        "policy | review |",
        "|------------|----|---------|----------|---------|---------|---------------|"
        "--------|--------|",
    ]
    for r in data["testpoints"]:
        tc_name = r.get("tc_name") or f"{module}_gen_test_{r['id']}"
        lines.append(
            f"| {r.get('feature_id', '-')} | {r.get('id', '-')} | {r.get('feature', '-')} "
            f"| {r.get('priority', '-')} | `{tc_name}` | {r.get('checker', '-')} "
            f"| {r.get('func_coverage', '-')} | {r.get('constraint_policy', '-')} "
            f"| {r.get('review_status', '-')} |")
    lines.append("")
    # ── 按 feature 分组视图 ──
    by_feature: Dict[str, List[Dict[str, Any]]] = {}
    for r in data["testpoints"]:
        by_feature.setdefault(r.get("feature_id", "-"), []).append(r)
    if by_feature:
        lines.append("## By Feature")
        lines.append("")
        for fid, rs in sorted(by_feature.items()):
            lines.append(f"### {fid}")
            lines.append("")
            for r in rs:
                tc_name = r.get("tc_name") or f"{module}_gen_test_{r['id']}"
                lines.append(f"- `{r.get('id', '-')}` [{r.get('priority', '-')}] "
                             f"{r.get('feature', '-')} → `{tc_name}`"
                             f"{'（' + r.get('review_status', '-') + '）'}")
            lines.append("")
    if data["review_log"]:
        lines.append("## Review Log")
        lines.append("")
        for rl in data["review_log"]:
            lines.append(f"- {rl.get('date', '-')} {rl.get('reviewer', '-')}: "
                         f"{rl.get('conclusion', '-')}（{rl.get('affected_ids', '-')}）"
                         f"{' — ' + rl['comment'] if rl.get('comment') else ''}")
    return "\n".join(lines) + "\n"


# ════════════════════════════════════════════════════════════
# 模板 xlsx
# ════════════════════════════════════════════════════════════

# ── 样式常量 ──
_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")       # 深蓝表头
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
_REQ_FONT = Font(bold=True, color="FFD966", size=11)        # 必填列金色字
_FILL_OK = PatternFill("solid", fgColor="C6EFCE")           # approved 示例行
_FILL_WIP = PatternFill("solid", fgColor="FFEB9C")          # 未过评审示例行
_TAB_COLORS = {"testpoints": "2E75B6", "sequences": "70AD47",
               "review_log": "ED7D31", "meta": "808080"}
_WIDTHS = {
    "feature_id": 16, "id": 14, "feature": 26, "description": 46, "spec_ref": 18,
    "priority": 10, "tc_name": 30, "tc_com": 26, "tc_reg": 20, "tc_seq": 24,
    "seq_item_constraints": 42, "seq_flow": 42, "constraint_policy": 18,
    "checker": 28, "func_coverage": 30, "iterations": 10, "review_status": 14,
    "review_comment": 26, "assignee": 10,
    "seq_class": 26, "kind": 8, "behavior": 40, "source_pkg": 20,
    "date": 12, "reviewer": 10, "conclusion": 12, "affected_ids": 16, "comment": 40,
    "key": 14, "value": 22,
}


def _style_sheet(ws, headers: List[Tuple[str, bool, str]], tab_color: str) -> None:
    """表头样式 + 冻结首行 + 筛选 + 列宽 + 表头注释（说明文档）。"""
    ws.sheet_properties.tabColor = _TAB_COLORS.get(ws.title, "808080")
    for i, (name, required, doc) in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=i)
        cell.fill = _HEADER_FILL
        cell.font = _REQ_FONT if required else _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.comment = Comment(
            ("【必填】" if required else "【可选】") + doc, "tool_testgen")
        ws.column_dimensions[cell.column_letter].width = _WIDTHS.get(name, 16)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(headers)).coordinate}"


def _add_dropdown(ws, column: str, values: List[str], rows: int = 200,
                  strict: bool = True, prompt: str = "") -> None:
    """枚举列下拉（strict=False 时允许自由输入，仅提示）。"""
    dv = DataValidation(type="list", formula1='"' + ",".join(values) + '"',
                        allow_blank=True, showErrorMessage=strict)
    if prompt:
        dv.showInputMessage = True
        dv.promptTitle = "填写说明"
        dv.prompt = prompt
    ws.add_data_validation(dv)
    dv.add(f"{column}2:{column}{rows}")


def make_template(path: Path) -> None:
    """生成 testpoint_<module>.xlsx 模板（美化表头 + 枚举下拉 + 示例行）。"""
    wb = Workbook()
    wb.remove(wb.active)

    # ── testpoints 主表 ──
    ws = wb.create_sheet("testpoints")
    headers = [(col, req, doc) for col, req, doc in TESTPOINT_COLUMNS]
    ws.append([col for col, _r, _d in headers])
    _style_sheet(ws, headers, "testpoints")
    # 列字母按新表头顺序: F=priority, K=seq_item_constraints(无), L=seq_flow(无),
    #                    N=checker, Q=review_status
    _add_dropdown(ws, "F", list(VALID_PRIORITY))                       # priority
    _add_dropdown(ws, "Q", list(VALID_STATUS))                         # review_status
    _add_dropdown(ws, "N", ["sb:", "assert:", "ref_model:", "reg_mirror:"],
                  strict=False,
                  prompt="前缀 + 具体名，如 sb:apb_scb；多个用 ; 分隔，也可自由填写")
    ws.append([
        "APB_FEAT_WR", "APB_TP_001", "APB back-to-back 写传输",
        "连续两次写、第二次无等待态，检查 psel 保持与 pslverr=0",
        "APB spec §3.2.1", "P0", "", "apb_config_b2b_override", "apb_cfg_seq", "apb_b2b_wr_seq",
        "paddr==32'h1000; pwrite==1; pwdata inside {[0:255]};",
        "apb_random_wr_seq(10); apb_b2b_wr_seq(1); apb_read_cmp_seq(1);",
        "apb_policy_b2b", "sb:apb_scb", "apb_write_b2b_cross; apb_wr_err_cp", "100",
        "approved", "已评审通过", "张三",
    ])
    for c in ws[2]:
        c.fill = _FILL_OK
    ws.append([
        "APB_FEAT_ERR", "APB_TP_002", "错误响应注入",
        "slave 注入 pslverr=1，master 侧应采到错误响应并上报",
        "APB spec §4.1", "P1", "", "-", "apb_cfg_seq", "apb_err_inject_seq",
        "",
        "apb_err_inject_seq(50);",
        "", "sb:apb_scb; assert:assert_pslverr_ack", "apb_err_resp_cp", "",
        "reviewed", "待补充断言清单后通过", "李四",
    ])
    for c in ws[3]:
        c.fill = _FILL_WIP

    # ── sequences 清单 ──
    ws2 = wb.create_sheet("sequences")
    ws2.append(SEQUENCE_COLUMNS)
    _style_sheet(ws2, [(c, True, doc) for c, doc in zip(
        SEQUENCE_COLUMNS,
        ["序列/重载类名（testpoints 的 tc_reg/tc_seq/tc_com 必须在此表）",
         "类型: reg=configure_phase 配置序列 / seq=main_phase 事务序列 / com=约束重载类",
         "该序列做什么（评审依据）", "实现在哪个 package"])], "sequences")
    _add_dropdown(ws2, "B", list(VALID_KIND))
    for row in (
        ["apb_cfg_seq", "reg", "配置 10 个控制寄存器", "APB_env_seq_pkg"],
        ["apb_b2b_wr_seq", "seq", "back-to-back 写 100 次", "APB_env_seq_pkg"],
        ["apb_err_inject_seq", "seq", "随机错误响应注入 50 次", "APB_env_seq_pkg"],
        ["apb_random_wr_seq", "seq", "随机写（seq_flow 步骤用）", "APB_env_seq_pkg"],
        ["apb_read_cmp_seq", "seq", "读回并比对（seq_flow 步骤用）", "APB_env_seq_pkg"],
        ["apb_config_b2b_override", "com", "环境约束重载: drive_delay=0", "APB_env_test_pkg"],
    ):
        ws2.append(row)

    # ── review_log 评审记录 ──
    ws3 = wb.create_sheet("review_log")
    ws3.append(REVIEW_LOG_COLUMNS)
    _style_sheet(ws3, [(c, False, doc) for c, doc in zip(
        REVIEW_LOG_COLUMNS,
        ["评审日期", "评审人", "结论", "影响范围（id 或区间）", "意见"])], "review_log")
    _add_dropdown(ws3, "C", list(VALID_CONCLUSION))
    ws3.append(["2026-09-05", "张三", "通过", "APB_TP_001", "检查器与覆盖点齐全"])

    # ── meta ──
    ws4 = wb.create_sheet("meta")
    ws4.append(["key", "value"])
    _style_sheet(ws4, [("key", True, "配置键（module_name 必填 = env 名）"),
                       ("value", True, "配置值")], "meta")
    for row in (["module_name", "APB_env"],
                ["dut_name", "apb_slave_dut"],
                ["output_pkg", "APB_env_tc_pkg"],
                ["bus_seq_item", "apb_master_seq_item"]):
        ws4.append(row)

    wb.save(path)


# ════════════════════════════════════════════════════════════
# CLI
# ════════════════════════════════════════════════════════════

def load_interface_info(yaml_paths: List[str]) -> Tuple[set, List[str]]:
    """读接口 YAML → (transaction_vars 字段集合, bus seq_item 类型列表)。"""
    import yaml as _yaml
    fields: set = set()
    bus_items: List[str] = []
    for p in yaml_paths:
        data = _yaml.safe_load(Path(p).read_text(encoding="utf-8", errors="replace")) or {}
        for item in data.get("interfaces") or []:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "")
            if name:
                bus_items.append(f"{name}_master_seq_item")
            for var in item.get("transaction_vars") or []:
                if isinstance(var, dict) and var.get("name"):
                    fields.add(var["name"])
    return fields, bus_items


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tool_testgen",
        description="测试点 xlsx → UVM test case（完整类 + 定向约束 seq_item_c + 拆 seq 骨架）"
                    " + traceability。")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s (tool_testgen) {__version__}")
    parser.add_argument("-i", "--input", help="testpoint xlsx 文件路径")
    parser.add_argument("-y", "--yaml", nargs="+",
                        help="接口 YAML（校验定向约束字段名 + 推导 bus seq_item 类型）")
    parser.add_argument("-d", "--dest_dir", default="generated",
                        help="输出目录（缺省 ./generated）")
    parser.add_argument("--make-template", action="store_true",
                        help="生成 testpoint_template.xlsx 模板")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="静默输出")
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    dest = Path(args.dest_dir).expanduser()

    if args.make_template:
        template_path = dest / "testpoint_template.xlsx"
        template_path.parent.mkdir(parents=True, exist_ok=True)
        make_template(template_path)
        log(f"Template written: {template_path}")
        return 0

    if not args.input:
        parser.error("需要 -i <testpoint.xlsx>（或用 --make-template 生成模板）")
    xlsx_path = Path(args.input).expanduser()
    if not xlsx_path.is_file():
        parser.error(f"xlsx 不存在: {xlsx_path}")

    data = read_testpoints(xlsx_path)
    # bus seq_item 类型: meta.bus_seq_item > -y 接口 YAML 推导
    txn_fields: Optional[set] = None
    bus_seq_item = data["meta"].get("bus_seq_item", "")
    if args.yaml:
        txn_fields, bus_items = load_interface_info(args.yaml)
        if not bus_seq_item and bus_items:
            bus_seq_item = bus_items[0]
    errors = validate(data, bus_seq_item=bus_seq_item, txn_fields=txn_fields)
    if errors:
        for e in errors:
            print(f"Error: {e}", file=sys.stderr)
        return 1

    module = data["meta"]["module_name"]
    dest.mkdir(parents=True, exist_ok=True)
    pkg_path = dest / f"{module}_tc_pkg.sv"
    pkg_path.write_text(render_tc_pkg(data, bus_seq_item), encoding="utf-8")
    cons_path = dest / f"{module}_tc_constraints.svh"
    cons_path.write_text(render_constraints_svh(data, bus_seq_item), encoding="utf-8")
    trace_path = dest / "testpoint_trace.md"
    trace_path.write_text(render_trace(data), encoding="utf-8")
    # P1-5: 回归矩阵（approved × seeds；source_xlsx 供 tool_testrun 回写执行结果）
    import yaml as _yaml
    reg_tests = []
    for r in data["testpoints"]:
        if r.get("review_status", "").lower() != ReviewStatus.APPROVED.value:
            continue
        entry = {"tc_name": r.get("tc_name") or f"{module}_gen_test_{r['id']}",
                 "id": r.get("id"), "priority": r.get("priority", "P2")}
        if r.get("constraint_policy"):
            entry["policy"] = r["constraint_policy"]
        if r.get("iterations"):
            entry["iterations"] = int(r["iterations"])
        reg_tests.append(entry)
    plan = {"regression": {"module": module, "seeds": [1, 2, 3, 4, 5],
                           "source_xlsx": str(xlsx_path.resolve()),
                           "tests": reg_tests}}
    plan_path = dest / "regression_plan.yaml"
    plan_path.write_text(
        _yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")

    n_approved = sum(1 for r in data["testpoints"]
                     if r.get("review_status", "").lower() == ReviewStatus.APPROVED.value)
    log(f"Generated {pkg_path} ({n_approved} approved / "
        f"{len(data['testpoints']) - n_approved} 未过评审保留注释)")
    log(f"Generated {cons_path}")
    log(f"Generated {trace_path}")
    log(f"Generated {plan_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
