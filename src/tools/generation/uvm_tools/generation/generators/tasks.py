"""渲染任务 —— 模型 → 文件，只做渲染、不解析、不编排。

从 `tool_uvm/gen_uvm.py` 原样搬入；`gen_uvm` 继续 re-export 这些名字。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..constants import DEFAULT_META, TEMPLATES_DIR, __version__
from ..ir.uvm_ir import validate_agent_ir, validate_ir
from ..ir.shadow import (
    compare_agent_context, compare_environment_context, record_agent,
    record_environment, shadow_enabled, warn_shadow,
)
from ..models import (
    AgentModel, BenchAgentEntry, BenchModel, ConstraintModel, EnvironmentModel,
    HarnessModel,
)
from ..render.file_ops import _is_generated_file
from ..render.jinja_renderer import COMPANY_TRADEMARK, JinjaRenderer, reproducible_now
from ..render.region_injector import RegionInjector
from ..render.templates import (
    AGENT_LOOPBACK_TEMPLATES, BENCH_TEMPLATES, ENVIRONMENT_ATTR_TEST_TEMPLATES,
    ENVIRONMENT_BATCH_TEST_TEMPLATES, ENVIRONMENT_REG_TEST_TEMPLATES,
    ENVIRONMENT_ROOT_TEMPLATES, ENVIRONMENT_SEQ_TEMPLATES,
    ENVIRONMENT_TEST_TEMPLATES, ENV_CONSTRAINT_TEMPLATES, HARNESS_TEMPLATES,
    INTERFACE_TEMPLATES, _split_template_entry,
)

def _warn_ir_issues(scope: str, issues: List[Dict[str, str]]) -> None:
    """渲染前的 UVM IR 结构校验 —— 只出声，不阻断、不改产物字节。

    IR 是 parsing 与 render 之间的契约：模型/解析一旦漂移（agent 端口丢了方向、
    模型里出现重名 agent），这里先看见，而不是产出一份编译不过或语义悬空的 SV。
    """
    for issue in issues:
        print(f"  [gen_uvm] Warning: UVM IR {scope}: {issue['message']}",
              flush=True)


def read_env_cov_bins(output_dir: Path) -> Dict[str, Any]:
    """读 verify 落下的 `inputs/yaml/uvm/env_cov_bins.yaml`。

    **这一个文件喂两个模板**：

        `env_cov.sv.j2`   组件持 `virtual <type>`，把 DUT 信号采进 `cg_dut`
        `tb_top.sv.j2`    把 bind 出来的接口实例挂进 `config_db`

    两边必须拿到**同一份身份**（类型名 / bind 实例名 / 时钟 / 复位）。各读各的、
    各推各的名字，漂了的表现是"组件拿到空句柄、覆盖率永远 0%"，而**编译和加载
    都不报错** —— 正是本仓库最贵的那类 bug。所以这里做成**一个读者**，
    两个渲染任务都经它取。

    **两个键名都认**：`cov_bins` 是现在写的（与 schema 的文档类型一致），
    `coverage_bins` 是老的运行目录里留下的 —— 老的照样能渲染。
    文件不在 / 读坏了就返回空字典：调用方各自退回"没有"的行为（一个字都不生成），
    而不是猜一个默认值出来。
    """
    import json as _json
    path = Path(output_dir) / "inputs" / "yaml" / "uvm" / "env_cov_bins.yaml"
    if not path.exists():
        return {}
    try:
        data = _json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class RenderTask:
    def __init__(self, renderer: JinjaRenderer, output_dir: Path,
                 injector: Optional[RegionInjector] = None,
                 overwrite: bool = False,
                 meta: Optional[Dict[str, str]] = None) -> None:
        self.renderer = renderer
        self.output_dir = output_dir
        self.injector = injector if injector is not None else RegionInjector()
        self.overwrite = overwrite
        self.meta = dict(meta or DEFAULT_META)
        self.skipped = 0

    def _add_coverage_dut_context(self, context: Dict[str, Any]) -> None:
        """把 **DUT 覆盖率接口**的身份与 bins 塞进 context（env 与 bench 两条路共用）。

        两份模板要的键不一样，但**来源必须是同一个文件**（`read_env_cov_bins`）：

          · `env_cov.sv.j2`  要 `coverage_dut_if`（类型名/时钟/复位）+ `coverage_dut_bins`
          · `tb_top.sv.j2`   要 `coverage_dut_if` 里的**类型名与 bind 实例名**
            （去挂 `config_db`），DUT 实例路径则由 bench 自己给

        缺席时一律给空字典：模板据此**一个字都不生成**。**"两边一致地没有"**
        是有意的 —— 单边有（组件声明了 `virtual <type>` 而 tb_top 没挂）会渲染出
        一个永远拿到空句柄的组件，覆盖率恒 0%，而编译与加载都不报错。
        """
        data = read_env_cov_bins(self.output_dir)
        _dif = data.get("dut_if")
        context["coverage_dut_if"] = _dif if isinstance(_dif, dict) else {}
        _db = data.get("dut_bins")
        context["coverage_dut_bins"] = _db if isinstance(_db, dict) else {}
        # DUT 检查规则：env 组件逐拍求值 → 收口打印 `matched=N mismatched=K`。
        # **这是"真 pass"的比对那一半**（判据要求日志里有 `mismatched=0`）——
        # 缺了它，一条用例再干净也只是"没报错"，不是"验过了"。
        _dc = data.get("dut_checker")
        context["coverage_dut_checker"] = _dc if isinstance(_dc, dict) else {}

    def should_skip(self, target_path: Path) -> bool:
        """默认跳过已存在文件（UVMF 语义）；-o/--overwrite 或合并流程例外。

        **但"跳过"分两种，不能一视同仁**：

          · 目标存在，**且带生成签名**（`_is_generated_file`）—— 那是**我们自己的
            产物**（上一轮的输出），跳过它等于**永远不刷新**：模板改了、生成物
            却停在旧版本上，而且不报一声。实测踩过：一份更老版本模板产的
            `apb_loopback_scb.sv`（带着当前 `apb.yaml` 产不出的 `pstrb`/`pprot`）
            在"全新"的 run 里被编译，于是 SCB 引用了 seq_item 里没有的字段 →
            `(vlog-13276)` → 类没编成 → `[INVTST] apb_loopback_test not found`。
            **时好时坏**（取决于那一轮用的是旧文件还是新生成的），最难查的那种。
            所以：**自己生成的，照常重生**（刷新是对的，那也是它的来源）。

          · 目标存在，**但不是生成物** —— 那是人手写的/别处来的，**不动它是对的**，
            但要**说出来**。静默跳过是"把生成物悄悄换掉的暗路"：谁都不知道
            模板这次没生效。日志一行，是这条暗路上唯一的灯。
        """
        if self.overwrite or self.injector.merge_source is not None:
            return False
        if not target_path.exists():
            return False
        if _is_generated_file(target_path):
            return False           # 自己的产物 → 重生（别让旧版本顶着）
        print(f"  [gen_uvm] 跳过非生成文件（不是 tool_uvm 产的，不动它）：{target_path}"
              f" —— 模板这次没往这儿写；若期望它被生成，请先移走该文件")
        return True

    def render_file(self, template_path: str, target_path: Path,
                    context: Dict[str, Any]) -> Optional[Path]:
        if self.should_skip(target_path):
            self.skipped += 1
            return None
        target_path.parent.mkdir(parents=True, exist_ok=True)
        # 文件头元数据（base_template.sv.j2 继承渲染用）
        context = dict(context)
        context.setdefault("meta", self.meta)
        context.setdefault("file_name", target_path.name)
        content = self.renderer.render(template_path, context)
        relpath = str(target_path.relative_to(self.output_dir))
        # Makefile 用 # 注释（banner 与 pragma 区域均如此）
        banner_prefix = "# " if target_path.name == "Makefile" else "// "
        content, _report = self.injector.inject(content, {}, relpath,
                                                banner_prefix=banner_prefix)
        # 原子写入：先写 .tmp 再 rename，防止生成中断截断旧文件（旧文件可能是 merge 源）
        tmp_path = target_path.with_suffix(target_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        os.replace(tmp_path, target_path)
        return target_path


class AgentRenderTask(RenderTask):
    def generate(self, agent: AgentModel) -> List[Path]:
        # 渲染前先让 IR 过一遍端口契约（`dir`/`direction` 拼错、空端口名）。
        # 只警告：空端口名会渲染成 `logic [-1:0] ;` 这种废接口，正是要拦住的那类漂移。
        _warn_ir_issues(f"agent {agent.name}",
                        validate_agent_ir(agent.to_uvm_ir()))
        if shadow_enabled():
            # 双写比对：IR 派生视图 vs 渲染 ctx —— 差异进日志**并落盘**
            # （`docs/ir_shadow_diff.json`）。只报告，不改变产物字节。
            issues = compare_agent_context(agent, {"agent": agent})
            warn_shadow(f"agent {agent.name}", issues)
            record_agent(self.output_dir, agent, {"agent": agent})
        rendered: List[Path] = []
        base_dir = self.output_dir / "agents" / f"{agent.name}_agent"
        # filelist.f 是「在 agent 目录里单独用」的（cd agents/<X>_agent && vlog -f filelist.f），
        # 故 base_pkg 走相对 agent 目录的路径，不依赖 $WORK_PATH（env 级 filelist 才用 $WORK_PATH）。
        _base_pkg = Path(TEMPLATES_DIR).resolve().parent / "base_pkg"
        context = {
            "agent": agent,
            "base_pkg_dir": _rel_or_abs(_base_pkg, base_dir),
            **agent.to_context(),
        }
        for entry in INTERFACE_TEMPLATES:
            template_path, target_pattern, extra_ctx = _split_template_entry(entry)
            ctx = {**context, **extra_ctx}
            target_name = target_pattern.format(agent_name=agent.name)
            target_path = base_dir / target_name
            result = self.render_file(template_path, target_path, ctx)
            if result is not None:
                rendered.append(result)

        # ── Agent 自闭环测试套件（master-drive → slave-monitor）──
        lb_dir = base_dir / "loopback"
        for template_path, target_pattern in AGENT_LOOPBACK_TEMPLATES:
            target_name = target_pattern.format(agent_name=agent.name)
            target_path = lb_dir / target_name
            result = self.render_file(template_path, target_path, context)
            if result is not None:
                rendered.append(result)
        if not self.should_skip(lb_dir / "filelist.f"):
            rendered.append(_generate_loopback_filelist(agent, lb_dir))

        # ── Generate human-readable markdown summary ──
        if not self.should_skip(base_dir / "summary.md"):
            rendered.append(_generate_agent_markdown(agent, base_dir))

        return rendered


def _generate_loopback_filelist(agent: "AgentModel", lb_dir: Path) -> Path:
    """Generate a compile filelist for the loopback self-test (master→slave)."""
    name = agent.name
    filelist_path = lb_dir / "filelist.f"
    lines = [
        "// Compile from the loopback directory: vlog -sv -f filelist.f",
        "+incdir+..",
        f"../1_interface/{name}_if.sv",
        f"../{name}_pkg.sv",
        f"{name}_loopback_env.sv",
        f"{name}_loopback_scb.sv",
        f"{name}_loopback_test.sv",
        f"{name}_loopback_tb.sv",
    ]
    filelist_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return filelist_path


def _generate_agent_markdown(agent: "AgentModel", base_dir: Path) -> Path:
    """Generate a human-readable summary.md for a single UVM agent."""
    md_path = base_dir / "summary.md"
    lines: List[str] = []
    lines.append(f"<!-- 自动生成 (tool_uvm v{__version__}) — 请勿直接修改本文件 -->")
    lines.append("")

    name = agent.name
    iface = agent.interface_name or agent.interface or name
    clk = agent.clock or "clk"
    rst = agent.reset or "rst"

    lines.append(f"# Agent: `{name}`")
    lines.append("")
    lines.append("| Property | Value |")
    lines.append("|----------|-------|")
    lines.append(f"| Interface | `{iface}` |")
    lines.append(f"| Clock | `{clk}` |")
    lines.append(f"| Reset | `{rst}` |")
    lines.append("| Activation | 由 env 级 `agents[].is_active` 决定（缺省 `UVM_ACTIVE`）；"
                 "loopback 套件固定 master-ACTIVE / slave-PASSIVE |")
    lines.append("")

    # ── Interface Ports ──
    ports = agent.ports
    if ports:
        lines.append("## 📌 Interface Ports")
        lines.append("")
        lines.append("| Dir | Name | Width | Description |")
        lines.append("|-----|------|-------|-------------|")
        for p in ports:
            d = str(p.get("dir", "?"))
            n = str(p.get("name", "?"))
            w_raw = p.get("width", 1)
            if isinstance(w_raw, str):
                w = f"`{w_raw}`"
            elif isinstance(w_raw, int) and w_raw > 1:
                w = f"[{w_raw-1}:0]"
            else:
                w = "1"
            desc = str(p.get("desc", "-"))
            lines.append(f"| {d} | `{n}` | {w} | {desc} |")
        lines.append("")

    # ── Parameters ──
    params = agent.parameters
    if params:
        lines.append("## ⚙️ Parameters")
        lines.append("")
        lines.append("| Parameter | Type | Default |")
        lines.append("|-----------|------|---------|")
        for p in params:
            pn = str(p.get("name", "?"))
            pt = str(p.get("type", "?"))
            pv = str(p.get("value", "-"))
            lines.append(f"| `{pn}` | `{pt}` | `{pv}` |")
        lines.append("")

    # ── Typedefs（名字 → 类型映射）──
    typedefs = agent.typedefs or {}
    if typedefs:
        lines.append("## 🏷️ Type Definitions")
        lines.append("")
        for tn, tv in typedefs.items():
            lines.append(f"- `{tn}` = `{tv}`")
        lines.append("")

    # ── Transaction Fields ──
    txn_vars = agent.transaction_vars
    if txn_vars:
        lines.append("## 📦 Transactions (`{name}_master_seq_item` / `{name}_slave_seq_item`)".format(name=name))
        lines.append("")
        lines.append("| Field | Type | Compare | Random |")
        lines.append("|-------|------|---------|--------|")
        for v in txn_vars:
            vn = str(v.get("name", "?"))
            vt = str(v.get("type", "?"))
            vc = "✓" if str(v.get("iscompare", "False")).lower() in ("true", "1") else "-"
            vr = "✓" if str(v.get("isrand", "False")).lower() in ("true", "1") else "-"
            lines.append(f"| `{vn}` | `{vt}` | {vc} | {vr} |")
        lines.append("")

    # ── Transaction Constraints ──
    txn_cons = agent.transaction_constraints or {}
    if isinstance(txn_cons, dict):
        for role in ("master", "slave"):
            role_cons = txn_cons.get(role, [])
            if role_cons:
                lines.append(f"### Constraints ({role})")
                lines.append("")
                for c in role_cons:
                    cn = c.get("name", "?")
                    cv = c.get("value", "?")
                    lines.append(f"- **`{cn}`**: `{cv}`")
                lines.append("")

    # ── Configuration Variables ──
    cfg_vars = agent.config_vars
    if cfg_vars:
        lines.append("## 🔧 Configuration (`{name}_config`)".format(name=name))
        lines.append("")
        lines.append("| Variable | Default | Description |")
        lines.append("|----------|---------|-------------|")
        for v in cfg_vars:
            vn = str(v.get("name", "?"))
            vd = str(v.get("default", "-"))
            vdesc = str(v.get("desc", v.get("description", "-")))
            lines.append(f"| `{vn}` | `{vd}` | {vdesc} |")
        lines.append("")

    # ── Response Info ──
    rsp = agent.response_info
    if rsp:
        lines.append("## 📬 Response Info")
        lines.append("")
        for k, val in rsp.items():
            lines.append(f"- **{k}**: `{val}`")
        lines.append("")

    # ── Generated File Inventory ──
    lines.append("## 📁 Generated File Inventory")
    lines.append("")
    lines.append("| # | File | Role |")
    lines.append("|---|------|------|")
    file_entries = [
        (f"1_interface/{name}_if.sv", "Interface: internal logic + master/slave/monitor clocking + modport"),
        (f"2_config/{name}_port_config.sv", "Port config: drive/response 统一（port_kind 区分端口类型）"),
        (f"5_agent/{name}_system_config.sv", "System config: aggregates master_cfgs[] / slave_cfgs[]"),
        (f"3_transaction_sequencer/{name}_base_seq_item.sv", "Base transaction: xact_type + base_transaction_vars（master/slave 共用）"),
        (f"3_transaction_sequencer/{name}_master_seq_item.sv", "Master transaction"),
        (f"3_transaction_sequencer/{name}_slave_seq_item.sv", "Slave transaction (request + response control)"),
        (f"3_transaction_sequencer/{name}_master_sequencer.sv", "Master sequencer"),
        (f"3_transaction_sequencer/{name}_slave_sequencer.sv", "Slave sequencer (+ req_fifo, event-driven)"),
        (f"4_driver_monitor/{name}_master_driver.sv", "Master driver"),
        (f"4_driver_monitor/{name}_slave_driver.sv", "Slave driver (responds)"),
        (f"4_driver_monitor/{name}_port_monitor.sv", "Port monitor: port_kind 分支（SLAVE 侧 → slave_mon_ap + req_fifo）"),
        (f"5_agent/{name}_master_agent.sv", "Master agent"),
        (f"5_agent/{name}_slave_agent.sv", "Slave agent"),
        (f"5_agent/{name}_system_vsqr.sv", "System virtual sequencer: 持有同协议全部 master/slave 子 sequencer 句柄"),
        (f"5_agent/{name}_system_monitor.sv", "System monitor: 直接嗅探 system_if 全端口（{kind, index} 标签）"),
        (f"7_sequence/{name}_master_sequence.sv", "Master sequence"),
        (f"7_sequence/{name}_slave_sequence.sv", "Slave sequence (memory model)"),
        (f"8_ral/{name}_reg_adapter.sv", "RAL reg adapter"),
        (f"{name}_pkg.sv", "Package: includes all class files"),
        ("filelist.f", "Compile order: interface → package"),
    ]
    for i, (fname, desc) in enumerate(file_entries, 1):
        lines.append(f"| {i} | `{fname}` | {desc} |")
    lines.append("")

    # ── Compile / Sim Quick Reference ──
    lines.append("## 🚀 Quick Start")
    lines.append("")
    lines.append("```bash")
    lines.append(f"# Compile (from the agent directory)")
    lines.append(f"vlog -sv -f filelist.f")
    lines.append("")
    lines.append(f"# Env/bench level compile+sim is handled by the environment/bench tooling")
    lines.append("```")
    lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def _generate_output_readme(output_dir: Path, agents: List["AgentModel"],
                            environments: List["EnvironmentModel"] = None,
                            benches: List["BenchModel"] = None,
                            harnesses: List["HarnessModel"] = None,
                            sc_preds: List["ScPredModel"] = None) -> Path:
    """Generate an overall README.md at the output root indexing all agents."""
    readme_path = output_dir / "README.md"
    lines: List[str] = []
    lines.append(f"<!-- 自动生成 (tool_uvm v{__version__}) — 请勿直接修改本文件 -->")

    lines.append("# UVM Verification Environment — Generated Output")
    lines.append("")
    # 与文件头时间戳同源：`reproducible_now()`（见其说明）。README 也在生成物树里，
    # 用墙上时钟的话它同样会让「同一输入两次跑」的内容哈希对不上。
    _gen_ts = reproducible_now()
    lines.append(f"**Generated**: {_gen_ts}" if _gen_ts else "**Generated**: (未钉时间戳；设 SOURCE_DATE_EPOCH 可写入)")
    lines.append("")
    lines.append("---")
    lines.append("")

    # ── Directory Structure ──
    lines.append("## 📂 Directory Structure")
    lines.append("")
    lines.append("```")
    lines.append("output/")
    lines.append("├── README.md              ← this file")
    if agents:
        lines.append("├── agents/")
        for a in agents:
            lines.append(f"│   ├── {a.name}_agent/")
            lines.append(f"│   │   ├── summary.md     ← agent design summary")
            lines.append(f"│   │   ├── {a.name}_*.sv  ← UVM components")
            lines.append(f"│   │   └── loopback/      ← self-test testbench")
    lines.append("├── env/                    ← environment + tests + sequences")
    lines.append("├── env/rtl_sc/             ← Scoreboard Predictor (monitor + prod + env wrapper)")
    lines.append("├── bench/                  ← top-level testbench")
    lines.append("├── inputs/                 ← tool input files")
    lines.append("│   ├── yaml/")
    lines.append("│   │   ├── uvm/            ← UVM agent/env/bench YAML")
    lines.append("│   │   ├── agent_test/     ← agent loopback test YAML")
    lines.append("│   │   └── dut_test/       ← DUT regression test YAML")
    lines.append("│   └── filelists/          ← compile filelists")
    lines.append("├── docs/                   ← pipeline documentation")
    lines.append("├── build/                  ← compiled work library + test work areas")
    lines.append("├── sim/                    ← simulation artifacts")
    lines.append("│   ├── agent/              ← agent loopback logs + waves")
    lines.append("│   └── dut/                ← DUT regression logs + waves")
    lines.append("├── quality_report.json     ← quality check results")
    lines.append("└── sim_*.log / wave_*.wlf  ← simulation artifacts")
    lines.append("```")
    lines.append("")

    # ── Agent Summary Table ──
    if agents:
        lines.append("## 🤖 Agents")
        lines.append("")
        lines.append("| Agent | Interface | Ports | Transaction Fields | Constraints |")
        lines.append("|-------|-----------|-------|--------------------|-------------|")
        for a in agents:
            iface = a.interface_name or a.interface or a.name
            n_ports = len(a.ports) if a.ports else 0
            n_txn = len(a.transaction_vars) if a.transaction_vars else 0
            _tc = a.transaction_constraints or {}
            n_cons = (len(_tc.get("master", [])) + len(_tc.get("slave", []))) if isinstance(_tc, dict) else 0
            lines.append(f"| [{a.name}](agents/{a.name}_agent/summary.md) | `{iface}` | {n_ports} | {n_txn} | {n_cons} |")
        lines.append("")

    # ── Per-Agent Detail ──
    if agents:
        lines.append("## 📋 Agent Details")
        lines.append("")
        for a in agents:
            lines.append(f"### [{a.name}](agents/{a.name}_agent/summary.md)")
            lines.append("")
            lines.append(f"- **Interface**: `{a.interface_name or a.interface or a.name}`")
            lines.append(f"- **Clock**: `{a.clock or 'clk'}`  |  **Reset**: `{a.reset or 'rst'}`")
            lines.append("- **Activation**: env 级 `agents[].is_active` 决定（缺省 `UVM_ACTIVE`）；"
                         "loopback 固定 master-ACTIVE / slave-PASSIVE")

            if a.ports:
                port_list = ", ".join(
                    f"`{p.get('name','?')}`({p.get('dir','?')})"
                    for p in a.ports[:8])
                if len(a.ports) > 8:
                    port_list += f" +{len(a.ports) - 8} more"
                lines.append(f"- **Ports**: {port_list}")

            if a.transaction_vars:
                txn_list = ", ".join(
                    f"`{v.get('name','?')}`"
                    for v in a.transaction_vars[:6])
                if len(a.transaction_vars) > 6:
                    txn_list += f" +{len(a.transaction_vars) - 6} more"
                lines.append(f"- **Transaction fields**: {txn_list}")

            _tc = a.transaction_constraints or {}
            _cons_all = (_tc.get("master", []) + _tc.get("slave", [])) if isinstance(_tc, dict) else list(_tc)
            if _cons_all:
                cons_list = ", ".join(
                    f"`{c.get('name','?')}`"
                    for c in _cons_all[:4])
                lines.append(f"- **Constraints**: {cons_list}")

            lines.append(f"- **Files**: `agents/{a.name}_agent/` (13 .sv + loopback)")
            lines.append("")

    # ── Environment ──
    if environments:
        lines.append("## 🌐 Environment")
        lines.append("")
        for env in environments:
            lines.append(f"- **{env.env_name}** — {len(env.agents) if env.agents else 0} agents")
            if env.scoreboards:
                lines.append(f"  - Scoreboards: {len(env.scoreboards)}")
            if env.tlm_connections:
                lines.append(f"  - TLM connections: {len(env.tlm_connections)}")
            if env.register_model and env.register_model.get("components"):
                comps = ", ".join(
                    f"`{c['name']}` (`{c['type']}`)" for c in env.register_model["components"])
                lines.append(f"  - Register model: {comps}")
            if env.analysis_exports:
                names = ", ".join(f"`{p['name']}`" for p in env.analysis_exports)
                lines.append(f"  - Analysis exports: {names}")
            if env.analysis_ports:
                names = ", ".join(f"`{p['name']}`" for p in env.analysis_ports)
                lines.append(f"  - Analysis ports: {names}")
            lines.append(f"  - Files: `env/{env.env_name}*.sv`")
        lines.append("")

    # ── Harness ──
    if harnesses:
        lines.append("## 🔌 UVM Harness (bind 式自连接)")
        lines.append("")
        for h in harnesses:
            lines.append(f"- **{h.name}** — bind 到 `{h.bind_to}`")
            if h.interfaces:
                for i in h.interfaces:
                    arr = f"[{i['count']}-1:0]" if i["count"] != 1 else ""
                    lines.append(f"  - `{i['type']} {i['name']}{arr}` → agent path `.{(i['agent_path'])}`")
            if h.sub_harnesses:
                lines.append(f"  - Sub-harnesses: {len(h.sub_harnesses)}")
            lines.append(f"  - File: `bench/{h.name}.sv`")
        lines.append("")

    # ── Bench ──
    if benches:
        lines.append("## 🔌 Testbench Top")
        lines.append("")
        for b in benches:
            lines.append(f"- **{b.name}** — env: `{b.env_name}`, timeout: `{b.timeout}`")
            if b.harness and b.harness.get("bind_to"):
                lines.append(f"  - DUT: `{b.harness['bind_to']}` (instance: `u_dut`)")
            agents_list = list(b.agents.keys()) if isinstance(b.agents, dict) else []
            if agents_list:
                lines.append(f"  - Agents: {', '.join(agents_list)}")
            lines.append(f"  - File: `bench/{b.name}_tb_top.sv`")
        lines.append("")

    # ── Quality ──
    lines.append("## ✅ Quality Checks")
    lines.append("")
    lines.append("See [`quality_report.json`](quality_report.json) for detailed results:")
    lines.append("")
    lines.append("| Check | What | Pass Criteria |")
    lines.append("|-------|------|---------------|")
    lines.append("| Static | All expected files exist | 0 missing files |")
    lines.append("| Compile | `vlog` passes for agent loopback TB | 0 errors |")
    lines.append("| Loopback | Driver→Monitor closed-loop simulation | matched > 0, 0 UVM_ERROR |")
    lines.append("")

    lines.append("---")
    lines.append(f"*Generated by {COMPANY_TRADEMARK} UVM Generator*")
    lines.append("")

    readme_path.write_text("\n".join(lines), encoding="utf-8")
    return readme_path


class EnvironmentRenderTask(RenderTask):
    def generate(self, environment: EnvironmentModel) -> List[Path]:
        # env 级 IR：检查 agent 重名 / 身份缺失 / test 引用不存在的 agent。
        # 端口在 interface 侧声明，这里不要求端口（`require_ports=False`）。
        _warn_ir_issues(f"environment {environment.env_name}",
                        validate_ir(environment.to_uvm_ir(), require_ports=False))
        if shadow_enabled():
            issues = compare_environment_context(
                environment, {"environment": environment})
            warn_shadow(f"environment {environment.env_name}", issues)
            record_environment(self.output_dir, environment,
                               {"environment": environment})
        rendered: List[Path] = []
        env_dir = self.output_dir / "env"
        context = {"environment": environment, **environment.to_context()}
        # 补充 agent 的 transaction_vars（env 渲染需要，供 env_cov 生成 coverpoint/cross）
        self._enrich_agents_transaction_vars(context)
        self._check_stimulus_bindings(environment, context)

        for template_path, target_pattern in ENVIRONMENT_ROOT_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = env_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        tests_dir = env_dir / "tests"
        for template_path, target_pattern in ENVIRONMENT_TEST_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = tests_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        # 属性测试：只在清单里真的写了 tests 时才产那个文件。
        # 空列表还产一个空壳文件的话，apb 那类没有属性的工程会多出一个
        # 「看着像有东西其实什么都没有」的文件。
        if environment.tests:
            for template_path, target_pattern in ENVIRONMENT_ATTR_TEST_TEMPLATES:
                target_name = target_pattern.format(env_name=environment.env_name)
                rendered.append(self.render_file(template_path,
                                                 tests_dir / target_name, context))
        if environment.batches:
            for template_path, target_pattern in ENVIRONMENT_BATCH_TEST_TEMPLATES:
                target_name = target_pattern.format(env_name=environment.env_name)
                rendered.append(self.render_file(template_path,
                                                 tests_dir / target_name, context))

        # 寄存器（CSR）测试：只在配了寄存器模型时才产（模板自身也有 `{% if %}` 兜底，
        # 但这里先判一次，避免产出一堆空文件）。
        if context.get("register_model") and context["register_model"].get("reg_block"):
            for template_path, target_pattern in ENVIRONMENT_REG_TEST_TEMPLATES:
                target_name = target_pattern.format(env_name=environment.env_name)
                rendered.append(self.render_file(template_path,
                                                 tests_dir / target_name, context))

        seqs_dir = env_dir / "seqs"
        for template_path, target_pattern in ENVIRONMENT_SEQ_TEMPLATES:
            target_name = target_pattern.format(env_name=environment.env_name)
            target_path = seqs_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))

        # 生成 Reg 自检序列（register_model 存在时，P1-3）
        if environment.register_model and environment.register_model.get("reg_block"):
            reg_smoke_path = seqs_dir / f"{environment.env_name}_reg_smoke_seq.sv"
            result = self.render_file(
                "environment_templates/reg_smoke_seq.sv.j2",
                reg_smoke_path, context)
            if result is not None:
                rendered.append(result)

        # scoreboard 一律由 sb_type 指向外部类，本工具不生成 scb 文件

        return rendered

    def _check_stimulus_bindings(self, environment: "EnvironmentModel",
                                 context: Dict[str, Any]) -> None:
        """`stimulus.field` 必须在某个 master agent 的事务上**真的**存在。

        不查的话，`stimulus: {field: instr_typ}` 这种笔误照样能生成：test 会
        `set("instr_typ_int", …)`，而**没有任何 sequence 读它** —— 编译通过、
        回归全绿、每个属性 test 的激励还是一样的。那正是"属性 test 是死标签"
        这个 bug 的复发方式，所以这里必须出声（只警告，不阻断生成）。

        没有事务定义（例如只给了 interface 清单）时无法判定，不误报。
        """
        drivable = set()
        any_txn = False
        for agent in context.get("agents") or []:
            tvars = getattr(agent, "transaction_vars", None)
            if tvars is None and isinstance(agent, dict):
                tvars = agent.get("transaction_vars")
            for v in tvars or []:
                if not isinstance(v, dict) or not v.get("name"):
                    continue
                any_txn = True
                # slave 字段由 DUT/从端驱动，master sequence 约束不上
                if str(v.get("is_master", "True")) == "True":
                    drivable.add(str(v["name"]))
        # 完全没有事务定义（例如只给了 interface 清单）时无法判定，不误报。
        # 但"有事务、只是没有 master 字段"要照报 —— 否则绑到 slave 字段上的
        # 笔误会被这句提前返回吞掉。
        if not any_txn:
            return
        unknown = sorted({t["field"] for t in (environment.tests or [])
                          if t.get("field") and t["field"] not in drivable})
        if unknown:
            print("  [gen_uvm] Warning: stimulus.field 在 master 事务上不存在："
                  f"{', '.join(unknown)} —— 这些属性 test 的激励不会生效"
                  f"（可绑定：{', '.join(sorted(drivable))}）", flush=True)

    def _enrich_agents_transaction_vars(self, context: Dict[str, Any]):
        """从 agent yaml 读取 transaction_vars + 策略包 coverage_bins，合并进 context。

        parse_environment_model 只填 agent 的 name/interface，transaction_vars 在
        独立的 agent yaml 里。env_cov 模板需要 transaction_vars 生成 coverpoint，
        coverage_bins（策略包）生成语义化 cross。
        """
        import yaml as _yaml
        yaml_dir = self.output_dir / "inputs" / "yaml" / "uvm"
        agents = context.get("agents", [])
        if not isinstance(agents, (list, tuple)):
            return
        for agent in agents:
            name = getattr(agent, "name", None) or (agent.get("name", "") if isinstance(agent, dict) else "")
            if not name:
                continue
            agent_yaml = yaml_dir / f"{name}.yaml"
            if not agent_yaml.exists():
                continue
            try:
                data = _yaml.safe_load(agent_yaml.read_text(encoding="utf-8", errors="replace")) or {}
                # **transaction_vars 住在 `interfaces:` 里面**：`tool_find_spec_yaml`
                # 生成的 agent yaml 是 `interfaces: {name, clock, ports, transaction_vars}`。
                # 原来只读文档顶层的 `data.get("transaction_vars")` —— 恒为 None，
                # 于是 env 里每个 `covergroup cg_<agent>` 都是**空壳**
                #（渲染成 `covergroup cg_apb; endgroup`），功能覆盖率永远是 0%。
                # 顶层那份是手写 agent yaml 的写法，一并兼容。
                _iface_doc = data.get("interfaces")
                if isinstance(_iface_doc, dict):
                    txn_vars = _iface_doc.get("transaction_vars") or []
                else:
                    txn_vars = data.get("transaction_vars") or []
                if hasattr(agent, "transaction_vars"):
                    agent.transaction_vars = txn_vars
                elif isinstance(agent, dict):
                    agent["transaction_vars"] = txn_vars
            except Exception:
                pass
        # 读策略包的语义 bin（verify agent 落盘的 env_cov_bins.yaml）。
        data = read_env_cov_bins(self.output_dir)
        context["coverage_bins"] = data.get("cov_bins") \
            or data.get("coverage_bins") or []
        # `field_bins`: 字段名 → 显式 bin 表（`[{name, value}]`），来自 **case 模型**
        # （verify 阶段注入，见 `src/executors/verify/main.py`）。有了它就按模型声明
        # 的边界值分箱，没有就退回模板里那套"值类自动分箱"（0/1/其余）。
        _fb = data.get("field_bins")
        context["coverage_field_bins"] = _fb if isinstance(_fb, dict) else {}
        # 测试点位图 + 时序判据（verify 落 `env_cov_bins.yaml` 的 `tp_bitmap`）：
        # 位序 → TP，以及每个 bit 在哪个信号/bin 上置位、有没有时序窗口。
        _tb = data.get("tp_bitmap")
        context["coverage_tp_bitmap"] = _tb if isinstance(_tb, dict) else {}
        self._add_coverage_dut_context(context)


class ConstraintRenderTask(RenderTask):
    def generate(self, constraint: ConstraintModel) -> List[Path]:
        rendered: List[Path] = []
        cons_dir = self.output_dir / "env" / "cons"
        context = constraint.to_context()
        # **模板统一读 `environment.env_name`**（与 `env_pkg.sv.j2` 同一个变量名）——
        # 原来这 5 个模板读的是 `project.name` / `project.env_name`，那是**约束模型
        # 自己那份拷贝**，与真环境名是两个来源。同名的东西有两条出处就会漂，
        # 而漂了的表现是类名对不上（`_policy_factory` 找不到之类），编译才报。
        context["environment"] = {"env_name": constraint.env_name}
        for template_path, target_pattern in ENV_CONSTRAINT_TEMPLATES:
            # 文件名也只用 `env_name`（`project_name` 那套已下线）——与其余环境产物
            # （`{env_name}_config.sv` / `{env_name}_coverage.sv` …）同一个命名空间，
            # 不再是"约束模型自己一份名字"。
            target_name = target_pattern.format(env_name=constraint.env_name)
            target_path = cons_dir / target_name
            rendered.append(self.render_file(template_path, target_path, context))
        return rendered


class BenchRenderTask(RenderTask):
    def generate(self, bench: BenchModel) -> Path:
        bench_dir = self.output_dir / "bench"
        target_path = bench_dir / f"{bench.name}_tb_top.sv"
        ctx = {"bench": bench.to_context()}
        # Add agents as a list for easy template iteration
        ctx["agents"] = [
            v.to_context() if isinstance(v, BenchAgentEntry) else v
            for v in bench.agents.values()
        ]
        # DUT 覆盖率接口：tb_top 要把 bind 出来的实例挂进 config_db，组件才拿得到
        # 句柄。**与 env_cov 读的是同一份契约**（`read_env_cov_bins`）—— 两边各推
        # 一次名字就会漂，而漂的表现是"覆盖率永远 0%、编译不报错"。
        self._add_coverage_dut_context(ctx)
        return self.render_file(BENCH_TEMPLATES[0][0], target_path, ctx)


class HarnessRenderTask(RenderTask):
    def generate(self, harness: HarnessModel) -> Optional[Path]:
        harness_dir = self.output_dir / "bench"
        target_path = harness_dir / f"{harness.name}.sv"
        ctx = {"harness": harness, **harness.to_context()}
        return self.render_file(HARNESS_TEMPLATES[0][0], target_path, ctx)


class RenderTaskFactory:
    @staticmethod
    def create(task_type: str, renderer: JinjaRenderer, output_dir: Path,
               injector: Optional[RegionInjector] = None,
               overwrite: bool = False,
               meta: Optional[Dict[str, str]] = None) -> RenderTask:
        if task_type == "agent":
            return AgentRenderTask(renderer, output_dir, injector, overwrite, meta)
        if task_type == "environment":
            return EnvironmentRenderTask(renderer, output_dir, injector, overwrite, meta)
        if task_type == "constraint":
            return ConstraintRenderTask(renderer, output_dir, injector, overwrite, meta)
        if task_type == "bench":
            return BenchRenderTask(renderer, output_dir, injector, overwrite, meta)
        if task_type == "harness":
            return HarnessRenderTask(renderer, output_dir, injector, overwrite, meta)
        raise ValueError(f"Unknown task type: {task_type}")


def _type_to_pkg(type_name):
    """从 seq_item 类型名推断 agent package 名：xxx_[master/slave]_seq_item → xxx_pkg。"""
    for suffix in ("_master_seq_item", "_slave_seq_item", "_seq_item"):
        if type_name.endswith(suffix):
            return type_name[: -len(suffix)] + "_pkg"
    return ""


def _rel_or_abs(target: Path, start: Path) -> str:
    """`os.path.relpath` 的跨盘安全版（结果一律正斜杠）。

    Windows 上 `os.path.relpath(r"D:\\repo\\base_pkg", r"C:\\tmp\\out")` 直接抛
    `ValueError: path is on mount 'D:', start on mount 'C:'` —— 只要**生成目录和
    仓库不在同一个盘**就炸（pytest 的 tmp_path 在 C:，仓库在 D:，一跑就是一片红）。
    相对路径只是为了让生成物自包含；跨盘时根本表达不了，退回绝对路径即可，
    vlog / make 都吃得下。
    """
    try:
        return os.path.relpath(target, start).replace("\\", "/")
    except ValueError:
        return str(target).replace("\\", "/")
