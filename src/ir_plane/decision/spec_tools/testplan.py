"""
testplan.py —— spec → 两个标准验证文档生成器。

从规格（analyze_specification 解析）确定性派生：
  1. testplan.md            —— 7 节标准验证计划（总体设计 / 测试点 / 平台 / 环境使用 / 未覆盖 / 评审 / 总结）
  2. testpoint_<module>.xlsx —— tool_uvmtestgen 输入（testpoints/sequences/meta 表）

用法:
    python -m src.ir_plane.decision.spec_tools.testplan -i specs/apb_uart/apb_uart_spec.md -d generated/
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# spec → 结构化分析
# ═══════════════════════════════════════════════════════════════

def analyze_spec(spec_text: str) -> Dict[str, Any]:
    """复用 spec_tools.analyze_specification，返回结构化 spec dict。"""
    from src.ir_plane.decision.spec_tools.main import analyze_specification
    raw = analyze_specification(spec_text)
    data = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
    if not isinstance(data, dict) or not data.get("design_name"):
        data = {"design_name": "dut", "version": "1.0"}
    data.setdefault("version", "1.0")
    data.setdefault("overview", "")
    data.setdefault("interfaces", [])
    data.setdefault("features", [])
    data.setdefault("registers", [])
    data.setdefault("interrupts", [])
    return data


# ═══════════════════════════════════════════════════════════════
# testplan.md 渲染（7 节标准结构）
# ═══════════════════════════════════════════════════════════════

def _feature_name(f: Dict[str, Any]) -> str:
    return str(f.get("name", "feature")).strip()


def _priority(f: Dict[str, Any]) -> str:
    return str(f.get("priority", "P1")).upper()


def render_testplan_md(spec: Dict[str, Any]) -> str:
    """渲染 testplan.md（7 节标准验证计划结构）。

    可确定性推导的章节从 spec 填充；需人工/EDA 的部分（时序图、评审、总结）留占位。
    """
    module = spec.get("design_name", "dut")
    version = spec.get("version", "1.0")
    date = datetime.now().strftime("%Y-%m-%d")
    interfaces = spec.get("interfaces", []) or []
    features = spec.get("features", []) or []
    registers = spec.get("registers", []) or []
    interrupts = spec.get("interrupts", []) or []

    L: List[str] = []
    A = L.append

    # ── 文档头：Version / Date / Description ──
    A(f"# {module} 验证计划（Testplan）")
    A("")
    A("| 项 | 内容 |")
    A("|----|------|")
    A(f"| Version | {version} |")
    A(f"| Date | {date} |")
    A(f"| Description | {spec.get('overview', '') or module + ' 模块验证计划'} |")
    A("")

    # ── 1. 总体设计介绍图 ──
    A("## 1. 总体设计介绍图")
    A("")
    A("### 1.1 设计框图")
    A("")
    A("> TODO：插入设计框图（DUT 内部结构 + 总线接口 + 时钟复位）。")
    A("")
    A("### 1.2 接口定义")
    A("")
    A("#### 1.2.1 IO 端口列表")
    A("")
    A("| 信号 | 位宽 | 方向 | 协议 | 描述 |")
    A("|------|------|------|------|------|")
    for itf in interfaces:
        name = str(itf.get("name", "?")).split("[")[0]
        width = itf.get("data_width", 1)
        direction = str(itf.get("direction", "INPUT")).upper()
        protocol = itf.get("protocol", "generic") or "generic"
        desc = str(itf.get("description", "-"))[:60]
        A(f"| {name} | {width} | {direction} | {protocol} | {desc} |")
    A("")
    A("#### 1.2.2 接口时序")
    A("")
    A("> TODO：插入接口时序图（APB 读写握手 / UART 帧格式 等）。")
    A("")
    A("#### 1.2.3 时钟和复位")
    A("")
    A("- 时钟：由接口表 Clock 协议信号确定（见 IO 端口列表）")
    A("- 复位：由接口表 Reset 协议信号确定（见 IO 端口列表）")
    A("")
    A("### 1.3 功能描述")
    A("")
    A("#### 1.3.1 正常功能")
    A("")
    for f in features:
        A(f"- **{_feature_name(f)}**（{_priority(f)}）：{str(f.get('description', _feature_name(f)))[:120]}")
    if not features:
        A("- （spec 未提供功能章节，需人工补充）")
    A("")
    A("#### 1.3.2 边界行为")
    A("")
    A("> TODO：补充边界行为（FIFO 满/空、地址越界、波特率边界等）。")
    A("")
    A("### 1.4 软件配置流程")
    A("")
    A("> TODO：补充软件配置流程（寄存器初始化顺序 / 使能流程）。")
    A("")
    if registers:
        A("| 寄存器 | 偏移 | 位宽 | 访问 | 描述 |")
        A("|--------|------|------|------|------|")
        for r in registers:
            A(f"| {r.get('name','?')} | {r.get('offset','-')} | {r.get('width','-')} "
              f"| {r.get('access','RW')} | {str(r.get('description','-'))[:60]} |")
        A("")
    A("### 1.5 异常处理")
    A("")
    if interrupts:
        for intr in interrupts:
            A(f"- 中断 `{intr.get('name','?')}`：{intr.get('description','-')[:80]}")
    else:
        A("- （spec 未提供中断/异常定义，需人工补充）")
    A("")

    # ── 2. 验证测试点 ──
    A("## 2. 验证测试点")
    A("")
    A("| 编号 | 测试点 | 级别 | 描述 |")
    A("|------|--------|------|------|")
    for i, f in enumerate(features, 1):
        A(f"| {module}_TP_{i:03d} | {_feature_name(f)} | {_priority(f)} "
          f"| {str(f.get('description', ''))[:100]} |")
    if not features:
        A("| - | （无测试点） | - | spec 未提供功能章节 |")
    A("")

    # ── 3. 验证平台 ──
    A("## 3. 验证平台")
    A("")
    A("### 3.1 验证架构图")
    A("")
    A("> TODO：插入验证架构图（master/slave agent + predictor + scoreboard + coverage）。")
    A("")
    A("### 3.2 典型用例流程")
    A("")
    A("> TODO：补充典型用例流程（配置 → 激励 → 比对 → 覆盖率）。")
    A("")
    A("### 3.3 激励生成")
    A("")
    A("#### 3.3.1 Sequence item")
    A("")
    A(f"- `{module}_master_seq_item`：master 事务（is_master=True 字段）")
    A(f"- `{module}_slave_seq_item`：slave 事务（请求回填 + 响应控制）")
    A("")
    A("#### 3.3.2 Sequence")
    A("")
    A(f"- `{module}_master_sequence`：master 激励序列")
    A(f"- `{module}_slave_sequence`：slave 响应序列（事件驱动 req_fifo）")
    A("")
    A("### 3.4 验证组件介绍")
    A("")
    A(f"#### 3.4.1 Agent —— `{module}_master_agent` / `{module}_slave_agent`")
    A("#### 3.4.2 Predictor —— 参考模型（黄金库命中或占位）")
    A("#### 3.4.3 Scoreboard —— `sb_type` 指定（如 `uvmf_in_order_scoreboard`）")
    A("#### 3.4.4 Checker —— 断言（SVA）+ 参考模型比对")
    A("#### 3.4.5 Coverage —— 功能覆盖（coverpoint/cross）+ 代码覆盖")
    A("")
    A("### 3.5 测试点描述和验证方法")
    A("")
    A("每个测试点对应一个 test case（见 testpoint.xlsx → tool_uvmtestgen 生成 tc_pkg）。")
    A("")

    # ── 4. 验证环境使用 ──
    A("## 4. 验证环境使用")
    A("")
    A("### 4.1 目录结构")
    A("")
    A("```")
    A("generated/")
    A(f"├── agents/{module}_agent/   # AXI-VIP 风格（1_interface…8_ral + loopback）")
    A("├── env/                     # env config / env / coverage / pkg / tests / seqs")
    A("└── bench/                   # tb_top + harness")
    A("```")
    A("")
    A("### 4.2 配置文件介绍")
    A("")
    A("#### 4.2.1 vcs 仿真 cfg")
    A("#### 4.2.2 ISA 编译 cfg")
    A("")
    A("> TODO：补充仿真/编译配置文件说明。")
    A("")
    A("### 4.3 仿真运行")
    A("")
    A("#### 4.3.1 Smoke case 命令")
    A("")
    A(f"```bash\nvagent verify specs/{module}/{module}_spec.md --verify-only\n```")
    A("")
    A("#### 4.3.2 回归命令")
    A("")
    A(f"```bash\nvagent verify specs/{module}/{module}_spec.md --verify-only --max-rounds 8\n```")
    A("")
    A("### 4.4 测试用例")
    A("")
    A("见 testpoint.xlsx（tool_uvmtestgen 生成 tc_pkg + traceability）。")
    A("")
    A("### 4.5 覆盖率报告")
    A("")
    A("#### 4.5.1 Code coverage")
    A("#### 4.5.2 Function coverage")
    A("")
    A("> TODO：跑完仿真后回填覆盖率数据。")
    A("")

    # ── 5. 验证未覆盖部分 ──
    A("## 5. 验证未覆盖部分")
    A("")
    A("> TODO：列出未覆盖功能/边界（exclude 项 + 理由，见 exclude_registry 审计链）。")
    A("")

    # ── 6. 评审记录 ──
    A("## 6. 评审记录")
    A("")
    A("| 日期 | 评审人 | 结论 | 意见 |")
    A("|------|--------|------|------|")
    A("| | | | |")
    A("")

    # ── 7. 经验总结 ──
    A("## 7. 经验总结")
    A("")
    A("> TODO：验证结束后回填经验总结（可蒸馏进 L5 经验库）。")
    A("")

    return "\n".join(L)


# ═══════════════════════════════════════════════════════════════
# testpoint.xlsx（tool_uvmtestgen 输入）
# ═══════════════════════════════════════════════════════════════

def spec_to_testpoint_rows(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    """spec.features → testpoints 行（feature_id/id/feature/description/priority/checker/...）。"""
    module = spec.get("design_name", "dut")
    features = spec.get("features", []) or []
    rows = []
    # 按优先级分组，稳定 feature_id
    by_feat: Dict[str, int] = {}
    for f in features:
        pri = _priority(f)
        name = _feature_name(f)
        fid = by_feat.get(name)
        if fid is None:
            fid = len(by_feat) + 1
            by_feat[name] = fid
        rows.append({
            "feature_id": f"{module}_FEAT_{fid:02d}",
            "id": f"{module}_TP_{len(rows) + 1:03d}",
            "feature": name,
            "description": str(f.get("description", name))[:150],
            "priority": pri if pri in ("P0", "P1", "P2") else "P1",
            "checker": f"sb:{module}_scb",
            "func_coverage": f"{name}_cp",
            "review_status": "draft",
        })
    return rows


def write_testpoint_xlsx(rows: List[Dict[str, str]], module: str, path: Path) -> None:
    """写 testpoint_<module>.xlsx（testpoints 表 + meta 表）。"""
    from openpyxl import Workbook
    from openpyxl.comments import Comment
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation

    # 与 tool_uvmtestgen 的 TESTPOINT_COLUMNS 对齐（必填 17 列）
    columns = ["feature_id", "id", "feature", "description", "spec_ref", "priority",
               "tc_name", "tc_com", "tc_reg", "tc_seq", "seq_item_constraints", "seq_flow",
               "constraint_policy", "checker", "func_coverage", "iterations",
               "review_status", "review_comment", "assignee"]

    wb = Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet("testpoints")
    ws.append(columns)
    header_fill = PatternFill("solid", fgColor="1F4E79")
    header_font = Font(bold=True, color="FFFFFF")
    for i in range(1, len(columns) + 1):
        c = ws.cell(row=1, column=i)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center")
    for r in rows:
        ws.append([r.get(col, "") for col in columns])
    ws.freeze_panes = "A2"

    # meta 表
    ws2 = wb.create_sheet("meta")
    ws2.append(["key", "value"])
    for k, v in (("module_name", f"{module}_env"),
                 ("dut_name", module),
                 ("output_pkg", f"{module}_env_tc_pkg"),
                 ("bus_seq_item", f"{module}_master_seq_item")):
        ws2.append([k, v])

    wb.save(path)


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

def generate_docs(spec_text: str, output_dir: Path) -> Dict[str, Path]:
    """spec → testplan.md + testpoint.xlsx，返回生成文件路径。"""
    spec = analyze_spec(spec_text)
    module = spec.get("design_name", "dut")
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{module}_testplan.md"
    md_path.write_text(render_testplan_md(spec), encoding="utf-8")

    rows = spec_to_testpoint_rows(spec)
    xlsx_path = output_dir / f"testpoint_{module}.xlsx"
    write_testpoint_xlsx(rows, module, xlsx_path)

    return {"testplan_md": md_path, "testpoint_xlsx": xlsx_path}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="spec → testplan.md + testpoint.xlsx 标准验证文档生成")
    ap.add_argument("-i", "--input", required=True, help="spec 文档路径")
    ap.add_argument("-d", "--dest_dir", default="generated", help="输出目录")
    args = ap.parse_args(argv)

    spec_text = Path(args.input).read_text(encoding="utf-8")
    out = generate_docs(spec_text, Path(args.dest_dir).expanduser())
    for k, p in out.items():
        print(f"Generated {k}: {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
