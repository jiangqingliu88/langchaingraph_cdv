#!/usr/bin/env python3
"""gen_uvm.py
Generate UVM SystemVerilog from YAML interface and environment descriptions.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import zlib
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: PyYAML is required. Install with: pip install pyyaml"
    ) from exc

try:
    from jinja2 import Environment, FileSystemLoader, pass_context
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: Jinja2 is required. Install with: pip install jinja2"
    ) from exc

try:
    from .semantic_check import SemanticValidator  # 包内导入（python -m 路径）
except ImportError:  # 直接脚本执行（python gen_uvm.py）
    from semantic_check import SemanticValidator

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

__version__ = "0.1.0"

# ════════════════════════════════════════════════════════════
# 商标与版权（只改这里一个变量，全脚本生效）
# YAML 顶层 meta.company / meta.rights 可覆盖
# ════════════════════════════════════════════════════════════
COMPANY_TRADEMARK = "SignOffAI（功能签核）"   # ← 替换成你的公司/组织名
COPYRIGHT_YEAR = "2026"


def reproducible_now() -> str:
    """模板里 `now()` 的实现 —— **确定性**，不再取墙上时钟。

    为什么必须确定：这个值会写进**每个**生成文件的头注释
    （`base_templates/base_template.sv.j2` 的「创建时间 / 修改时间」）。
    取墙上时钟的话，同一份输入跑两次得到不同的字节 —— 实测 86 个生成文件里
    76 个内容哈希不同。而证据链/产物比对正是靠内容哈希判断「这个产物有没有被
    动过」，假差异会让它失去意义；「可复现」这个卖点也就落不了地。

    规则对齐 reproducible-builds 的 `SOURCE_DATE_EPOCH` 约定：

      · 设了 `SOURCE_DATE_EPOCH`（Unix 秒）→ 用它格式化。CI 想钉死时间、
        或想要真实时间，都通过这个变量显式给。
      · 没设 → 返回**空串**，模板里那两行整行不输出（见模板改动）。
        默认就是可复现的，而不是默认不可复现、要用户自己去关。

    想做「确定性但带时间」，用 YAML 的 `meta.created` / `meta.modified` ——
    模板已经支持这两个键优先于 `now()`（`meta.created | default('') or now()`）。
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if not epoch:
        return ""
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        # 值给错了不该让生成失败 —— 退回不可复现也要比炸掉好，但要出声
        print(f"[warn] SOURCE_DATE_EPOCH 不是合法 Unix 秒: {epoch!r}，本次不写时间戳")
        return ""

# ── 文件头元数据（base_templates/base_template.sv.j2 渲染用）──
DEFAULT_META = {
    "company": COMPANY_TRADEMARK,
    "rights": (f"Copyright © {COPYRIGHT_YEAR} {COMPANY_TRADEMARK}. All rights reserved. "
               "未经书面许可，禁止复制、修改、分发或用于商业用途。"),
    "author": "-",
    "email": "-",
}

# ============================================================
#  pragma custom 自定义代码区域（细粒度语义槽，无粗区）
# ============================================================
# 槽位在单文件内必须唯一、不嵌套、begin/end 成对；回填优先级:
#   merge_source 旧文件内容 > 模板默认内容
# （YAML custom_code 注入已下线；区域内容只能靠 -m/--merge_source 手改保留）
# 生成文件带 BANNER 签名；-c/--clean 只删除带签名的文件，绝不碰手写文件。

def _make_banner(prefix: str = "// ") -> str:
    """生成文件签名 banner（按目标文件类型选注释前缀：SV/filelist 用 //，Makefile 用 #）。"""
    return "\n".join([
        f"{prefix}════════════════════════════════════════════════════════════════",
        f"{prefix}自动生成 (tool_uvm v{__version__}) — 请勿直接修改；"
        f"自定义代码写入 pragma custom 区域",
        f"{prefix}════════════════════════════════════════════════════════════════",
    ]) + "\n"


BANNER = _make_banner("// ")
BANNER_MARKER = "自动生成 (tool_uvm"

REGION_MARKER = re.compile(r"^\s*//\s*pragma\s+custom\s+(\w+)\s+(begin|end)\s*$")


class RegionError(Exception):
    """pragma custom 区域错误（未闭合 / 嵌套 / 同名重复 / 旧源无匹配）。"""


@dataclass
class MergeBlockInfo:
    slot: str
    source: str   # "yaml" | "merged" | "default"
    lines: int


@dataclass
class MergeFileReport:
    relpath: str
    blocks: List[MergeBlockInfo] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)


class RegionInjector:
    """pragma custom 区域注入器。

    模板静态写空区域（slot 文件内唯一）；渲染后按优先级回填。
    -m/--merge_source 时预提取旧文件区域表，按目标相对路径索引。
    """

    def __init__(self, merge_source: Optional[Path] = None,
                 skip_missing: bool = False,
                 debug_dir: Optional[Path] = None,
                 report: Optional[List[MergeFileReport]] = None) -> None:
        self.merge_source = Path(merge_source) if merge_source else None
        self.skip_missing = skip_missing
        self.debug_dir = Path(debug_dir) if debug_dir else None
        self.report: List[MergeFileReport] = report if report is not None else []
        self.load_errors: List[str] = []   # merge_source 中区域解析失败的文件（不参与合并）
        self._old_blocks: Dict[str, Dict[str, str]] = {}
        if self.merge_source:
            self._load_merge_source(self.merge_source)

    # ── 提取 ──
    @staticmethod
    def extract_blocks(text: str) -> Dict[str, str]:
        """提取 text 中全部 pragma custom 区域 → {slot: 内容}。

        未闭合 / 嵌套 / 同名重复 → RegionError。
        """
        blocks: Dict[str, str] = {}
        current: Optional[str] = None
        buf: List[str] = []
        for lineno, line in enumerate(text.splitlines(), 1):
            m = REGION_MARKER.match(line)
            if m:
                slot, kind = m.group(1), m.group(2)
                if kind == "begin":
                    if current is not None:
                        raise RegionError(
                            f"line {lineno}: region '{slot}' nested inside '{current}'")
                    if slot in blocks:
                        raise RegionError(f"line {lineno}: duplicate region '{slot}'")
                    current = slot
                    buf = []
                else:
                    if current != slot:
                        raise RegionError(
                            f"line {lineno}: region end '{slot}' without begin "
                            f"(open: '{current}')")
                    blocks[slot] = "\n".join(buf)
                    current = None
            elif current is not None:
                buf.append(line)
        if current is not None:
            raise RegionError(f"region '{current}' not closed")
        return blocks

    def _load_merge_source(self, root: Path) -> None:
        """扫描 merge_source 目录，提取每个文件的区域表（按目标相对路径索引）。"""
        if not root.is_dir():
            raise RegionError(f"merge source directory not found: {root}")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".sv", ".svh"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            try:
                blocks = self.extract_blocks(text)
            except RegionError as exc:
                self.load_errors.append(f"[{path.relative_to(root)}] {exc}")
                continue  # 坏区域文件不参与合并（错误记录进报告）
            if blocks:
                self._old_blocks[str(path.relative_to(root))] = blocks

    # ── 注入 ──
    def inject(self, rendered: str, defaults: Dict[str, str],
               relpath: str, add_banner: bool = True,
               banner_prefix: str = "// ") -> Tuple[str, MergeFileReport]:
        """渲染产物 → 注入后文本。

        defaults = 外部提供的区域内容（非空 → "yaml" 源，每次生成覆盖）。
        生成流程已不再从 YAML 取值（custom_code 下线），该形参仅保留给程序化调用。
        模板区域内已有的默认内容作为最后兜底（"default" 源）。
        """
        report = MergeFileReport(relpath=relpath)
        old = self._old_blocks.get(relpath, {})
        out: List[str] = []
        current: Optional[str] = None
        inner: List[str] = []
        seen: List[str] = []

        for lineno, line in enumerate(rendered.splitlines(), 1):
            m = REGION_MARKER.match(line)
            if m:
                slot, kind = m.group(1), m.group(2)
                if kind == "begin":
                    if current is not None:
                        raise RegionError(
                            f"line {lineno}: region '{slot}' nested inside '{current}'")
                    if slot in seen:
                        raise RegionError(f"line {lineno}: duplicate region '{slot}'")
                    current = slot
                    inner = []
                    out.append(line)
                else:
                    if current != slot:
                        raise RegionError(
                            f"line {lineno}: region end '{slot}' without begin "
                            f"(open: '{current}')")
                    yaml_val = (defaults.get(slot) or "").strip() if defaults else ""
                    old_val = old.get(slot, "")
                    if yaml_val:
                        content, source = yaml_val, "yaml"
                    elif old_val:
                        content, source = old_val, "merged"
                    else:
                        content, source = "\n".join(inner), "default"
                    out.extend(content.splitlines())
                    out.append(line)
                    report.blocks.append(
                        MergeBlockInfo(slot, source, len(content.splitlines())))
                    seen.append(slot)
                    current = None
            elif current is not None:
                inner.append(line)
            else:
                out.append(line)
        if current is not None:
            raise RegionError(f"region '{current}' not closed")

        # 旧文件多出的区域（新模板没有对应槽）
        for slot in sorted(old):
            if slot not in seen:
                if not self.skip_missing:
                    raise RegionError(
                        f"[{relpath}] block '{slot}' found in old source has no "
                        f"matching region in new output "
                        f"(use --merge_skip_missing_blocks to continue)")
                report.missing.append(slot)

        text = "\n".join(out) + "\n"
        if add_banner and BANNER_MARKER not in text:
            text = _make_banner(banner_prefix) + "\n" + text
        if self.debug_dir is not None:
            debug_path = self.debug_dir / relpath
            debug_path.parent.mkdir(parents=True, exist_ok=True)
            debug_path.write_text(rendered + "\n", encoding="utf-8")
        self.report.append(report)
        return text, report


def backup_merge_source(merge_source: Path) -> Path:
    """备份 merge_source 目录 → <merge_source>_backup_<时间戳>。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = merge_source.with_name(f"{merge_source.name}_backup_{ts}")
    shutil.copytree(merge_source, backup)
    return backup


def _is_generated_file(path: Path) -> bool:
    """文件是否带生成签名（clean 只删除此类文件）。"""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    except OSError:
        return False
    return BANNER_MARKER in head


def _write_report_json(output_root: Path, *, generated: int, skipped: int,
                       validation_issues: List[Any], merge_reports: List[Any],
                       load_errors: List[str], gate_results: List[Dict[str, str]],
                       schema_issues: Optional[List[Any]] = None,
                       inputs: Optional[List[Path]] = None) -> Path:
    """P2-4: 结构化生成报告（供 Agent 决策 / 签核证据包引用）。"""
    report = {
        "tool": "tool_uvm",
        "version": __version__,
        "inputs": [str(p) for p in (inputs or [])],
        "generated": generated,
        "skipped": skipped,
        "schema": {
            "errors": [i.__dict__ for i in (schema_issues or []) if i.severity == "error"],
            "warnings": [i.__dict__ for i in (schema_issues or []) if i.severity == "warning"],
        },
        "validation": {
            "errors": [i.__dict__ for i in validation_issues if i.severity == "error"],
            "warnings": [i.__dict__ for i in validation_issues if i.severity == "warning"],
        },
        "merge": {
            "blocks": [
                {"file": r.relpath,
                 "items": [b.__dict__ for b in r.blocks],
                 "missing": r.missing}
                for r in merge_reports if r.blocks or r.missing
            ],
            "load_errors": load_errors,
        },
        "gate": gate_results,
    }
    report_path = output_root / "generation_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    return report_path


def _clean_generated(dest_root: Path) -> int:
    """-c/--clean：删除 dest_dir 下所有带签名的生成文件，并清理空目录。"""
    if not dest_root.is_dir():
        return 0
    removed = 0
    for path in sorted(dest_root.rglob("*"), reverse=True):
        if path.is_file() and _is_generated_file(path):
            path.unlink()
            removed += 1
    for path in sorted(dest_root.rglob("*"), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return removed

# AXI-VIP 风格：编号分层目录 + master/slave 完全分离
INTERFACE_TEMPLATES = [
    ("interface_templates/interface.sv.j2", "1_interface/{agent_name}_if.sv"),
    ("interface_templates/interface_system.j2", "1_interface/{agent_name}_system_if.sv"),

    # 单类合并模板（不区分 master/slave）
    ("interface_templates/port_config.sv.j2", "2_config/{agent_name}_port_config.sv"),

    # base 必须排在 master/slave 之前：派生类要引用基类的 xact_type_e / 字段，
    # SystemVerilog 要求先声明后使用。
    ("interface_templates/sequence_item_base.sv.j2", "3_transaction_sequencer/{agent_name}_base_seq_item.sv"),
    ("interface_templates/seq_item_master.sv.j2", "3_transaction_sequencer/{agent_name}_master_seq_item.sv"),
    ("interface_templates/seq_item_slave.sv.j2",  "3_transaction_sequencer/{agent_name}_slave_seq_item.sv"),
    ("interface_templates/sequencer_master.sv.j2", "3_transaction_sequencer/{agent_name}_master_sequencer.sv"),
    ("interface_templates/sequencer_slave.sv.j2",  "3_transaction_sequencer/{agent_name}_slave_sequencer.sv"),

    ("interface_templates/driver_master.sv.j2", "4_driver_monitor/{agent_name}_master_driver.sv"),
    ("interface_templates/driver_slave.sv.j2",  "4_driver_monitor/{agent_name}_slave_driver.sv"),
    ("interface_templates/port_monitor.sv.j2", "4_driver_monitor/{agent_name}_port_monitor.sv"),

    ("interface_templates/agent_master.sv.j2", "5_agent/{agent_name}_master_agent.sv"),
    ("interface_templates/agent_slave.sv.j2",  "5_agent/{agent_name}_slave_agent.sv"),
    ("interface_templates/config_system.sv.j2", "5_agent/{agent_name}_system_config.sv"),
    # vsqr 必须在 system_env 之前：env 持有 vsqr 句柄，vsqr 不引用 env（单向依赖，
    # 见模板头部说明），故先声明 vsqr 才能让 env 使用它的类型。
    ("interface_templates/interface_system_vsqr.sv.j2", "5_agent/{agent_name}_system_vsqr.sv"),
    ("interface_templates/interface_system_monitor.sv.j2", "5_agent/{agent_name}_system_monitor.sv"),
    ("interface_templates/interface_system_env.j2", "5_agent/{agent_name}_system_env.sv"),

    ("interface_templates/sequence_master.sv.j2", "7_sequence/{agent_name}_master_sequence.sv"),
    ("interface_templates/sequence_slave.sv.j2",  "7_sequence/{agent_name}_slave_sequence.sv"),

    ("interface_templates/reg_adapter.sv.j2", "8_ral/{agent_name}_reg_adapter.sv"),

    ("interface_templates/agent_parameters_pkg.sv.j2", "{agent_name}_parameters_pkg.sv"),
    ("interface_templates/agent_typedefs_pkg.sv.j2", "{agent_name}_typedefs_pkg.sv"),
    ("interface_templates/agent_pkg.sv.j2", "{agent_name}_pkg.sv"),
    ("interface_templates/agent_filelist.sv.j2", "filelist.f"),
    ("interface_templates/agent_Makefile.sv.j2", "Makefile"),
]

def _split_template_entry(entry) -> tuple:
    """模板注册表条目 → (template_path, target_pattern, context_overrides)。

    兼容 2 元组（无覆盖）与 3 元组（第 3 元素为渲染上下文覆盖，如 {"port": "master"}）。
    """
    return entry[0], entry[1], (entry[2] if len(entry) > 2 else {})


# Agent 自闭环测试套件（master-drive → slave-monitor 闭环，独立编译运行）
AGENT_LOOPBACK_TEMPLATES = [
    ("interface_templates/agent_loopback_env.sv.j2",  "{agent_name}_loopback_env.sv"),
    ("interface_templates/agent_loopback_scb.sv.j2",  "{agent_name}_loopback_scb.sv"),
    ("interface_templates/agent_loopback_test.sv.j2", "{agent_name}_loopback_test.sv"),
    ("interface_templates/agent_loopback_tb.sv.j2",   "{agent_name}_loopback_tb.sv"),
]

ENVIRONMENT_ROOT_TEMPLATES = [
    ("environment_templates/env_parameters_pkg.sv.j2", "{env_name}_parameters_pkg.sv"),
    ("environment_templates/env_config.sv.j2", "{env_name}_config.sv"),
    ("environment_templates/environment.sv.j2", "{env_name}.sv"),
    ("environment_templates/env_cov.sv.j2", "{env_name}_coverage.sv"),
    ("environment_templates/sim_end.sv.j2", "{env_name}_sim_end.sv"),
    ("environment_templates/env_pkg.sv.j2", "{env_name}_pkg.sv"),
]

ENVIRONMENT_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_pkg.sv.j2", "{env_name}_test_pkg.sv"),
    ("environment_templates/test_templates/test_base.sv.j2", "{env_name}_base_test.sv"),
    ("environment_templates/test_templates/test_directed.sv.j2", "{env_name}_direct_test.sv"),
    ("environment_templates/test_templates/gen_test_sv.j2", "{env_name}_gen_test.sv"),
]

#: 属性测试（**一条 environment.tests = 一个 UVM_TEST = 一个属性取值**）。
#: 单独一张表而不是并进上面那张：那张是「无条件产出的四个文件」，
#: 它被既有测试逐字钉着；这张**只在 tests 非空时渲染**，产物也只有一个文件。
ENVIRONMENT_ATTR_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_attr.sv.j2", "{env_name}_attr_test.sv"),
]

#: 批次测试（**一条 environment.batches = 一个 UVM_TEST = 一个批次/专题**）。
#: 与属性测试同形（都在 `tests`/`batches` 非空时才产），但产物不同 ——
#: 这一份出的是"这一批打哪几个维度、用什么方法"的 test 类，名字由 case 模型的
#: `themes[].test` 给定。**没有它，回归里 `+UVM_TESTNAME=<批次>` 会撞
#: UVM_FATAL(INVTST)，而那条路径被记成 pass**（见 `_sim_run_cmd` 的注释）。
ENVIRONMENT_BATCH_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_batch.sv.j2", "{env_name}_batch_test.sv"),
]

#: 寄存器（CSR）自带序列测试 —— 每个都是**薄薄一层**：实例化一个 UVM 官方
#: 寄存器序列（hw_reset / bit_bash / access）并 start。
#: **只在环境配了 register_model（且有 reg_block）时才产**：没配的环境连寄存器
#: 模型都没有，产出来就是一堆编译不过的文件。
ENVIRONMENT_REG_TEST_TEMPLATES = [
    ("environment_templates/test_templates/csr_hw_reset_test.sv.j2",
     "{env_name}_reg_hw_reset_test.sv"),
    ("environment_templates/test_templates/csr_bit_bash_test.sv.j2",
     "{env_name}_reg_bit_bash_test.sv"),
    ("environment_templates/test_templates/csr_access_test.sv.j2",
     "{env_name}_reg_access_test.sv"),
]


ENVIRONMENT_SEQ_TEMPLATES = [
    ("environment_templates/virtual_sequencer.sv.j2", "{env_name}_virtual_sequencer.sv"),
    ("environment_templates/seq_templates/virtual_sequence_base.sv.j2", "{env_name}_virtual_base_seq.sv"),
    ("environment_templates/seq_templates/seq_pkg.sv.j2", "{env_name}_seq_pkg.sv"),
]

ENV_CONSTRAINT_TEMPLATES = [
    (
        "environment_templates/env_cons_coordinated_sequence.j2",
        "{project_name}_coordinated_sequence.sv",
    ),
    (
        "environment_templates/env_cons_policy_base.sv.j2",
        "{env_name}_constraint_policy.sv",
    ),
    (
        "environment_templates/env_cons_policies.sv.j2",
        "{project_name}_constraint_policies.sv",
    ),
    (
        "environment_templates/env_cons_policy_combinator.j2",
        "{project_name}_policy_combinator.sv",
    ),
    (
        "environment_templates/env_cons_policy_factory.j2",
        "{project_name}_policy_factory.sv",
    ),
]

BENCH_TEMPLATES = [
    ("bench_templates/tb_top.sv.j2", "{bench_name}_tb_top.sv"),
]

HARNESS_TEMPLATES = [
    ("bench_templates/harness.sv.j2", "{name}.sv"),
]

CMODEL_TEMPLATES = [
    ("environment_templates/cmodel_predictor.sv.j2", "{module_name}_cmodel_predictor.sv"),
    ("environment_templates/cmodel_dpi.cpp.j2", "{module_name}_dpi_wrapper.cpp"),
]

# ── P0-4: 编译仿真门禁（--gate）──
_GATE_SIMULATORS = ("vlog", "vcs")   # 支持 UVM 的仿真器（iverilog/verilator 不支持 UVM 类）


def _detect_simulator() -> Optional[str]:
    for name in _GATE_SIMULATORS:
        if shutil.which(name):
            return name
    return None


def _run_gate(output_root: Path) -> List[Dict[str, str]]:
    """对每个 agent 的 loopback 自检跑编译+仿真，提取 pass/fail/skip。

    无仿真器 → 每项 skip（不阻断生成，仅报告）。
    """
    import subprocess as _sp

    sim = _detect_simulator()
    results: List[Dict[str, str]] = []
    agents_dir = output_root / "agents"
    if not agents_dir.is_dir():
        return results
    for agent_dir in sorted(agents_dir.iterdir()):
        lb_dir = agent_dir / "loopback"
        filelist = lb_dir / "filelist.f"
        if not filelist.is_file():
            continue
        name = agent_dir.name
        if sim is None:
            results.append({"agent": name, "status": "skip",
                            "reason": "no UVM simulator (vlog/vcs) found"})
            continue
        log_file = lb_dir / "gate_sim.log"
        try:
            if sim == "vlog":   # Questa/ModelSim
                cmds = [
                    ["vlog", "-sv", "-f", "filelist.f"],
                    ["vsim", "-c", "-l", "gate_sim.log",
                     "-do", "run -all; quit -f", f"{name}_loopback_tb"],
                ]
            else:               # VCS
                cmds = [
                    ["vcs", "-sverilog", "-f", "filelist.f", "-l", "gate_comp.log"],
                    ["./simv", "-l", "gate_sim.log"],
                ]
            status = "pass"
            for cmd in cmds:
                proc = _sp.run(cmd, cwd=str(lb_dir), capture_output=True,
                               text=True, timeout=300)
                if proc.returncode != 0:
                    status = "fail"
                    break
            if status == "pass":
                log_text = ""
                if log_file.is_file():
                    log_text = log_file.read_text(encoding="utf-8", errors="replace")
                if "UVM_ERROR" in log_text or "LOOPBACK_TIMEOUT" in log_text:
                    status = "fail"
            results.append({"agent": name, "status": status,
                            "sim": sim, "log": str(log_file)})
        except Exception as exc:
            results.append({"agent": name, "status": "fail",
                            "reason": f"{type(exc).__name__}: {exc}"})
    return results

@dataclass
class AgentModel:
    name: str
    agent_name: str
    interface: str
    interface_name: str
    clock: Optional[str] = None
    reset: Optional[str] = None
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    # typedefs: 名字 → 类型（如 byte_t: "bit [7:0]"），渲染进 <name>_typedefs_pkg。
    # 用映射而非 list[{name,type}]：类型定义天然是「一个名字对一个类型」。
    typedefs: Dict[str, str] = field(default_factory=dict)
    ports: List[Dict[str, Any]] = field(default_factory=list)
    # master/slave 共用的事务字段/约束 → 渲染进 <name>_base_seq_item，两侧 seq_item 继承它。
    # 与 transaction_vars 的分工：这里放「两侧都有」的（如 addr/data），
    # transaction_vars 放按 is_master 划分给各侧的（如 paddr/prdata）。
    base_transaction_vars: List[Dict[str, Any]] = field(default_factory=list)
    base_transaction_constraints: List[Dict[str, Any]] = field(default_factory=list)
    transaction_vars: List[Dict[str, Any]] = field(default_factory=list)
    transaction_constraints: List[Dict[str, Any]] = field(default_factory=list)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    response_info: Dict[str, Any] = field(default_factory=dict)
    config: Dict[str, Any] = field(default_factory=dict)
    agent_type: str = ""   # 从 YAML "type" 映射（如 "mem"）
    # 协议名（如 "apb"）→ 模板渲染协议正确的默认驱动/采样时序；空 = 通用单拍
    protocol: str = ""
    # 复位极性（P0-2 复位门控用）：True = 低有效（如 presetn），缺省 True
    reset_active_low: bool = True
    # env 级 agents 列表项的角色标记（interface 级不用）：
    is_master: Optional[bool] = None  # True=master 实例 / False=slave 实例 / None=未指定
    active: Optional[bool] = None     # 该实例 is_active（None → 模板走缺省 ACTIVE）
    # 注：pragma custom 区域不再从 YAML 回填（custom_code 已下线）——
    # 区域留空由模板默认值兜底，手改内容用 -m/--merge_source 保留。

    def __post_init__(self) -> None:
        # 注：interface 级不再提供 is_active —— 激活模式由 env 级 agents[].is_active
        # （→ AgentModel.active，见 _normalize_agents_list）决定；loopback 套件固定拓扑。
        if not self.interface:
            self.interface = self.name
        # Normalize: strip _interface suffix (may come from env/bench YAML)
        if self.interface.endswith("_interface"):
            self.interface = self.interface[:-len("_interface")]
        if not self.reset:
            self.reset = "rst"
        # agent_type：YAML "type" 映射为 agent 类名（如 "apb_master_agent"），
        # 缺省 = "{name}_agent"（兼容旧 dict 格式）
        if not self.agent_type:
            self.agent_type = f"{self.name}_agent"
        for var in self.transaction_vars:
            var.setdefault("iscompare", "False")
            var.setdefault("isrand", "False")
            # is_master: "True" → master 字段（master 驱动/生成）；
            #            "False" → slave 字段（slave 响应/生成）
            var.setdefault("is_master", "True")
        # base_transaction_vars 是两侧共用的，不参与 master/slave 划分（is_master 无意义），
        # 只补齐 iscompare/isrand 两个 flag 供 field_macros 统一处理。
        for var in self.base_transaction_vars:
            var.setdefault("iscompare", "False")
            var.setdefault("isrand", "False")
        # transaction_constraints 归一化为 dict：{master: [...], slave: [...]}
        # 兼容旧 list 格式（全部归入 master）
        if isinstance(self.transaction_constraints, list):
            self.transaction_constraints = {"master": self.transaction_constraints, "slave": []}
        elif not isinstance(self.transaction_constraints, dict):
            self.transaction_constraints = {"master": [], "slave": []}
        self.transaction_constraints.setdefault("master", [])
        self.transaction_constraints.setdefault("slave", [])

    def to_context(self) -> Dict[str, Any]:
        # pragma custom 区域内容不再来自 YAML（custom_code 已下线）；asdict 即完整上下文
        return asdict(self)

    # ── 派生类型名（env 层用）：从 agent_type（类名）推导 seq_item/config 类型 ──
    # 例：agent_type="apb_master_agent" → base="apb_master" →
    #     seq_item_type="apb_master_seq_item" / config_type="apb_master_config"
    @property
    def base_name(self) -> str:
        t = self.agent_type or self.name
        return t[:-len("_agent")] if t.endswith("_agent") else t

    @property
    def seq_item_type(self) -> str:
        return f"{self.base_name}_seq_item"

    @property
    def config_type(self) -> str:
        # 单类 port_config：env 级 agent 在 parse_documents 后处理中
        # 关联到 interface 级 agent 时覆盖为 "<interface_agent>_port_config"
        override = getattr(self, "_config_type_override", "")
        if override:
            return override
        return f"{self.base_name}_config"

    @property
    def sequence_type(self) -> str:
        return f"{self.base_name}_sequence"


class AgentCollection(list):
    def items(self):
        return [(agent.name, agent) for agent in self]


@dataclass
class EnvironmentModel:
    name: str
    env_name: str
    agents: AgentCollection = field(default_factory=AgentCollection)
    subenvs: List[Dict[str, Any]] = field(default_factory=list)
    vipenvs: List[Dict[str, Any]] = field(default_factory=list)
    scoreboards: List[Dict[str, Any]] = field(default_factory=list)
    analysis_components: List[Dict[str, Any]] = field(default_factory=list)
    analysis_exports: List[Dict[str, Any]] = field(default_factory=list)
    analysis_ports: List[Dict[str, Any]] = field(default_factory=list)
    clk_rst_vip: Dict[str, Any] = field(default_factory=dict)
    register_model: Dict[str, Any] = field(default_factory=dict)
    # 可选：测试侧 harness 连接 {path: 层级路径, env_suffix: ".sub_env0"}
    harness_connect: Dict[str, str] = field(default_factory=dict)
    # 语义 cross（P1-2）：[[字段A, 字段B], ...] → env_cov 生成 cross coverpoint
    coverage_crosses: List[List[str]] = field(default_factory=list)
    config_vars: List[Dict[str, Any]] = field(default_factory=list)
    config_constraints: List[Dict[str, Any]] = field(default_factory=list)
    tlm_connections: List[Dict[str, Any]] = field(default_factory=list)
    bench: Dict[str, Any] = field(default_factory=dict)
    #: 工具组件（predictor 等）。它们是**裸 class**，env_pkg 只能 `include`
    #: 进来（import 不了不在包里的东西）—— 而 env / env_config 里会声明
    #: 这些类型的成员，所以 include 要排在它们之前。
    utils: List[Dict[str, Any]] = field(default_factory=list)
    # 属性测试：**一条 = 一个 UVM_TEST = 一个属性取值**（维度×取值）。
    # 内容由 YAML environment.tests 归一化而来（_normalize_tests）；
    # 渲染在 test_attr.sv.j2，为空时不产那个文件。
    tests: List[Dict[str, Any]] = field(default_factory=list)
    # 批次测试：**一条 = 一个 UVM_TEST = 一个批次/专题**。
    # 内容由 YAML environment.batches 归一化而来（_normalize_batches）；
    # 渲染在 test_batch.sv.j2，为空时不产那个文件。
    #
    # 与 `tests` 是**两条平行的路**：那边一条一个属性取值，这边一条一个批次。
    batches: List[Dict[str, Any]] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        context = asdict(self)
        context["agents"] = self.agents
        return context

@dataclass
class ConstraintModel:
    name: str
    env_name: str
    transactions: List[Dict[str, Any]] = field(default_factory=list)
    policies: List[Dict[str, Any]] = field(default_factory=list)
    combinator: Dict[str, Any] = field(
        default_factory=lambda: {
            "default_mode": "APPLY_ALL",
            "modes": [
                "APPLY_ALL",
                "APPLY_WEIGHTED",
                "APPLY_FIRST_MATCH",
                "APPLY_SEQUENTIAL",
                "APPLY_CHAIN",
            ],
        }
    )

    def __post_init__(self) -> None:
        self.project = {"name": self.name, "env_name": self.env_name}

    def to_context(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "transactions": self.transactions,
            "policies": self.policies,
            "combinator": self.combinator,
        }


@dataclass
class ScPredPoint:
    """Sc_pred 检查点或产生点"""
    point_name: str
    width: int
    channel_num: int
    ports: List[Dict[str, Any]] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ScPredModel:
    """Scoreboard Predictor（监控器 + 产生器 + 环境类）"""
    name: str
    id: str = "0"
    prod_points: List[ScPredPoint] = field(default_factory=list)
    chck_points: List[ScPredPoint] = field(default_factory=list)

    def to_context(self) -> Dict[str, Any]:
        ctx = {
            "sc_pred": {
                "name": self.name,
                "id": self.id,
                "prod_points": [p.to_context() for p in self.prod_points],
                "chck_points": [p.to_context() for p in self.chck_points],
            }
        }
        return ctx

@dataclass
class HarnessModel:
    """bind 式 UVM harness（dummy interface + set_vifs + bind 到 DUT module）。

    各 interface 分别 bind 到目标 module（按 module 名，所有实例生效）；
    set_vifs 用向上查找（{{ bind_to }}.{{ source_path }}.{{ name }}）。
    """
    name: str                       # dummy interface 名（如 math_coprocessor_harness）
    bind_to: str = ""               # bind 目标 module 名（所有实例生效）
    parameter: str = ""             # 可选：harness 参数化（值取 module 同名 parameter）
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    sub_harnesses: List[Dict[str, Any]] = field(default_factory=list)
    connect_path: str = ""          # 可选：测试侧调用路径（如 "harness.U_X.harness"）

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


def _opt_bool(value: Any) -> Optional[bool]:
    """YAML 布尔（bool 或 "True"/"False" 字符串）→ Optional[bool]；无法解析 → None。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return None


def _to_count(value: Any) -> Any:
    """interface 数组大小：数字 → int；否则保留字符串（参数名，如 NUM_CLIENTS）。"""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value if value not in (None, "") else 1


def _normalize_harness(data: Dict[str, Any]) -> Optional[HarnessModel]:
    """归一化 harness YAML → HarnessModel。"""
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not name:
        return None
    bind_to = data.get("bind_to", "")
    interfaces = []
    for raw in data.get("interfaces") or []:
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("type"):
            continue
        conns = raw.get("connections") or {}
        if not isinstance(conns, dict):
            conns = {}
        interfaces.append({
            "name": raw["name"],
            "type": raw["type"],
            "agent_path": raw.get("agent_path", raw["name"]),
            "connections": conns,
            "bind_to": raw.get("bind_to", ""),      # 缺省用 harness.bind_to
            "source_path": raw.get("source_path", ""),  # 多实例层级路径（如 cache.memory）
            "count": _to_count(raw.get("count", 1)),
        })
    return HarnessModel(
        name=name,
        bind_to=bind_to,
        parameter=data.get("parameter", ""),
        interfaces=interfaces,
        sub_harnesses=[
            {"path": s.get("path", ""), "env_path": s.get("env_path", "")}
            for s in (data.get("sub_harnesses") or [])
            if isinstance(s, dict) and s.get("path")
        ],
        connect_path=data.get("connect_path", data.get("connect", {}).get("path", "")
                              if isinstance(data.get("connect"), dict) else ""),
    )


@dataclass
class WireDecl:
    """Wire declaration in the testbench top."""
    name: str
    width: int = 1

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Assignment:
    """Continuous assignment in the testbench top."""
    lhs: str
    rhs: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DutPort:
    """DUT port-to-wire connection."""
    name: str
    connection: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DutModel:
    """DUT instantiation information."""
    module: str
    instance: str = ""
    parameters: List[Dict[str, Any]] = field(default_factory=list)
    ports: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.instance:
            self.instance = f"u_{self.module}"

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ClkSpec:
    """Clock specification."""
    name: str
    period: str = "10ns"
    init: int = 0

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RstSpec:
    """Reset specification."""
    name: str
    init: int = 0
    release_delay: int = 100

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentConnection:
    """Maps an interface port to a physical wire."""
    port: str
    wire: str

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchAgentEntry:
    """Per-agent entry in the bench context — lean, connection-focused."""
    name: str
    interface: str
    clock: str = "clk"
    reset: str = "rst_n"
    instance: str = ""
    config_db_path: str = ""
    connections: List[Dict[str, Any]] = field(default_factory=list)
    agent_type: str = ""   # 从 YAML "type" 映射（如 "mem"）

    def __post_init__(self) -> None:
        if not self.instance:
            self.instance = f"{self.interface}_if"
        if not self.config_db_path:
            self.config_db_path = f"*{self.name}_agent_h*"
        if not self.agent_type:
            self.agent_type = f"{self.name}_agent"

    def to_context(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchModel:
    name: str
    env_name: str
    timeout: str = "10ms"
    include_assertions: bool = False
    clk_rst: Dict[str, Any] = field(default_factory=dict)
    wire_decls: List[Dict[str, Any]] = field(default_factory=list)
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    agents: Dict[str, BenchAgentEntry] = field(default_factory=dict)
    # 可选：bind 式 harness（存在时 tb_top 跳过接口实例化与 config_db set，
    # 由 harness.set_vifs() 在测试侧接管 vif 配置；DUT 实例化由 harness.bind_to 推导）
    harness: Dict[str, Any] = field(default_factory=dict)
    dut_instance: str = "u_dut"     # DUT **实例名**
    #: DUT **模块名**（tb_top 例化用）。
    #:
    #: 与 `dut_instance` 是两回事：一个是 `apb_slave_dut`，一个是 `u_dut`。
    #: 以前模块名只存在于 `harness.bind_to` 里 —— harness 一撤就没地方放了，
    #: 于是 tb_top 例化不出 DUT。现在它是 bench 自己的一等字段。
    dut_module: str = ""
    #: 要例化进 tb_top 的接口实例（替代 harness 的 bind 式自连接）。
    #: 每项：{name, type_name, clock, reset, agent_path, ports}
    #: tb_top 据此例化接口、按**同名端口**直连 DUT、再把 vif set 到 agent 路径。
    interfaces: List[Dict[str, Any]] = field(default_factory=list)
    #: DUT / 寄存器模型的源文件 —— 编译清单要收它们
    dut_filelist: List[str] = field(default_factory=list)
    ral_filelist: List[str] = field(default_factory=list)
    uvm_config: Dict[str, Any] = field(default_factory=dict)
    wave_dump: Dict[str, Any] = field(default_factory=dict)
    simulation: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Normalize agents: convert dict entries to BenchAgentEntry
        if isinstance(self.agents, dict):
            typed: Dict[str, BenchAgentEntry] = {}
            for k, v in self.agents.items():
                if isinstance(v, BenchAgentEntry):
                    typed[k] = v
                elif isinstance(v, dict):
                    typed[k] = BenchAgentEntry(
                        name=v.get("name", k),
                        interface=v.get("interface", k),
                        clock=v.get("clock", "clk"),
                        reset=v.get("reset", "rst_n"),
                        instance=v.get("instance", ""),
                        config_db_path=v.get("config_db_path", ""),
                        connections=v.get("connections", []),
                    )
            self.agents = typed

        # Normalize clk_rst: old-style string lists → dict lists
        clocks = self.clk_rst.get("clocks", [])
        resets = self.clk_rst.get("resets", [])
        self.clk_rst["clocks"] = [
            c if isinstance(c, dict) else {"name": c, "period": "10ns", "init": 0}
            for c in clocks
        ]
        self.clk_rst["resets"] = [
            r if isinstance(r, dict) else {"name": r, "init": 0, "release_delay": 100}
            for r in resets
        ]

    def to_context(self) -> Dict[str, Any]:
        ctx = asdict(self)
        # Convert BenchAgentEntry objects to dicts for Jinja2
        if "agents" in ctx and isinstance(self.agents, dict):
            ctx["agents"] = {
                k: (v.to_context() if isinstance(v, BenchAgentEntry) else v)
                for k, v in self.agents.items()
            }
        return ctx

    def get_agent(self, name: str) -> Optional[BenchAgentEntry]:
        return self.agents.get(name)

    def __repr__(self) -> str:
        return f"BenchModel(name={self.name!r}, env_name={self.env_name!r}, agents={list(self.agents.keys())!r})"

def _attr_slug(text: Any) -> str:
    """一段文本 → ASCII 标识符片段（非 [A-Za-z0-9] 一律折成 `_`）。

    中文维度名/取值都过这一道：它们能出现在注释里，但**不能出现在类名里**。
    """
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_").lower()


def attr_key(entry: Dict[str, Any]) -> str:
    """config_db 的键前缀。

    显式给的 `key` **原样用**（那是作者的命名选择，不该被我们小写化）；没给才由
    维度名推导。推导结果保证 ASCII —— config_db 的键会进 SV 字面量。
    """
    explicit = str(entry.get("key") or "").strip()
    if explicit:
        return explicit
    return _attr_slug(entry.get("dimension", "")) or "attr"


def attr_int_value(entry: Dict[str, Any]) -> int:
    """机器可读的整型取值 —— 这是**唯一进 SV 字面量的东西**。

    优先级：显式 `int_value` → 取值本身是数字 → 0。
    落到 0 意味着取值是中文且作者没给 `int_value`；类名那边会用 crc32 兜底保证
    不重名（见 `attr_class_slug`），而原取值仍以注释形式留在文件里。
    """
    explicit = entry.get("int_value")
    if isinstance(explicit, int) and not isinstance(explicit, bool):
        return explicit
    text = str(entry.get("value", "")).strip()
    try:
        return int(text)
    except ValueError:
        return 0


def attr_class_slug(entry: Dict[str, Any]) -> str:
    """类名里的 `<维度>_p<取值>` 片段，**保证全 ASCII**。

    取值是 ASCII 就直接用（`D_ratio` + `50` → `ratio_p50`）；是中文就投影到
    `int_value`（`D_mode` + 首拍 + 1 → `mode_p1`）。既非 ASCII 又没给 int_value
    时用 crc32 —— 硬编码成 `p0` 会让多个中文取值**撞成同一个类名**，那是编译错误。
    """
    dim = _attr_slug(entry.get("dimension", "")) or "attr"
    text = str(entry.get("value", "")).strip()
    if re.fullmatch(r"[A-Za-z0-9_]+", text):
        return f"{dim}_p{text}"
    if isinstance(entry.get("int_value"), int):
        return f"{dim}_p{attr_int_value(entry)}"
    return f"{dim}_p{zlib.crc32(text.encode('utf-8')) & 0xFFFF:04x}"


class JinjaRenderer:
    def __init__(self, templates_dir: Path) -> None:
        self.environment = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            keep_trailing_newline=True,
            autoescape=False,
        )
        # 文件头元数据（创建/修改时间 + 商标变量，base_template 兜底用）
        #
        # **`now` 必须是确定性的，否则生成物不可复现。**
        # 它落在每个生成文件的头注释里（base_template.sv.j2 的「创建/修改时间」）。
        # 取墙上时钟的话：同一份输入跑两次，实测 86 个文件里 76 个内容哈希不同 ——
        # 而证据链正是靠**内容哈希**判断「这个产物有没有被动过」。假差异会让比对
        # 失去意义，「可复现」也就无从谈起。
        self.environment.globals["now"] = reproducible_now
        self.environment.globals["trademark"] = COMPANY_TRADEMARK
        self.environment.globals["copyright_year"] = COPYRIGHT_YEAR
        self.environment.filters["nl2br"] = lambda value: str(value).replace("\n", "\\n")
        # 属性测试用的三个过滤器 —— 纯函数，能脱离 Jinja 单测
        self.environment.filters["attr_key"] = attr_key
        self.environment.filters["attr_int_value"] = attr_int_value
        self.environment.filters["attr_class_slug"] = attr_class_slug
        self.environment.globals["get_clock_index"] = lambda name, clocks: clocks.index(name) if name in clocks else 0
        self.environment.globals["get_reset_index"] = lambda name, resets: resets.index(name) if name in resets else 0
        self.environment.globals["get_transaction_type"] = self._get_transaction_type

    @staticmethod
    @pass_context
    def _get_transaction_type(context, transaction_name: str) -> str:
        transactions = context.get("transactions", [])
        for transaction in transactions:
            if transaction.get("name") == transaction_name:
                return transaction.get("type", f"{transaction_name}_transaction")
        return f"{transaction_name}_transaction"

    def render(self, template_path: str, context: Dict[str, Any]) -> str:
        template = self.environment.get_template(template_path)
        return template.render(**context)


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


# ────────────────────────────────────────────────────────────
# Markdown Summary Generation — human-readable agent docs
# ────────────────────────────────────────────────────────────

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
        rendered: List[Path] = []
        env_dir = self.output_dir / "env"
        context = {"environment": environment, **environment.to_context()}
        # 补充 agent 的 transaction_vars（env 渲染需要，供 env_cov 生成 coverpoint/cross）
        self._enrich_agents_transaction_vars(context)

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
        # **两个键名都认**：`cov_bins` 是现在写的（与 schema 的文档类型一致），
        # `coverage_bins` 是老的运行目录里留下的 —— 老的照样能渲染。
        bins_path = yaml_dir / "env_cov_bins.yaml"
        context["coverage_bins"] = []
        # `field_bins`: 字段名 → 显式 bin 表（`[{name, value}]`），来自 **case 模型**
        # （verify 阶段注入，见 `src/executors/verify/main.py`）。有了它就按模型声明
        # 的边界值分箱，没有就退回模板里那套"值类自动分箱"（0/1/其余）。
        context["coverage_field_bins"] = {}
        if bins_path.exists():
            try:
                import json as _json
                data = _json.loads(bins_path.read_text(encoding="utf-8", errors="replace"))
                if isinstance(data, dict):
                    context["coverage_bins"] = data.get("cov_bins") \
                        or data.get("coverage_bins") or []
                    _fb = data.get("field_bins")
                    if isinstance(_fb, dict):
                        context["coverage_field_bins"] = _fb
            except Exception:
                context["coverage_bins"] = []
                context["coverage_field_bins"] = {}


class ConstraintRenderTask(RenderTask):
    def generate(self, constraint: ConstraintModel) -> List[Path]:
        rendered: List[Path] = []
        cons_dir = self.output_dir / "env" / "cons"
        context = constraint.to_context()
        for template_path, target_pattern in ENV_CONSTRAINT_TEMPLATES:
            target_name = target_pattern.format(
                project_name=constraint.name,
                env_name=constraint.env_name,
            )
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


def _normalize_tests(raw) -> List[Dict[str, Any]]:
    """归一化 `environment.tests` → `[{dimension, value, key, int_value, base}]`。

    **一条 = 一个 UVM_TEST = 一个属性取值**。这里只做「类型净化 + 丢坏条目」，
    不做取值展开 —— 展开（哪个维度有哪些取值）是 case 属性模型那边的事，
    由它导出成这份清单；渲染器不认识那些语义。

    必填 `dimension` / `value`，缺一个就丢掉（宁可不产这个 test，也不要产一个
    没有属性、名字还重复的类）。`key` / `int_value` / `base` 缺省时留给模板
    过滤器推导（见 `attr_key` / `attr_int_value` / `attr_class_slug`）。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        value = item.get("value")
        if not dimension or value is None or str(value).strip() == "":
            continue
        int_value = item.get("int_value")
        out.append({
            "dimension": dimension,
            "value": str(value),
            "key": str(item.get("key") or "").strip(),
            # 保持 None：「没给」和「给了 0」是两回事，模板过滤器区分处理
            "int_value": int_value if isinstance(int_value, int) else None,
            "base": str(item.get("base") or "").strip(),
        })
    return out


def _normalize_batches(raw) -> List[Dict[str, Any]]:
    """`environment.batches` → `[{name, theme, dimensions, method, priority, checks}]`。

    必填 `name`（= test 类名），缺了就丢掉 —— 一个没名字的 test 类生成不出来。
    其余键缺省给空串（模板按空串渲染，不炸）。

    与 `_normalize_tests` 同一套纪律：**只做类型净化，不做语义展开** ——
    "哪个批次打哪几个维度"是 case 模型那边的事，这里不认识。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "theme": str(item.get("theme") or "").strip(),
            "dimensions": str(item.get("dimensions") or "").strip(),
            "method": str(item.get("method") or "").strip(),
            "priority": str(item.get("priority") or "").strip(),
            "checks": str(item.get("checks") or "").strip(),
        })
    return out


def _normalize_scoreboards(scoreboards):
    """归一化 scoreboards → list[{name, sb_type, trans_type, params, handle_type, typedef_decl}]。

    scoreboards:
      - name: apb_scb
        sb_type: uvmf_in_order_scoreboard   # 工厂可注册的具名类
        trans_type: apb_master_seq_item
      # 参数化类（如 scb_pkg 的 in_order_scoreboard#(REQ_T, RSP_T, CMP_T)）：
      # 给 params 传实参，句柄走 typedef 出来的别名
      - name: apb_scb_param
        sb_type: in_order_scoreboard
        trans_type: apb_master_seq_item
        params: [apb_master_seq_item, apb_master_seq_item]

    注：生成式（mode/expected_from/actual_from 自造计分板）已下线 ——
    scb 文件不再由本工具生成，一律由 sb_type 指向外部类。
    """
    normalized = []
    for sb in scoreboards or []:
        if not isinstance(sb, dict) or not sb.get("name"):
            continue
        name = sb["name"]
        sb_type = sb.get("sb_type", "")
        params = [str(p) for p in (sb.get("params") or [])]
        # 参数化类不能直接当类型名用（`in_order_scoreboard apb_scb;` 编译不过），
        # 故先 `typedef <类>#(<实参>) <name>_t;` 出别名，再用别名声明/例化句柄。
        typedef_decl = (f"typedef {sb_type}#({', '.join(params)}) {name}_t;"
                        if params and sb_type else "")
        normalized.append({
            "name": name,
            "sb_type": sb_type,
            "trans_type": sb.get("trans_type", ""),
            "params": params,
            "handle_type": f"{name}_t" if params else sb_type,
            "typedef_decl": typedef_decl,
        })
    return normalized


def _normalize_typedefs(raw) -> Dict[str, str]:
    """typedefs → 保序 Dict[类型名, 类型表达式]。

    每项一个 object，两个字段：
        type_t    类型表达式（typedef 右边）
        type_name 新类型名  （typedef 左边）
        - { type_t: "bit [7:0]", type_name: "byte_t" }  →  typedef bit [7:0] byte_t;

    保序：写在前面的先声明，故后面的 typedef 可以引用它。
    """
    out: Dict[str, str] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = item.get("type_name")
        if name is None or str(name) == "":
            continue
        ty = item.get("type_t")
        out[str(name)] = "" if ty is None else str(ty)
    return out


def _normalize_agents_list(agents):
    """把 agents 归一化为 list[dict]，兼容 dict（旧）与 list（新）两种格式。

    dict 格式:  { name: {interface, clock, ...} }
    list 格式:  [ {name, type, interface, clock, ...} ]
    """
    if not agents:
        return []
    if isinstance(agents, dict):
        items = []
        for k, v in agents.items():
            if isinstance(v, dict):
                items.append({"name": k, **v})
            elif isinstance(v, str):
                items.append({"name": k, "interface": v})
            else:
                items.append({"name": k})
        return items
    if isinstance(agents, list):
        result = []
        for a in agents:
            if not isinstance(a, dict):
                continue
            a = dict(a)
            if not a.get("name"):
                # name 缺省从 type 推导："apb_master_agent" → "apb_master"
                t = a.get("type", "")
                a["name"] = t[:-len("_agent")] if t.endswith("_agent") else t
            # `interface` 缺省从 name 推导：**一个接口出 master/slave 两个 agent**
            #（见 interface yaml 的头注释），所以接口名 = agent 名去掉 `_master`/`_slave`。
            #
            # 这一步不做的话，env 模板里的 `import {{ agent.interface }}_pkg::*`
            # 会退化成 agent 自己的名字 —— 生成 `import apb_master_pkg::*`，
            # 而真实的包叫 `apb_pkg`。于是 env/cfg 里**每一个**跨包类型都变成
            # "Invalid type"，一屏连带错误，根因却只是这一处。
            if not a.get("interface"):
                _n = str(a.get("name", ""))
                for _suffix in ("_master", "_slave"):
                    if _n.endswith(_suffix):
                        _n = _n[: -len(_suffix)]
                        break
                a["interface"] = _n
            result.append(a)
        return result
    return []


def _normalize_analysis_ports(entries):
    """归一化 analysis_exports/analysis_ports → list[{name, type, connected_to}]。

    事务类型兼容 type 与 trans_type 两种键名；缺省 type = uvm_sequence_item。
    """
    result = []
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        result.append({
            "name": e["name"],
            "type": e.get("type") or e.get("trans_type", "") or "uvm_sequence_item",
            "connected_to": e.get("connected_to", ""),
        })
    return result


def _normalize_analysis_components(components):
    """归一化 analysis_components → list[{name, type}]。type 缺省 = name。"""
    result = []
    for c in components or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": c.get("type", name),
        })
    return result


def _normalize_vipenvs(vipenvs):
    """归一化 vipenvs → list[{name, type, vip_path}]（外部 VIP 环境集成）。"""
    result = []
    for ve in vipenvs or []:
        if not isinstance(ve, dict):
            continue
        name = ve.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": ve.get("type", name),
            "vip_path": ve.get("vip_path", ""),
        })
    return result


def _normalize_subenvs(subenvs):
    """归一化 subenvs → list[{name, type}]。

    subenvs:
      - name: "apb_sys_env"        # 实例名
        type: "apb_system_env"     # 环境类名（缺省 = name）
    """
    result = []
    for se in subenvs or []:
        if not isinstance(se, dict):
            continue
        name = se.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": se.get("type", name),
        })
    return result


def _ral_role(name: str, item: Dict[str, Any]) -> str:
    """旧列表风格：显式 role 字段优先，否则按 name 识别。"""
    if item.get("role"):
        r = str(item["role"]).lower()
        if "predictor" in r or r.startswith("pred"):
            return "predictor"
        if "adapter" in r:
            return "adapter"
        return "reg_block"
    n = str(name).lower()
    if "predictor" in n or n.startswith("pred"):
        return "predictor"
    if "adapter" in n:
        return "adapter"
    return "reg_block"


def _resolve_bus_agent(item: Dict[str, Any], agents: List[Any]) -> Tuple[str, bool]:
    """bus 条目 → (env agent 名, 是否匹配)。

    type 匹配 agent_type/name > bus_name 匹配 name > 回退第一个 agent。
    多个候选时优先 is_master=True 的实例（如 master/slave 同 type 时选 master）。
    """
    itype = item.get("type") or ""
    bus_name = item.get("bus_name") or ""
    if itype:
        candidates = [a for a in agents
                      if getattr(a, "agent_type", "") == itype
                      or getattr(a, "name", "") == itype]
        if candidates:
            for a in candidates:
                if getattr(a, "is_master", None) is True:
                    return a.name, True
            return candidates[0].name, True
    if bus_name:
        for a in agents:
            if getattr(a, "name", "") == bus_name:
                return a.name, True
    return (agents[0].name if agents else ""), False


def _finalize_ral(components: List[Dict[str, Any]], agents: List[Any],
                  bus_agent: str = "", bus_matched: bool = False,
                  bus_entry_seen: bool = False) -> Dict[str, Any]:
    rm = {
        "components": components,
        # 总线 agent（env 实例名，如 apb_master）：default_map.set_sequencer 与 predictor 连接使用
        "bus_agent": bus_agent or (agents[0].name if agents else ""),
        # 供 SemanticValidator 检测 bus 条目未匹配到任何 agent
        "bus_matched": bus_matched,
        "bus_entry_seen": bus_entry_seen,
    }
    for role in ("reg_block", "adapter", "predictor"):
        rm[role] = next((c for c in components if c["role"] == role), None)
    pkgs: List[str] = []
    for c in components:
        if c["pkg"] and c["pkg"] not in pkgs:
            pkgs.append(c["pkg"])
    rm["pkgs"] = pkgs
    return rm


def _normalize_register_model(raw: Any, agents: List[Any]) -> Dict[str, Any]:
    """归一化 register_model → RAL 组件列表（env 模板渲染用）。

    用户 key 字段风格（当前）:
      register_model:
        - bus_name: "apb"                  # 总线 agent（type 匹配 env agents）
          type: "apb_master_agent"
        - reg_block_name: "reg_block"      # uvm_reg_block（实例名 + 类名）
          type: "regblock_t"
        - reg_adpater_name: "adapter"      # uvm_reg_adapter（reg_adapter_name 亦兼容）
          type: "my_adapter"
        - predictor_name: "predictor"      # uvm_reg_predictor
          type: "my_bus_predictor"         #   预测器类（缺省 = uvm_reg_predictor）
          trans_type: "my_bus_trans"       #   总线事务类（缺省 = type）
      type 可为 "pkg::class" 或配 pkg 字段（env_pkg 自动 import）。

    兼容旧列表风格（name 识别角色）与旧 dict 格式（reg_block_class/...）。
    """
    # 解包嵌套: register_model: {reg_adapter: [...]}
    if isinstance(raw, dict):
        for nested_key in ("reg_adapter", "reg_adpater"):
            nested = raw.get(nested_key)
            if isinstance(nested, list):
                raw = nested
                break

    def _mk(name: str, itype: str, role: str, pkg: str = "",
            trans_type: str = "") -> Dict[str, Any]:
        entry = {"name": name, "type": itype, "role": role, "pkg": pkg}
        if role == "predictor":
            entry["trans_type"] = trans_type or itype or "uvm_sequence_item"
        return entry

    # 列表 → components
    if isinstance(raw, list):
        components = []
        bus_agent = ""
        bus_matched = False
        bus_entry_seen = False
        for item in raw:
            if not isinstance(item, dict):
                continue
            itype = item.get("type") or ""
            pkg = item.get("pkg", "")
            if not pkg and isinstance(itype, str) and "::" in itype:
                pkg = itype.split("::", 1)[0]
            # 用户 key 字段风格
            if item.get("bus_name") is not None:
                bus_entry_seen = True
                bus_agent, bus_matched = _resolve_bus_agent(item, agents)
            elif item.get("reg_block_name"):
                components.append(_mk(item["reg_block_name"], itype, "reg_block", pkg))
            elif item.get("reg_adpater_name") or item.get("reg_adapter_name"):
                components.append(_mk(item.get("reg_adpater_name") or item.get("reg_adapter_name"),
                                      itype, "adapter", pkg))
            elif item.get("predictor_name"):
                components.append(_mk(item["predictor_name"],
                                      itype or "uvm_reg_predictor", "predictor", pkg,
                                      item.get("trans_type", "")))
            elif item.get("name"):
                # 旧列表风格（name 识别角色）：predictor 的 type 即总线事务类
                role = _ral_role(item["name"], item)
                if role == "predictor":
                    components.append(_mk(item["name"], "uvm_reg_predictor", "predictor",
                                          pkg, item.get("trans_type", "") or itype))
                else:
                    components.append(_mk(item["name"], itype, role, pkg))
        return _finalize_ral(components, agents, bus_agent, bus_matched, bus_entry_seen)

    # 旧 dict 格式 → components
    if isinstance(raw, dict) and raw.get("reg_block_class"):
        def _bool(value: Any, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            return str(value).strip().lower() in ("true", "1", "yes", "on")

        default_agent = agents[0].name if agents else ""
        components = [{
            "name": "reg_model",
            "type": f"{raw['reg_model_package']}::{raw['reg_block_class']}"
                    if raw.get("reg_model_package") else raw["reg_block_class"],
            "role": "reg_block",
            "pkg": raw.get("reg_model_package", ""),
        }]
        if _bool(raw.get("use_adapter"), True) and raw.get("reg_adapter_class"):
            components.append({
                "name": "adapter",
                "type": raw["reg_adapter_class"],
                "role": "adapter",
                "pkg": "",
            })
        if _bool(raw.get("use_explicit_prediction"), False) and default_agent:
            components.append({
                "name": "predictor",
                "type": "uvm_reg_predictor",
                "trans_type": f"{default_agent}_seq_item",
                "role": "predictor",
                "pkg": "",
            })
        return _finalize_ral(components, agents)

    return {}


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


def _with_system_type_name(raw: Dict[str, Any]) -> Dict[str, Any]:
    """bench.interfaces[] 的一项 → 补齐 `system_type_name`。

    每个接口都有个配套的"系统接口" `<x>_system_if`（agent 包里的
    `interface_system.j2` 生成：里面是 `virtual <x>_if master_if[15:0]` 这类
    句柄数组，供 system env 把接口分发给多个 agent 实例）。

    **它必须被实例化**：agent 包的 `<x>_system_env.sv` / `<x>_system_monitor.sv`
    里写着 `uvm_config_db#(virtual <x>_system_if)::get(...)`。Questa 在
    **load 阶段**会对设计中出现过的 virtual interface 类型做解析，设计里找不到
    该接口的**任何实例**就报
      "(vsim-8451) Virtual interface resolution cannot find a matching instance"
    —— **整个设计加载不了**，哪怕那两个组件根本没被例化过。
    所以 tb_top 会实例化它并向 master_if/slave_if 数组挂上真实句柄。
    """
    entry = dict(raw)
    type_name = str(entry.get("type_name") or "")
    if type_name.endswith("_if") and not entry.get("system_type_name"):
        entry["system_type_name"] = type_name[: -len("_if")] + "_system_if"
    return entry


class YAMLLoader:
    SUPPORTED_SUFFIXES = {".yml", ".yaml"}
    LISTFILE_SUFFIXES = {".f"}   # 清单文件：一行一个 YAML 路径

    @staticmethod
    def _expand_listfile(path: Path) -> List[Path]:
        """把 .f 清单文件展开成路径列表。

        一行一个路径；`#` 或 `//` 起注释；空行跳过；`+incdir+`、`-f` 之类
        编译选项行忽略（直接从 vlog filelist 搬过来也不会报错）。
        相对路径先按当前工作目录解析，找不到再相对清单文件所在目录解析。
        """
        out: List[Path] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.split("#", 1)[0].split("//", 1)[0].strip()
            if not line or line.startswith(("+", "-")):
                continue
            p = Path(line)
            if not p.is_absolute() and not p.exists():
                p = path.parent / line
            out.append(p)
        return out

    @staticmethod
    def collect_paths(inputs: Iterable[Path]) -> List[Path]:
        files: List[Path] = []
        seen: set = set()
        for input_path in inputs:
            # .f 清单文件：展开后当作新的输入（也允许里面写目录）
            if input_path.is_file() and input_path.suffix.lower() in YAMLLoader.LISTFILE_SUFFIXES:
                expanded = YAMLLoader.collect_paths(YAMLLoader._expand_listfile(input_path))
                for p in expanded:
                    if p not in seen:
                        seen.add(p)
                        files.append(p)
                continue
            if input_path.is_dir():
                for path in sorted(input_path.rglob("*")):
                    if path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES and path.is_file():
                        if path not in seen:
                            seen.add(path)
                            files.append(path)
            elif input_path.is_file() and input_path.suffix.lower() in YAMLLoader.SUPPORTED_SUFFIXES:
                if input_path not in seen:
                    seen.add(input_path)
                    files.append(input_path)
        return files

    @staticmethod
    def parse_agent_model(data: Dict[str, Any]) -> Optional[AgentModel]:
        if not isinstance(data, dict):
            return None
        name = data.get("name") or data.get("agent_name")
        if not name:
            return None

        return AgentModel(
            name=name,
            agent_name=name,
            interface=data.get("interface", ""),
            interface_name=data.get("interface_name", data.get("interface", "")),
            clock=data.get("clock") or data.get("clk"),
            reset=data.get("reset"),
            protocol=data.get("protocol", ""),
            reset_active_low=_opt_bool(data.get("reset_active_low", True)) is not False,
            parameters=data.get("parameters", []),
            typedefs=_normalize_typedefs(data.get("typedefs")),
            ports=data.get("ports", []),
            base_transaction_vars=data.get("base_transaction_vars", []),
            base_transaction_constraints=data.get("base_transaction_constraints", []),
            transaction_vars=data.get("transaction_vars", []),
            transaction_constraints=data.get("transaction_constraints", []),
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            response_info=data.get("response_info", {}),
            config=dict(data.get("config") or {}),
        )

    @staticmethod
    def parse_environment_model(data: Dict[str, Any]) -> EnvironmentModel:
        name = data.get("name")
        env_name = name      # env_name 已从 YAML 下线：生成前缀一律取 name
        agents = AgentCollection()
        for agent_config in _normalize_agents_list(data.get("agents")):
            agent_name = agent_config.get("name") or agent_config.get("agent_name")
            if not agent_name:
                continue
            agent = AgentModel(
                name=agent_name,
                agent_name=agent_name,
                interface=agent_config.get("interface", agent_name),
                interface_name=agent_config.get("interface", agent_name),
                clock=agent_config.get("clock"),
                reset=agent_config.get("reset"),
                agent_type=agent_config.get("type", ""),
                is_master=_opt_bool(agent_config.get("is_master")),
                active=_opt_bool(agent_config.get("is_active")),
            )
            agents.append(agent)

        clk_rst_vip = data.get("clk_rst_vip") or {}
        if not clk_rst_vip and data.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": data["clk_rst"].get("clocks", []),
                "resets": data["clk_rst"].get("resets", []),
            }

        agent_names = [a.name for a in agents]
        register_model = _normalize_register_model(
            data.get("register_model") or data.get("reg_adapter"), list(agents))
        return EnvironmentModel(
            name=name,
            env_name=env_name,
            agents=agents,
            subenvs=_normalize_subenvs(data.get("subenvs", [])),
            vipenvs=_normalize_vipenvs(data.get("vipenvs", [])),
            scoreboards=_normalize_scoreboards(data.get("scoreboards", [])),
            analysis_components=_normalize_analysis_components(data.get("analysis_components", [])),
            analysis_exports=_normalize_analysis_ports(data.get("analysis_exports", [])),
            analysis_ports=_normalize_analysis_ports(data.get("analysis_ports", [])),
            clk_rst_vip=clk_rst_vip,
            register_model=register_model,
            harness_connect=dict(data.get("harness_connect") or {}),
            coverage_crosses=[
                [str(f) for f in c] for c in (data.get("coverage_crosses") or [])
                if isinstance(c, (list, tuple)) and len(c) >= 2],
            config_vars=data.get("config_vars", []),
            config_constraints=data.get("config_constraints", []),
            tlm_connections=data.get("tlm_connections", []),
            bench=data.get("bench", {}),
            # util_components 与 environment 在**同一份文档**里，所以这里读得到
            utils=[{"name": u.get("name")} for u in (data.get("util_components") or [])
                   if isinstance(u, dict) and u.get("name")],
            tests=_normalize_tests(data.get("tests", [])),
            batches=_normalize_batches(data.get("batches", [])),
        )

    @staticmethod
    def parse_bench_model(data: Dict[str, Any]) -> BenchModel:
        agents: Dict[str, BenchAgentEntry] = {}
        for agent_config in _normalize_agents_list(data.get("agents")):
            name = agent_config.get("name")
            if not name:
                continue
            agents[name] = BenchAgentEntry(
                name=name,
                interface=agent_config.get("interface", ""),
                clock=agent_config.get("clock", "clk"),
                reset=agent_config.get("reset", "rst_n"),
                instance=agent_config.get("instance", ""),
                config_db_path=agent_config.get("config_db_path", ""),
                connections=agent_config.get("connections", []),
                agent_type=agent_config.get("type", ""),
            )
        return BenchModel(
            name=data.get("name") or data.get("bench_name", "bench"),
            # env_name 已从 YAML 下线：由 run() 按已解析的 environment 回填
            env_name="",
            timeout=data.get("timeout", "10ms"),
            include_assertions=data.get("include_assertions", False),
            # 时钟复位：新名 clk_rst_if 优先，兼容旧名 clk_rst
            clk_rst=data.get("clk_rst_if") or data.get("clk_rst") or {},
            wire_decls=data.get("wire_decls", []),
            assignments=data.get("assignments", []),
            agents=agents,
            harness=dict(data.get("harness") or {}),
            dut_instance=data.get("dut_instance", "u_dut"),
            dut_module=data.get("dut_module", ""),
            # 接口实例清单（替代 harness）。只收形状完整的项 —— 缺 name/type_name
            # 的条目渲染不出东西，留着只会在 tb_top 里变成一行空声明。
            interfaces=[_with_system_type_name(i)
                        for i in (data.get("interfaces") or [])
                        if isinstance(i, dict) and i.get("name") and i.get("type_name")],
            dut_filelist=list(data.get("dut_filelist") or []),
            ral_filelist=list(data.get("ral_filelist") or []),
            uvm_config=data.get("uvm_config", {}),
            wave_dump=data.get("wave_dump", {}),
            simulation=data.get("simulation", {}),
        )

    @staticmethod
    def parse_sc_pred_model(data: Dict[str, Any]) -> Optional[ScPredModel]:
        """解析 sc_pred 配置为 ScPredModel。

        配置格式：
          sc_pred:
            name: "apb"
            id: "0"
            prod_points:
              - { point_name: "cmd_cfg", width: 512, channel_num: 1, ports: [...] }
            chck_points:
              - { point_name: "rd0_align", width: 512, channel_num: 1, ports: [...] }
        """
        if not isinstance(data, dict):
            return None

        sc_pred = data.get("sc_pred") or data.get("rtl_sc_components")
        if not sc_pred:
            return None

        # 解析 prod_points
        prod_points = []
        for pt in sc_pred.get("prod_points", []):
            if not isinstance(pt, dict) or not pt.get("point_name"):
                continue
            prod_points.append(ScPredPoint(
                point_name=pt["point_name"],
                width=pt.get("width", 32),
                channel_num=pt.get("channel_num", 1),
                ports=pt.get("ports", []),
            ))

        # 解析 chck_points
        chck_points = []
        for pt in sc_pred.get("chck_points", []):
            if not isinstance(pt, dict) or not pt.get("point_name"):
                continue
            chck_points.append(ScPredPoint(
                point_name=pt["point_name"],
                width=pt.get("width", 32),
                channel_num=pt.get("channel_num", 1),
                ports=pt.get("ports", []),
            ))

        return ScPredModel(
            name=sc_pred.get("name", "sc_pred"),
            id=str(sc_pred.get("id", "0")),
            prod_points=prod_points,
            chck_points=chck_points,
        )

    @staticmethod
    def parse_constraint_model(data: Dict[str, Any]) -> ConstraintModel:
        project = data.get("constraint") or {}
        name = project.get("name") or project.get("constraint_name") or "constraint"
        env_name = project.get("env") or ""      # env_name 已下线，改用 env
        return ConstraintModel(
            name=name,
            env_name=env_name,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get(
                "combinator",
                {
                    "default_mode": "APPLY_ALL",
                    "modes": [
                        "APPLY_ALL",
                        "APPLY_WEIGHTED",
                        "APPLY_FIRST_MATCH",
                        "APPLY_SEQUENTIAL",
                        "APPLY_CHAIN",
                    ],
                },
            ),
        )

    @staticmethod
    def parse_documents(paths: Iterable[Path]) -> Dict[str, Any]:
        interfaces = AgentCollection()
        environments: List[EnvironmentModel] = []
        benches: List[BenchModel] = []
        constraints: List[ConstraintModel] = []
        harnesses: List[HarnessModel] = []
        utils: List[Dict[str, Any]] = []
        meta: Dict[str, str] = {}

        for path in paths:
            with path.open("r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle)

            if not isinstance(data, dict):
                continue

            # 顶层 meta: 文件头元数据（后读的文件覆盖同名键）
            if isinstance(data.get("meta"), dict):
                for k, v in data["meta"].items():
                    if v not in (None, ""):
                        meta[k] = str(v)

            if "util_components" in data:
                payload = data["util_components"]
                if isinstance(payload, list):
                    utils.extend(payload)
                elif isinstance(payload, dict):
                    utils.append(payload)

            if "interfaces" in data:
                payload = data["interfaces"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "interface" in data:
                payload = data["interface"]
                if isinstance(payload, list):
                    for item in payload:
                        agent = YAMLLoader.parse_agent_model(item)
                        if agent:
                            interfaces.append(agent)
                elif isinstance(payload, dict):
                    agent = YAMLLoader.parse_agent_model(payload)
                    if agent:
                        interfaces.append(agent)

            if "environment" in data:
                payload = data["environment"]
                if isinstance(payload, dict):
                    environments.append(YAMLLoader.parse_environment_model(payload))

            if "bench" in data:
                payload = data["bench"]
                if isinstance(payload, dict):
                    bmodel = YAMLLoader.parse_bench_model(payload)
                    # DUT / RAL 清单在 YAML 里是**相对该 YAML 的路径**（习惯写法，
                    # 如 `../apb_slave_dut.sv`），而 Makefile 是在**生成目录**里跑的
                    # —— 原样渲染就会 "Failed to open design unit file
                    # ../apb_slave_dut.sv"。这里就地解析成绝对路径，生成目录放哪都能编。
                    base = path.parent
                    for attr in ("dut_filelist", "ral_filelist"):
                        files = getattr(bmodel, attr) or []
                        if files:
                            setattr(bmodel, attr, [
                                f if os.path.isabs(f)
                                else str((base / f).resolve()).replace("\\", "/")
                                for f in files])
                    benches.append(bmodel)

            if "constraint" in data:
                constraints.append(YAMLLoader.parse_constraint_model(data))

            if "harness" in data:
                payload = data["harness"]
                if isinstance(payload, list):
                    for item in payload:
                        h = _normalize_harness(item)
                        if h:
                            harnesses.append(h)
                elif isinstance(payload, dict):
                    h = _normalize_harness(payload)
                    if h:
                        harnesses.append(h)

            if "bench" in data and isinstance(data["bench"], dict):
                bh = data["bench"].get("harness")
                if isinstance(bh, dict):
                    h = _normalize_harness(bh)
                    if h:
                        harnesses.append(h)

        # 后处理：env agents 的 transaction_vars 从同名 interface 文档补齐
        # （校验层 coverage_cross 规则与 env_cov 渲染都需要；匹配:
        #  精确 → 忽略大小写 → 前缀包含，如 apb_master ↔ APB）
        _ifaces_lower = {a.interface_name.lower(): a for a in interfaces
                         if a.interface_name}
        _ifaces_name = {a.name.lower(): a for a in interfaces}
        for env in environments:
            for eagent in env.agents:
                if getattr(eagent, "transaction_vars", None):
                    continue
                key = getattr(eagent, "interface", "") or eagent.name
                ref = (_ifaces_name.get(key.lower())
                       or _ifaces_lower.get(key.lower()))
                if ref is None:   # 前缀匹配（apb_master → apb）
                    for lower, agent in _ifaces_name.items():
                        if lower and (key.lower().startswith(lower)
                                      or lower.startswith(key.lower())):
                            ref = agent
                            break
                if ref is not None:
                    eagent.transaction_vars = list(ref.transaction_vars)
                    # 单类 port_config：env 级 config 类型指向 interface 级单类
                    eagent._config_type_override = f"{ref.name}_port_config"

        return {
            "interfaces": interfaces,
            "environments": environments,
            "benches": benches,
            "constraints": constraints,
            "harnesses": harnesses,
            "utils": utils,
            "sc_preds": [pred for pred in [YAMLLoader.parse_sc_pred_model(data) for data in [data]] if pred is not None],

            "meta": meta,
        }


class UVMGenerator:
    def __init__(self, renderer: JinjaRenderer, output_root: Path,
                 injector: Optional[RegionInjector] = None,
                 overwrite: bool = False,
                 generate_names: Optional[List[str]] = None,
                 quiet: bool = False,
                 schema_check: bool = True) -> None:
        self.renderer = renderer
        self.output_root = output_root
        self.injector = injector if injector is not None else RegionInjector()
        self.overwrite = overwrite
        self.generate_names = generate_names or []
        self.quiet = quiet
        self.schema_check = schema_check  # Phase 0: YAML schema 语法检查（--skip-schema-check 关闭）
        self.skipped = 0
        self.meta: Dict[str, str] = dict(DEFAULT_META)
        self.validation_issues: List[Any] = []
        self.schema_issues: List[Any] = []

    def _log(self, msg: str) -> None:
        if not self.quiet:
            print(msg)

    def _should_skip(self, target_path: Path) -> bool:
        if self.overwrite or self.injector.merge_source is not None:
            return False
        return target_path.exists()

    def _filter_named(self, items: Iterable[Any], *keys) -> List[Any]:
        if not self.generate_names:
            return list(items)
        result = []
        for item in items:
            for key in keys:
                value = item.get(key, "") if isinstance(item, dict) else getattr(item, key, "")
                if value in self.generate_names:
                    result.append(item)
                    break
        return result

    def generate_agents(self, agents: Iterable[AgentModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "agent", self.renderer, self.output_root, self.injector, self.overwrite, self.meta)
        generated: List[Optional[Path]] = []
        for agent in agents:
            generated.extend(task.generate(agent))
        self.skipped += task.skipped
        return generated

    def generate_environments(self, environments: Iterable[EnvironmentModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "environment", self.renderer, self.output_root, self.injector, self.overwrite, self.meta)
        generated: List[Optional[Path]] = []
        for environment in environments:
            generated.extend(task.generate(environment))
        self.skipped += task.skipped
        return generated

    def generate_constraints(self, constraints: Iterable[ConstraintModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "constraint", self.renderer, self.output_root, self.injector, self.overwrite, self.meta)
        generated: List[Optional[Path]] = []
        for constraint in constraints:
            generated.extend(task.generate(constraint))
        self.skipped += task.skipped
        return generated

    def generate_benches(self, benches: Iterable[BenchModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "bench", self.renderer, self.output_root, self.injector, self.overwrite, self.meta)
        generated: List[Optional[Path]] = []
        for bench in benches:
            generated.extend([task.generate(bench)])
        self.skipped += task.skipped
        return generated

    def generate_harnesses(self, harnesses: Iterable[HarnessModel]) -> List[Optional[Path]]:
        task = RenderTaskFactory.create(
            "harness", self.renderer, self.output_root, self.injector, self.overwrite, self.meta)
        generated: List[Optional[Path]] = []
        for harness in harnesses:
            result = task.generate(harness)
            if result is not None:
                generated.append(result)
        self.skipped += task.skipped
        return generated

    def generate_utils(self, utils: Iterable[Dict[str, Any]]) -> List[Path]:
        """生成工具组件（Predictor 等）"""
        generated: List[Path] = []
        util_dir = self.output_root / "env" / "utils"
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in utils:
            if not isinstance(comp, dict):
                continue
            name = comp.get("name", "util")
            ctx = {
                "name": name,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
                # 带这一项 → util 模板把 `process_<port>` 的 TODO 空壳换成真的
                # 参考模型镜像（见模板与 schema 的 `refModelMirror`）。缺省 None
                # 保持原样 —— 不带镜像的 util 组件行为逐字节不变。
                "ref_model": comp.get("ref_model"),
            }
            for tpl_path, target_pattern in _util_templates:
                target_name = target_pattern.format(name=name)
                target_path = util_dir / target_name
                if self._should_skip(target_path):
                    self.skipped += 1
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    content = self.renderer.render(tpl_path, ctx)
                    target_path.write_text(content, encoding="utf-8")
                    generated.append(target_path)
                except Exception as e:
                    pass
        return generated

    def generate_scpreds(self, sc_preds: Iterable[ScPredModel]) -> List[Path]:
        """生成 Scoreboard Predictor（监控器 + 产生器 + 环境类）。

        生成目录结构：
          env/rtl_sc/
            ├── {name}_sc_pred_env.sv    # 环境包装类
            ├── {{point}}_mon_ex.sv      # 监控器模板（每个检查点）
            └── {{point}}_prod.sv        # 产生器模板（每个产生点）
          env/rtl_sc/interfaces/        # 接口文件
          env/rtl_sc/prods/             # 产生器组件
          env/rtl_sc/mon_ex/            # 监控器组件
        """
        generated: List[Path] = []

        # 创建所有需要的目录结构
        rtl_sc_dir = self.output_root / "env" / "rtl_sc"
        interfaces_dir = rtl_sc_dir / "interfaces"
        prods_dir = rtl_sc_dir / "prods"
        mon_ex_dir = rtl_sc_dir / "mon_ex"
        for dir_path in [rtl_sc_dir, interfaces_dir, prods_dir, mon_ex_dir]:
            dir_path.mkdir(parents=True, exist_ok=True)

        # 使用 tool_sc_red 的模板路径（相对路径）
        sc_pred_templates = [
            ("sc_pred_templates/sc_pred_env.sv.j2", "{name}_sc_pred_env.sv"),
            ("sc_pred_templates/mon_ex.sv.j2", "{point_name}_mon_ex.sv"),
            ("sc_pred_templates/prod.sv.j2", "{point_name}_prod.sv"),
            ("sc_pred_templates/prod_point_if.sv.j2", "{point_name}_prod_if.sv"),
            ("sc_pred_templates/prod_point_if.sv.j2", "{point_name}_mon_if.sv"),
        ]

        # 辅助函数：生成 prod 的打印字段
        def generate_prod_print_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
                    if port['width'] > 1:
                        fields.append(f", {port['name']}=0x%0h")
                    else:
                        fields.append(f", {port['name']}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 prod 的转换字段
        def generate_prod_convert_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
                    field_name = port['name']
                    if port['width'] > 1:
                        fields.append(f", {field_name}=0x%0h")
                    else:
                        fields.append(f", {field_name}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 monitor 的打印字段
        def generate_mon_print_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
                    if port['width'] > 1:
                        fields.append(f", {port['name']}=0x%0h")
                    else:
                        fields.append(f", {port['name']}=%0d")
            return ''.join(fields)

        # 辅助函数：生成 monitor 的转换字段
        def generate_mon_convert_fields(point):
            fields = []
            for port in point.ports:
                if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
                    field_name = port['name']
                    if port['width'] > 1:
                        fields.append(f", {field_name}=0x%0h")
                    else:
                        fields.append(f", {field_name}=%0d")
            return ''.join(fields)

        for sc_pred in sc_preds:
            # 生成环境包装类
            ctx = sc_pred.to_context()
            # 将 sc_pred 内容提升到顶层
            ctx_top = ctx["sc_pred"]
            ctx_top["name"] = sc_pred.name  # 确保顶层有 name

            env_tpl_path, env_target_pat = sc_pred_templates[0]
            env_target_path = rtl_sc_dir / env_target_pat.format(name=sc_pred.name)
            if not self._should_skip(env_target_path):
                print(f"DEBUG: 生成 sc_pred_env.sv: {env_target_path}")
                print(f"DEBUG: 模板路径: {env_tpl_path}")
                try:
                    content = self.renderer.render(env_tpl_path, ctx_top)
                    content, _ = self.injector.inject(
                        content, {},
                        f"env/rtl_sc/{env_target_path.name}", banner_prefix="// "
                    )
                    env_target_path.write_text(content, encoding="utf-8")
                    generated.append(env_target_path)
                    print(f"SUCCESS: 生成 {env_target_path}")
                except Exception as e:
                    print(f"ERROR: 生成 {env_target_path} 失败: {e}")

            # 生成接口和组件文件
            # 生成 prod_points 的接口和组件
            for point in sc_pred.prod_points:
                ctx_point = point.to_context()
                # 提升到顶层
                ctx_top = ctx_point
                ctx_top.update({"name": sc_pred.name, "point": point})

                # 生成 prod interface
                prod_tpl_path, prod_target_pat = sc_pred_templates[3]
                prod_target_path = interfaces_dir / prod_target_pat.format(point_name=point.point_name)
                if not self._should_skip(prod_target_path):
                    try:
                        # 为 prod interface 添加额外的上下文
                        prod_ctx = {**ctx_point, "print_fields": generate_prod_print_fields(point),
                                  "convert_fields": generate_prod_convert_fields(point)}
                        content = self.renderer.render(prod_tpl_path, prod_ctx)
                        prod_target_path.write_text(content, encoding="utf-8")
                        generated.append(prod_target_path)
                        print(f"SUCCESS: 生成 {prod_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {prod_target_path} 失败: {e}")

                # 生成 prod 组件
                prod_tpl_path, prod_target_pat = sc_pred_templates[2]
                prod_target_path = prods_dir / prod_target_pat.format(point_name=point.point_name)
                if not self._should_skip(prod_target_path):
                    try:
                        # 为 prod 组件添加额外的上下文
                        prod_ctx = {**ctx_point, "print_fields": generate_prod_print_fields(point),
                                  "convert_fields": generate_prod_convert_fields(point)}
                        content = self.renderer.render(prod_tpl_path, prod_ctx)
                        prod_target_path.write_text(content, encoding="utf-8")
                        generated.append(prod_target_path)
                        print(f"SUCCESS: 生成 {prod_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {prod_target_path} 失败: {e}")

            # 生成 chck_points 的接口和组件
            for point in sc_pred.chck_points:
                ctx_point = point.to_context()
                # 提升到顶层
                ctx_top = ctx_point
                ctx_top.update({"name": sc_pred.name, "point": point})

                # 生成 mon interface
                mon_tpl_path, mon_target_pat = sc_pred_templates[4]
                mon_target_path = interfaces_dir / mon_target_pat.format(point_name=point.point_name)
                if not self._should_skip(mon_target_path):
                    try:
                        # 为 mon interface 添加额外的上下文
                        mon_ctx = {**ctx_point, "print_fields": generate_mon_print_fields(point),
                                  "convert_fields": generate_mon_convert_fields(point)}
                        content = self.renderer.render(mon_tpl_path, mon_ctx)
                        mon_target_path.write_text(content, encoding="utf-8")
                        generated.append(mon_target_path)
                        print(f"SUCCESS: 生成 {mon_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {mon_target_path} 失败: {e}")

                # 生成 mon_ex 组件
                mon_tpl_path, mon_target_pat = sc_pred_templates[1]
                mon_target_path = mon_ex_dir / mon_target_pat.format(point_name=point.point_name)
                if not self._should_skip(mon_target_path):
                    try:
                        # 为 mon_ex 组件添加额外的上下文
                        mon_ctx = {**ctx_point, "print_fields": generate_mon_print_fields(point),
                                  "convert_fields": generate_mon_convert_fields(point)}
                        content = self.renderer.render(mon_tpl_path, mon_ctx)
                        mon_target_path.write_text(content, encoding="utf-8")
                        generated.append(mon_target_path)
                        print(f"SUCCESS: 生成 {mon_target_path}")
                    except Exception as e:
                        print(f"ERROR: 生成 {mon_target_path} 失败: {e}")

        return generated

    def _run_schema_check(self, yaml_files: Iterable[Path]) -> List[Any]:
        """Phase 0: 原始 YAML 层 schema 语法检查（jsonschema 缺失时跳过并提示）。"""
        try:
            from .schema_check import SchemaChecker  # 包内导入（python -m 路径）
        except ImportError:
            try:
                from schema_check import SchemaChecker
            except ImportError as exc:
                self._log(f"Warning: schema check skipped "
                          f"(jsonschema not available: {exc})")
                return []
        return SchemaChecker().check(yaml_files)

    def run(self, inputs: Iterable[Path]) -> List[Path]:
        yaml_files = YAMLLoader.collect_paths(inputs)
        if not yaml_files:
            raise SystemExit("No YAML files were found in the input paths.")

        # ── Phase 0: YAML schema 语法检查（原始 YAML 层，先于解析/语义校验；
        #    error 阻断生成，warning 落盘不阻断）──
        self.schema_issues = self._run_schema_check(yaml_files) if self.schema_check else []
        if self.schema_issues:
            report_path = self.output_root / "schema_report.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "Schema check report (tool_uvm)\n"
                + "\n".join(str(i) for i in self.schema_issues) + "\n",
                encoding="utf-8")
            for i in self.schema_issues:
                if i.severity == "warning":
                    self._log(f"Warning: {i}")
            schema_errors = [i for i in self.schema_issues if i.severity == "error"]
            if schema_errors:
                for i in schema_errors:
                    self._log(f"Error: {i}")
                raise SystemExit(
                    f"Schema validation failed: {len(schema_errors)} error(s), "
                    f"{len(self.schema_issues) - len(schema_errors)} warning(s) "
                    f"— see {report_path}")

        data = YAMLLoader.parse_documents(yaml_files)
        self.meta = {**DEFAULT_META, **data["meta"]}   # YAML meta 覆盖默认文件头元数据
        interfaces = data["interfaces"]
        environments = data["environments"]
        benches = data["benches"]
        constraints = data["constraints"]
        harnesses = data["harnesses"]
        utils = data["utils"]
        sc_preds = data["sc_preds"]

        # ── Phase A: 渲染前语义校验（error 阻断生成，warning 不阻断）──
        issues = SemanticValidator.validate(data)
        self.validation_issues = issues
        # **规则命中落库**：没有这一刻，规则库就只会越加越多 ——
        # "从来没命中的规则"和"真在干活的规则"在源码里长得一模一样，
        # 于是没人敢删、也没人知道该调哪条阈值（见 l4_memory/rule_stats.py）。
        # 旁路：统计失败不影响生成。
        try:
            from src.layers.l4_memory.rule_stats import record_rule_hits

            _n = record_rule_hits(issues, run_id=Path(self.output_root).name)
            if _n:
                self._log(f"规则命中已记账：{_n} 条（{self.output_root}/.signoffai）")
        except Exception as _e:                        # noqa: BLE001
            self._log(f"规则命中记账失败（不影响生成）: {_e}")
        if issues:
            report_path = self.output_root / "validation_report.txt"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                "Semantic check report (tool_uvm)\n"
                + "\n".join(str(i) for i in issues) + "\n",
                encoding="utf-8")
            for i in issues:
                if i.severity == "warning":
                    self._log(f"Warning: {i}")
            errors = [i for i in issues if i.severity == "error"]
            if errors:
                for i in errors:
                    self._log(f"Error: {i}")
                raise SystemExit(
                    f"Semantic validation failed: {len(errors)} error(s), "
                    f"{len(issues) - len(errors)} warning(s) — see {report_path}")

        # ── -g/--generate 名称过滤 ──
        if self.generate_names:
            interfaces = self._filter_named(interfaces, "name")
            environments = self._filter_named(environments, "name")
            benches = self._filter_named(benches, "name")
            constraints = self._filter_named(constraints, "name")
            harnesses = self._filter_named(harnesses, "name")
            utils = self._filter_named(utils, "name")
            if not any((interfaces, environments, benches, constraints, harnesses, utils)):
                available = sorted(
                    [a.name for a in data["interfaces"]]
                    + [e.name for e in data["environments"]]
                    + [b.name for b in data["benches"]]
                    + [c.name for c in data["constraints"]]
                    + [h.name for h in data["harnesses"]]
                    + [u.get("name", "") for u in data["utils"] if isinstance(u, dict)])
                raise SystemExit(
                    f"No component named '{', '.join(self.generate_names)}' found. "
                    f"Available: {', '.join(available)}")

        if not any((interfaces, environments, benches, constraints, harnesses, utils)):
            raise SystemExit("No supported YAML definitions were found.")

        generated_files: List[Optional[Path]] = []
        if interfaces:
            generated_files.extend(self.generate_agents(interfaces))
        if environments:
            # 把**文档级**收集的 util_components 注入每个环境 —— 它们通常写在
            # 另一个 YAML 里（如 apb_util_comp.yaml），`parse_environment_model`
            # 看的是自己那份文档，拿不到。env_pkg 要靠它 `include` 那些裸 class
            #（predictor 等），否则 env / env_config 里 `apb_predictor apb_pred;`
            # 全是 "Invalid type"。
            for _env in environments:
                _env.utils = [{"name": u.get("name")} for u in utils
                              if isinstance(u, dict) and u.get("name")]
            generated_files.extend(self.generate_environments(environments))
        # env_name 已从 YAML 下线：bench / constraint 的 env 名从本次解析出的
        # environment 回填（都没写时取第一个 environment）
        default_env = environments[0].env_name if environments else ""
        if benches:
            for b in benches:
                if not b.env_name:
                    b.env_name = default_env
            generated_files.extend(self.generate_benches(benches))
        if constraints:
            for c in constraints:
                if not c.env_name:
                    c.env_name = default_env
            generated_files.extend(self.generate_constraints(constraints))
        if harnesses:
            generated_files.extend(self.generate_harnesses(harnesses))
        if utils:
            generated_files.extend(self.generate_utils(utils))
        if sc_preds:
            generated_files.extend(self.generate_scpreds(sc_preds))

        # ── ③ 整环境编译 filelist + Makefile（闭环：env + bench + tc_pkg 一键编译入口）──
        if environments:
            generated_files.extend(
                self._generate_env_filelists(environments, benches, harnesses, interfaces))

        # ── Generate overall README.md at output root ──
        readme_path = self.output_root / "README.md"
        if not self._should_skip(readme_path):
            try:
                generated_files.append(_generate_output_readme(
                    self.output_root,
                    list(interfaces) if interfaces else [],
                    list(environments) if environments else [],
                    list(benches) if benches else [],
                    list(harnesses) if harnesses else [],
                    list(sc_preds) if sc_preds else [],
                ))
            except Exception:
                pass  # README is optional, don't fail generation
        else:
            self.skipped += 1

        return [p for p in generated_files if p is not None]

    def _generate_env_filelists(self, environments: Iterable[EnvironmentModel],
                                benches: Iterable[BenchModel],
                                harnesses: Iterable[HarnessModel],
                                interfaces: Iterable[Any]) -> List[Path]:
        """渲染 {env}_pkg_filelist.f + 整环境 Makefile（env + bench + tc_pkg 一键编译入口）。

        interface_agents：interface 级 agent（agents/{name}_agent 目录布局）——
        文件清单与 Makefile 的 agent 段都按实际生成目录引用，不再用 env 级 agent 名。
        """
        rendered: List[Path] = []
        base_pkg_dir = Path(TEMPLATES_DIR).resolve().parent / "base_pkg"
        iface_agents = [{"name": getattr(a, "name", "")}
                        for a in interfaces if getattr(a, "name", "")]
        # filelist 里一律用 $WORK_PATH 而不是生成时刻的绝对路径：
        # WORK_PATH 由 output_root/Sourceme（`setenv WORK_PATH \`pwd\``）定义，
        # 故整份 filelist 可随目录整体搬迁/换机器，不必重新生成。
        # 相对基准 = output_root（源码 Sourceme 时 pwd 即此处）。
        _base_rel = _rel_or_abs(base_pkg_dir, self.output_root)
        for env in environments:
            ctx = {"environment": env, **env.to_context()}
            ctx["file_name"] = f"{env.env_name}_pkg_filelist.f"
            ctx["work_path"] = "$WORK_PATH"
            ctx["base_pkg_dir"] = f"$WORK_PATH/{_base_rel}"
            ctx["agent_dir"] = "$WORK_PATH/agents"
            ctx["env_dir"] = "$WORK_PATH/env"
            ctx["bench_dir"] = "$WORK_PATH/bench"
            ctx["bench_name"] = benches[0].name if benches else "BENCH"
            ctx["harnesses"] = list(harnesses)
            ctx["dut_path"] = "// TODO: 填入 DUT 源码路径（替换本行）"
            ctx["interface_agents"] = iface_agents

            target = self.output_root / "env" / f"{env.env_name}_pkg_filelist.f"
            if not self._should_skip(target):
                target.parent.mkdir(parents=True, exist_ok=True)
                content = self.renderer.render(
                    "environment_templates/env_pkg_filelist.f.j2", ctx)
                target.write_text(content, encoding="utf-8")
                rendered.append(target)
            else:
                self.skipped += 1

            # Sourceme：定义 $WORK_PATH（filelist / Makefile 的路径基准）。
            # 与 filelist 一并生成——否则引用 $WORK_PATH 的 filelist 没人定义它。
            # 放在生成目录根：`source Sourceme` 后 pwd 即 output_root。
            src_target = self.output_root / "Sourceme"
            if not self._should_skip(src_target):
                src_target.parent.mkdir(parents=True, exist_ok=True)
                src_target.write_text(
                    self.renderer.render("bench_templates/Sourceme", dict(ctx)),
                    encoding="utf-8")
                rendered.append(src_target)
            else:
                self.skipped += 1

            # 整环境 Makefile（生成目录根；Questar/VCS 双后端）
            mk_target = self.output_root / "Makefile"
            if not self._should_skip(mk_target):
                mk_ctx = dict(ctx)
                # Makefile 要读 bench 自己的字段（`dut_filelist` / `ral_filelist`），
                # 而 mk_ctx 原来只带了 `bench_name` 这个名字 —— 那两个清单因此在
                # 模板里恒为 undefined，DUT/RAL 一句都进不了编译命令。
                mk_ctx["bench"] = benches[0] if benches else None
                mk_ctx["file_name"] = "Makefile"
                mk_ctx["base_pkg_rel"] = _rel_or_abs(
                    base_pkg_dir, self.output_root)
                content = self.renderer.render(
                    "bench_templates/bench_makefile.j2", mk_ctx)
                content, _ = self.injector.inject(
                    content, {}, "Makefile", banner_prefix="# ")
                mk_target.write_text(content, encoding="utf-8")
                rendered.append(mk_target)
            else:
                self.skipped += 1
        return rendered


# ============================================================
#  Parameterized entry point for LangChain / programmatic use
# ============================================================

SUPPORTED_TOOL_TYPES = ("agent", "env", "bench", "harness", "constraint", "util")


def generate_uvm(tool_type: str, yaml_spec: str) -> str:
    """
    参数化 UVM 代码生成器 —— 根据 tool_type 和 YAML 输入生成 SystemVerilog。

    参数:
        tool_type:  类型 —— "agent" | "env" | "bench" | "constraint" | "util"
        yaml_spec:  YAML 规格字符串

    返回:
        生成的文件列表与代码摘要
    """
    if tool_type not in SUPPORTED_TOOL_TYPES:
        return (
            f"// Error: unsupported tool_type '{tool_type}'. "
            f"Supported: {', '.join(SUPPORTED_TOOL_TYPES)}"
        )

    try:
        data = yaml.safe_load(yaml_spec)
    except yaml.YAMLError as e:
        return f"// Error parsing YAML: {e}"

    if not isinstance(data, dict):
        return "// Error: YAML must be a dictionary"

    renderer = JinjaRenderer(TEMPLATES_DIR)

    # ── Agent ──────────────────────────────────────────────
    if tool_type == "agent":
        payload = data.get("interfaces") or data.get("interface")
        if payload is None:
            return "// Error: YAML must contain 'interfaces' or 'interface' key"
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            return "// Error: 'interfaces' must be a list or dict"

        results = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("agent_name")
            if not name:
                continue
            agent = AgentModel(
                name=name, agent_name=name,
                interface=item.get("interface", ""),
                interface_name=item.get("interface_name", item.get("interface", "")),
                clock=item.get("clock") or item.get("clk"),
                reset=item.get("reset"),
                protocol=item.get("protocol", ""),
                parameters=item.get("parameters", []),
                typedefs=_normalize_typedefs(item.get("typedefs")),
                ports=item.get("ports", []),
                transaction_vars=item.get("transaction_vars", []),
                transaction_constraints=item.get("transaction_constraints", []),
                config_vars=item.get("config_vars", []),
                config_constraints=item.get("config_constraints", []),
                response_info=item.get("response_info", {}),
                config=dict(item.get("config") or {}),
            )
            ctx = {"agent": agent, **agent.to_context()}
            files = []
            for entry in INTERFACE_TEMPLATES:
                tpl, pat, extra = _split_template_entry(entry)
                try:
                    c = renderer.render(tpl, {**ctx, **extra})
                    files.append(f"  {pat.format(agent_name=name)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(agent_name=name)}: ERR - {e}")
            results.append(f"Agent: {name}\n" + "\n".join(files))
        return "\n\n".join(results)

    # ── Environment ────────────────────────────────────────
    if tool_type == "env":
        payload = data.get("environment")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'environment' dict"
        name = payload.get("name") or "env"
        env_name = name      # env_name 已从 YAML 下线：生成前缀一律取 name
        agents = AgentCollection()
        for acfg in _normalize_agents_list(payload.get("agents")):
            aname = acfg.get("name") or acfg.get("agent_name")
            if not aname:
                continue
            agents.append(AgentModel(
                name=aname, agent_name=aname,
                interface=acfg.get("interface", aname),
                interface_name=acfg.get("interface", aname),
                clock=acfg.get("clock"), reset=acfg.get("reset"),
                agent_type=acfg.get("type", ""),
                is_master=_opt_bool(acfg.get("is_master")),
                active=_opt_bool(acfg.get("is_active")),
            ))
        clk_rst_vip = payload.get("clk_rst_vip") or {}
        if not clk_rst_vip and payload.get("clk_rst"):
            clk_rst_vip = {
                "enabled": True,
                "clocks": payload["clk_rst"].get("clocks", []),
                "resets": payload["clk_rst"].get("resets", []),
            }
        env = EnvironmentModel(
            name=name, env_name=env_name, agents=agents,
            subenvs=_normalize_subenvs(payload.get("subenvs", [])),
            vipenvs=_normalize_vipenvs(payload.get("vipenvs", [])),
            scoreboards=_normalize_scoreboards(payload.get("scoreboards", [])),
            analysis_components=_normalize_analysis_components(payload.get("analysis_components", [])),
            analysis_exports=_normalize_analysis_ports(payload.get("analysis_exports", [])),
            analysis_ports=_normalize_analysis_ports(payload.get("analysis_ports", [])),
            clk_rst_vip=clk_rst_vip,
            register_model=_normalize_register_model(
                payload.get("register_model") or payload.get("reg_adapter"),
                list(agents)),
            harness_connect=dict(payload.get("harness_connect") or {}),
            coverage_crosses=[
                [str(f) for f in c] for c in (payload.get("coverage_crosses") or [])
                if isinstance(c, (list, tuple)) and len(c) >= 2],
            config_vars=payload.get("config_vars", []),
            config_constraints=payload.get("config_constraints", []),
            tlm_connections=payload.get("tlm_connections", []),
            bench=payload.get("bench", {}),
            utils=[{"name": u.get("name")} for u in (payload.get("util_components") or [])
                   if isinstance(u, dict) and u.get("name")],
            tests=_normalize_tests(payload.get("tests", [])),
            batches=_normalize_batches(payload.get("batches", [])),
        )
        ctx = {"environment": env, **env.to_context()}
        files = []
        templates = list(ENVIRONMENT_ROOT_TEMPLATES + ENVIRONMENT_TEST_TEMPLATES
                         + ENVIRONMENT_SEQ_TEMPLATES)
        # 属性测试与上面那条路径同一条件 —— 两条都得管，否则 CLI 与这条
        # 字符串入口会给出不一样的产物
        if env.tests:
            templates += ENVIRONMENT_ATTR_TEST_TEMPLATES
        for tpl, pat in templates:
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(env_name=env_name)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(env_name=env_name)}: ERR - {e}")
        return f"Environment: {env_name}\n" + "\n".join(files)

    # ── Harness ────────────────────────────────────────────
    if tool_type == "harness":
        payload = data.get("harness")
        if payload is None and isinstance(data.get("bench"), dict):
            payload = data["bench"].get("harness")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'harness' dict"
        harness = _normalize_harness(payload)
        if harness is None:
            return "// Error: harness YAML missing 'name'"
        ctx = {"harness": harness, **harness.to_context()}
        c = renderer.render(HARNESS_TEMPLATES[0][0], ctx)
        return f"Harness: {harness.name}\n  {harness.name}.sv: {len(c)} chars"

    # ── Bench ──────────────────────────────────────────────
    if tool_type == "bench":
        payload = data.get("bench")
        if payload is None or not isinstance(payload, dict):
            return "// Error: YAML must contain 'bench' dict"
        agents_b: dict = {}
        for acfg in _normalize_agents_list(payload.get("agents")):
            aname = acfg.get("name")
            if not aname:
                continue
            agents_b[aname] = BenchAgentEntry(
                name=aname,
                interface=acfg.get("interface", ""),
                clock=acfg.get("clock", "clk"),
                reset=acfg.get("reset", "rst_n"),
                instance=acfg.get("instance", ""),
                config_db_path=acfg.get("config_db_path", ""),
                connections=acfg.get("connections", []),
                agent_type=acfg.get("type", ""),
            )
        bench = BenchModel(
            name=payload.get("name") or payload.get("bench_name", "bench"),
            env_name="",     # env_name 已从 YAML 下线（下游按 environment 回填）
            timeout=payload.get("timeout", "10ms"),
            include_assertions=payload.get("include_assertions", False),
            clk_rst=payload.get("clk_rst_if") or payload.get("clk_rst") or {},
            wire_decls=payload.get("wire_decls", []),
            assignments=payload.get("assignments", []),
            agents=agents_b,
            harness=dict(payload.get("harness") or {}),
            dut_instance=payload.get("dut_instance", "u_dut"),
            uvm_config=payload.get("uvm_config", {}),
            wave_dump=payload.get("wave_dump", {}),
            simulation=payload.get("simulation", {}),
        )
        ctx = {"bench": bench.to_context()}
        tpl = BENCH_TEMPLATES[0][0]
        c = renderer.render(tpl, ctx)
        return f"Bench: {bench.name}\n  {bench.name}_tb_top.sv: {len(c)} chars"

    # ── Constraint ─────────────────────────────────────────
    if tool_type == "constraint":
        proj = data.get("constraint") or {}
        cname = proj.get("name") or proj.get("constraint_name") or "constraint"
        cenv = proj.get("env") or ""     # env_name 已下线，改用 env
        constraint = ConstraintModel(
            name=cname, env_name=cenv,
            transactions=data.get("transactions", []),
            policies=data.get("policies", []),
            combinator=data.get("combinator", {
                "default_mode": "APPLY_ALL",
                "modes": ["APPLY_ALL", "APPLY_WEIGHTED", "APPLY_FIRST_MATCH",
                          "APPLY_SEQUENTIAL", "APPLY_CHAIN"],
            }),
        )
        ctx = constraint.to_context()
        files = []
        for tpl, pat in ENV_CONSTRAINT_TEMPLATES:
            try:
                c = renderer.render(tpl, ctx)
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: {len(c)} chars")
            except Exception as e:
                files.append(f"  {pat.format(project_name=cname, env_name=cenv)}: ERR - {e}")
        return f"Constraint: {cname}\n" + "\n".join(files)

    # ── Util ───────────────────────────────────────────────
    if tool_type == "util":
        components = data.get("util_components")
        if components is None or not isinstance(components, list):
            return "// Error: YAML must contain 'util_components' list"
        results = []
        _util_templates = [
            ("environment_templates/util_comp.sv.j2", "{name}_util.sv"),
        ]
        for comp in components:
            if not isinstance(comp, dict):
                continue
            uname = comp.get("name", "util")
            ctx = {
                "name": uname,
                "type": comp.get("type", "uvm_component"),
                "description": comp.get("description", ""),
                "analysis_exports": comp.get("analysis_exports", []),
                "analysis_ports": comp.get("analysis_ports", []),
            }
            files = []
            for tpl, pat in _util_templates:
                try:
                    c = renderer.render(tpl, ctx)
                    files.append(f"  {pat.format(name=uname)}: {len(c)} chars")
                except Exception as e:
                    files.append(f"  {pat.format(name=uname)}: ERR - {e}")
            results.append(f"Util: {uname}\n" + "\n".join(files))
        return "\n\n".join(results)

    return f"// Error: unknown tool_type '{tool_type}'"


# ============================================================
#  CLI entry point
# ============================================================

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gen_uvm.py",
        description="Generate UVM SystemVerilog from YAML descriptors (tool_uvm).",
    )
    parser.add_argument(
        "--version", action="version",
        version=f"%(prog)s (tool_uvm) {__version__}",
        help="Show script version number and exit.",
    )
    parser.add_argument(
        "-i", "--input", nargs="+", default=["."],
        help="Input YAML file(s) or directories containing YAML files. "
             "A .f list file is also accepted and expanded into the paths it lists.",
    )
    parser.add_argument(
        "-f", "--file", dest="input", nargs="+",
        help="Same as -i/--input: YAML files / directories, or a .f list file "
             "(one path per line; '#' and '//' start comments).",
    )
    parser.add_argument(
        "-d", "--dest_dir", "--output", dest="dest_dir", default="generated",
        help="Specify a destination directory for output. Default is $CWD/generated.",
    )
    parser.add_argument(
        "-o", "--overwrite", action="store_true",
        help="Overwrite existing output files. Default behavior is to skip files "
             "if they already exist in the destination directory.",
    )
    parser.add_argument(
        "-g", "--generate", metavar="NAME",
        help="Only produce the specified component (by name). By default, all "
             "components defined by the input configuration files will be generated.",
    )
    parser.add_argument(
        "-t", "--template_dir", metavar="DIR",
        help="Override the location where templates for generated files are sourced.",
    )
    parser.add_argument(
        "-c", "--clean", action="store_true",
        help="Clean up generated code (banner-signed files only) instead of producing code.",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Suppress output while running.",
    )
    parser.add_argument(
        "-m", "--merge_source", metavar="DIR",
        help="Enable auto-merge flow, pulling hand-edited pragma custom blocks from "
             "the specified directory. Updates from YAML will be overlaid on top of "
             "the specified directory. Backup of the original source will be made by default.",
    )
    parser.add_argument(
        "-s", "--merge_skip_missing_blocks", action="store_true",
        help="Continue the merge even if a labeled block was found in old source that "
             "can't be mapped to anything in the new output. A report of all such files "
             "and labels will be produced at the end of the run. By default, missing "
             "blocks will raise an error.",
    )
    parser.add_argument(
        "--merge_no_backup", action="store_true",
        help="Do not produce a backup of the original merge source.",
    )
    parser.add_argument(
        "--merge_debug", action="store_true",
        help="Provide an intermediate unmerged output directory for debug purposes. "
             "The location of this directory is <dest_dir>/merge_debug.",
    )
    parser.add_argument(
        "--merge_verbose", action="store_true",
        help="Output details on names of files and named blocks that were affected "
             "during the merging process.",
    )
    parser.add_argument(
        "--gate", action="store_true",
        help="生成后对每个 agent 的 loopback 自检跑编译+仿真门禁（无 vlog/vcs 则跳过）。",
    )
    parser.add_argument(
        "--skip-schema-check", action="store_true",
        help="跳过 Phase 0 YAML schema 语法检查（缺省执行，schema error 阻断生成）。",
    )
    parser.add_argument(
        "--report-json", action="store_true",
        help="输出结构化生成报告 generation_report.json（供 Agent 决策/签核证据包引用）。",
    )
    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List the supported Jinja2 templates and exit.",
    )
    args = parser.parse_args(argv)

    def log(msg: str) -> None:
        if not args.quiet:
            print(msg)

    dest_root = Path(args.dest_dir).expanduser().resolve()

    # ── -c/--clean：清理带签名的生成文件 ──
    if args.clean:
        removed = _clean_generated(dest_root)
        log(f"Cleaned {removed} generated file(s) from {dest_root}")
        return 0

    if args.list_templates:
        print("Supported template sets:")
        print("  interface_templates:")
        seen: set = set()
        for entry in INTERFACE_TEMPLATES:
            if entry[0] not in seen:   # 合并模板（port 参数化）注册两次，只列一次
                seen.add(entry[0])
                print(f"    {entry[0]}")
        print("  environment_root_templates:")
        for tpl, _ in ENVIRONMENT_ROOT_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_test_templates:")
        for tpl, _ in ENVIRONMENT_TEST_TEMPLATES:
            print(f"    {tpl}")
        print("  environment_seq_templates:")
        for tpl, _ in ENVIRONMENT_SEQ_TEMPLATES:
            print(f"    {tpl}")
        print("  env_constraint_templates:")
        for tpl, _ in ENV_CONSTRAINT_TEMPLATES:
            print(f"    {tpl}")
        print("  bench_templates:")
        for tpl, _ in BENCH_TEMPLATES:
            print(f"    {tpl}")
        return 0

    input_paths = [Path(x).expanduser() for x in args.input]
    dest_root.mkdir(parents=True, exist_ok=True)

    templates_dir = Path(args.template_dir).expanduser().resolve() if args.template_dir else TEMPLATES_DIR
    renderer = JinjaRenderer(templates_dir)

    # ── 合并流程 ──
    injector = RegionInjector(
        merge_source=args.merge_source,
        skip_missing=args.merge_skip_missing_blocks,
        debug_dir=(dest_root / "merge_debug") if args.merge_debug else None,
    )
    if args.merge_source and not args.merge_no_backup:
        try:
            backup = backup_merge_source(Path(args.merge_source).expanduser())
            log(f"Merge source backed up to: {backup}")
        except OSError as exc:
            log(f"Warning: backup failed: {exc}")

    generator = UVMGenerator(
        renderer, dest_root,
        injector=injector,
        overwrite=args.overwrite,
        generate_names=[args.generate] if args.generate else None,
        quiet=args.quiet,
        schema_check=not args.skip_schema_check,
    )

    try:
        generated_files = generator.run(input_paths)
    except RegionError as exc:
        print(f"Error: {exc}", file=__import__("sys").stderr)
        return 1

    skipped = generator.skipped
    log(f"Generated {len(generated_files)} file(s) into: {dest_root}"
        + (f" (skipped {skipped} existing)" if skipped else ""))
    for path in generated_files:
        log(f"  {path.relative_to(dest_root)}")

    # ── 校验摘要（可审计）──
    n_schema_warn = sum(1 for i in generator.schema_issues if i.severity == "warning")
    if n_schema_warn:
        log(f"Schema check: {n_schema_warn} warning(s) — see {dest_root / 'schema_report.txt'}")
    n_warn = sum(1 for i in generator.validation_issues if i.severity == "warning")
    if n_warn:
        log(f"Semantic check: {n_warn} warning(s) — see {dest_root / 'validation_report.txt'}")

    # ── P0-4: 编译仿真门禁 ──
    gate_results: List[Dict[str, str]] = []
    if args.gate:
        log("Gate: running loopback compile+sim ...")
        gate_results = _run_gate(dest_root)
        for r in gate_results:
            if r.get("status") == "skip":
                log(f"  [SKIP] {r['agent']} — {r.get('reason', '')}")
            else:
                log(f"  [{r['status'].upper()}] {r['agent']} (sim={r.get('sim')})")

    # ── P2-4: 结构化 JSON 报告 ──
    if args.report_json:
        report_path = _write_report_json(
            dest_root,
            generated=len(generated_files),
            skipped=skipped,
            validation_issues=generator.validation_issues,
            merge_reports=injector.report,
            load_errors=injector.load_errors,
            gate_results=gate_results,
            schema_issues=generator.schema_issues,
            inputs=input_paths,
        )
        log(f"Report: {report_path}")

    # ── 合并报告 ──
    if args.merge_source:
        report = injector.report
        merged_files = [r for r in report if r.blocks]
        total_blocks = sum(len(r.blocks) for r in report)
        merged_count = sum(len([b for b in r.blocks if b.source == "merged"]) for r in report)
        log(f"Merge: {len(merged_files)} file(s) with regions, "
            f"{total_blocks} block(s) updated ({merged_count} from hand-edited source)")
        missing = [(r.relpath, slot) for r in report for slot in r.missing]
        if missing:
            log(f"Merge: {len(missing)} block(s) in old source could not be mapped (skipped):")
            for rel, slot in missing:
                log(f"  [{rel}] {slot}")
        if injector.load_errors:
            log(f"Merge: {len(injector.load_errors)} file(s) skipped due to malformed regions:")
            for err in injector.load_errors:
                log(f"  {err}")
        if args.merge_verbose:
            for r in report:
                if not r.blocks and not r.missing:
                    continue
                log(f"  [{r.relpath}]")
                for b in r.blocks:
                    log(f"    {b.slot} <- {b.source} ({b.lines} lines)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
