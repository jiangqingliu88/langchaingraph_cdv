"""
Document Serializer — MD ↔ 结构化 JSON 双向转换

支持 SignOffAI 标准格式:
  # 模块名（层级）
  <!-- 元数据 -->
  ## 1. 概述
  ## 2. 功能需求
  ### 需求标题
  **级别**：P0  **类型**：FUNCTIONAL  **描述**：...  **验收标准**：...
  ## 3. 接口规范
  ## 4. 时序约束
  ## 5. 功耗约束
"""

from __future__ import annotations

import re, yaml, json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# Pydantic-style 数据模型
# ═══════════════════════════════════════════════════════════════

@dataclass
class InterfaceSpec:
    name: str = ""
    width: int = 1
    direction: str = "INPUT"
    protocol: str = ""
    description: str = ""


@dataclass
class TimingConstraint:
    signal_a: str = ""
    signal_b: str = ""
    relation: str = "≥"  # ≥ ≤ = setup hold
    cycles: float = 1.0
    description: str = ""


@dataclass
class PowerConstraint:
    mode: str = ""
    power_mw: float = 0.0
    description: str = ""


@dataclass
class RequirementItem:
    title: str = ""
    level: str = "P0"
    req_type: str = "FUNCTIONAL"  # FUNCTIONAL/CONTROL/ERROR/TIMING/POWER
    description: str = ""
    acceptance: str = ""


@dataclass
class DocumentMeta:
    module: str = ""
    level: str = "BT"
    parent: str = ""
    process: str = ""
    frequency: str = ""
    data_width: int = 32
    interfaces: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    sub_modules: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredDocument:
    """完整的结构化文档"""
    meta: DocumentMeta = field(default_factory=DocumentMeta)
    overview: str = ""
    requirements: List[RequirementItem] = field(default_factory=list)
    interfaces: List[InterfaceSpec] = field(default_factory=list)
    timing_constraints: List[TimingConstraint] = field(default_factory=list)
    power_constraints: List[PowerConstraint] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "meta": {k: v for k, v in self.meta.__dict__.items() if v},
            "overview": self.overview,
            "requirements": [r.__dict__ for r in self.requirements],
            "interfaces": [i.__dict__ for i in self.interfaces],
            "timing_constraints": [t.__dict__ for t in self.timing_constraints],
            "power_constraints": [p.__dict__ for p in self.power_constraints],
        }

    @classmethod
    def from_dict(cls, data: dict) -> StructuredDocument:
        doc = cls()
        if "meta" in data:
            doc.meta = DocumentMeta(**data["meta"])
        doc.overview = data.get("overview", "")
        doc.requirements = [RequirementItem(**r) for r in data.get("requirements", [])]
        doc.interfaces = [InterfaceSpec(**i) for i in data.get("interfaces", [])]
        doc.timing_constraints = [TimingConstraint(**t) for t in data.get("timing_constraints", [])]
        doc.power_constraints = [PowerConstraint(**p) for p in data.get("power_constraints", [])]
        return doc


# ═══════════════════════════════════════════════════════════════
# DocumentSerializer: MD ↔ StructuredDocument
# ═══════════════════════════════════════════════════════════════

class DocumentSerializer:
    """MD ↔ 结构化 JSON 双向转换"""

    # ── MD → StructuredDocument ──

    def md_to_doc(self, md_text: str) -> StructuredDocument:
        doc = StructuredDocument()
        doc.meta = self._parse_metadata(md_text)

        # 解析各章节
        sections = self._split_sections(md_text)

        doc.overview = sections.get("1. 概述", sections.get("概述", ""))
        doc.requirements = self._parse_requirements(sections.get("2. 功能需求", sections.get("功能需求", "")))
        doc.interfaces = self._parse_interfaces(sections.get("3. 接口规范", sections.get("接口规范", "")))
        doc.timing_constraints = self._parse_timing(sections.get("4. 时序约束", sections.get("时序约束", "")))
        doc.power_constraints = self._parse_power(sections.get("5. 功耗约束", sections.get("功耗约束", "")))

        return doc

    def _parse_metadata(self, md: str) -> DocumentMeta:
        """从 HTML 注释提取元数据"""
        meta = DocumentMeta()
        m = re.search(r'<!--\s*(.*?)\s*-->', md, re.DOTALL)
        if not m:
            # 从标题提取
            title_m = re.search(r'^#\s+(.+)', md, re.MULTILINE)
            if title_m:
                meta.module = title_m.group(1).split("（")[0].strip()
            return meta

        meta_text = m.group(1)
        for line in meta_text.split("\n"):
            line = line.strip()
            if ":" not in line:
                continue
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if key == "module": meta.module = val.strip("'\"")
            elif key == "parent": meta.parent = val.strip("'\"")
            elif key == "level": meta.level = val.strip("'\"")
            elif key == "process": meta.process = val.strip("'\"")
            elif key == "frequency": meta.frequency = val.strip("'\"")
            elif key == "data_width": meta.data_width = int(val) if val.isdigit() else 32
            elif key == "interfaces":
                ifcs = re.findall(r'[\w_]+', val)
                meta.interfaces = ifcs
            elif key == "requirements":
                reqs = re.findall(r'REQ_\w+', val)
                meta.requirements = reqs
            elif key == "sub_modules":
                mods = re.findall(r'[\w_]+', val)
                meta.sub_modules = mods
            else:
                meta.extra[key] = val
        return meta

    def _split_sections(self, md: str) -> Dict[str, str]:
        """按 H2 标题拆分章节"""
        sections = {}
        # Remove metadata comment
        md = re.sub(r'<!--.*?-->', '', md, flags=re.DOTALL)
        # Split by ##
        parts = re.split(r'\n(?=## )', md)
        for part in parts:
            m = re.match(r'##\s+(.+)', part)
            if m:
                title = m.group(1).strip()
                content = part[m.end():].strip()
                # Clean the section number prefix
                clean_title = re.sub(r'^\d+[.\s]*', '', title)
                sections[title] = content
                sections[clean_title] = content
        return sections

    def _parse_requirements(self, section: str) -> List[RequirementItem]:
        if not section:
            return []
        reqs = []
        # Split by ###
        blocks = re.split(r'\n(?=### )', section)
        for block in blocks:
            m = re.match(r'###\s+(.+)', block)
            if not m:
                continue
            title = m.group(1).strip()
            body = block[m.end():]
            req = RequirementItem(title=title)
            for line in body.split("\n"):
                line = line.strip()
                if line.startswith("**级别**"):
                    mm = re.search(r'P\d', line)
                    if mm: req.level = mm.group(0)
                elif line.startswith("**类型**"):
                    mm = re.search(r'[A-Z]+', line)
                    if mm: req.req_type = mm.group(0)
                elif line.startswith("**描述**"):
                    req.description = line.replace("**描述**", "").strip("：: ").strip()
                elif line.startswith("**验收标准**"):
                    req.acceptance = line.replace("**验收标准**", "").strip("：: ").strip()
            if title and title != req.title:  # should not happen but be safe
                pass
            reqs.append(req)
        return reqs

    def _parse_interfaces(self, section: str) -> List[InterfaceSpec]:
        if not section:
            return []
        ifaces = []
        # Try table format first
        rows = re.findall(r'\|\s*(\w[\w\[\]:]*)\s*\|\s*(\d+)\s*\|\s*(INPUT|OUTPUT|INOUT)\s*\|\s*(\w*)\s*\|\s*(.*?)\s*\|', section)
        for name, width, direction, protocol, desc in rows:
            ifaces.append(InterfaceSpec(name=name.strip(), width=int(width), direction=direction.strip(), protocol=protocol.strip(), description=desc.strip()))
        if ifaces:
            return ifaces
        # Try list format: ### 接口：xxx
        for block in re.split(r'\n(?=### )', section):
            m = re.match(r'###\s*(?:接口|Interface)[：:]\s*(.+)', block, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                iface = InterfaceSpec(name=name)
                for line in block.split("\n"):
                    line = line.strip()
                    dir_m = re.match(r'方向[：:]\s*(\w+)', line) or re.match(r'direction[：:]\s*(\w+)', line, re.IGNORECASE)
                    if dir_m: iface.direction = dir_m.group(1).upper()
                    w_m = re.match(r'(?:宽度|width)[：:]\s*(\d+)', line, re.IGNORECASE)
                    if w_m: iface.width = int(w_m.group(1))
                    p_m = re.match(r'(?:协议|protocol)[：:]\s*(\S+)', line, re.IGNORECASE)
                    if p_m: iface.protocol = p_m.group(1)
                ifaces.append(iface)
        return ifaces

    def _parse_timing(self, section: str) -> List[TimingConstraint]:
        if not section:
            return []
        constraints = []
        rows = re.findall(r'\|\s*(\S[\S\s]*?)\s*\|\s*([≤≥\w\s]*?)\s*\|\s*(\d+\.?\d*\s*\w*)\s*\|\s*(.*?)\s*\|', section)
        if not rows:
            rows = re.findall(r'\|\s*(\S+)\s*\|\s*(\S+)\s*\|\s*([≥≤=]|setup|hold)\s*\|\s*([\d.]+)\s*\|\s*(.*?)\s*\|', section)
        for sig_a, sig_b, rel, cycles, desc in rows:
            constraints.append(TimingConstraint(signal_a=sig_a.strip(), signal_b=sig_b.strip(), relation=rel.strip(), cycles=float(cycles), description=desc.strip()))
        return constraints

    def _parse_power(self, section: str) -> List[PowerConstraint]:
        if not section:
            return []
        constraints = []
        rows = re.findall(r'\|\s*(\S[\w\s()]*?)\s*\|\s*[≤]*\s*([\d.]+)\s*m?W\s*\|\s*(.*?)\s*\|', section)
        for mode, power, desc in rows:
            constraints.append(PowerConstraint(mode=mode.strip(), power_mw=float(power), description=desc.strip()))
        return constraints

    # ── StructuredDocument → MD ──

    def doc_to_md(self, doc: StructuredDocument) -> str:
        lines = []

        # 标题
        title = doc.meta.module or "Untitled"
        if doc.meta.level:
            level_names = {"CHIP": "芯片级", "ST": "系统级", "IT": "集成级", "BT": "模块级", "UT": "单元级"}
            title += f"（{level_names.get(doc.meta.level, doc.meta.level)}）"
        lines.append(f"# {title}")

        # 元数据注释
        meta_lines = ["<!--"]
        for key in ["module", "parent", "level", "process", "frequency", "data_width"]:
            val = getattr(doc.meta, key, "")
            if val:
                meta_lines.append(f"  {key}: {val}")
        if doc.meta.interfaces:
            meta_lines.append(f"  interfaces: [{', '.join(doc.meta.interfaces)}]")
        if doc.meta.requirements:
            meta_lines.append(f"  requirements: [{', '.join(doc.meta.requirements)}]")
        if doc.meta.sub_modules:
            meta_lines.append(f"  sub_modules: [{', '.join(doc.meta.sub_modules)}]")
        for k, v in doc.meta.extra.items():
            meta_lines.append(f"  {k}: {v}")
        meta_lines.append("-->")
        lines.extend(meta_lines)
        lines.append("")

        # 1. 概述
        lines.append("## 1. 概述")
        lines.append(doc.overview or "待补充")
        lines.append("")

        # 2. 功能需求
        lines.append("## 2. 功能需求")
        lines.append("")
        for i, req in enumerate(doc.requirements):
            lines.append(f"### {req.title}")
            lines.append(f"**级别**：{req.level}")
            lines.append(f"**类型**：{req.req_type}")
            lines.append(f"**描述**：{req.description or '待补充'}")
            lines.append(f"**验收标准**：{req.acceptance or '待补充'}")
            lines.append("")
        if not doc.requirements:
            lines.append("待补充")
            lines.append("")

        # 3. 接口规范
        lines.append("## 3. 接口规范")
        lines.append("")
        if doc.interfaces:
            lines.append("| 信号 | 位宽 | 方向 | 协议 | 描述 |")
            lines.append("|------|------|------|------|------|")
            for iface in doc.interfaces:
                lines.append(f"| {iface.name} | {iface.width} | {iface.direction} | {iface.protocol or '—'} | {iface.description or ''} |")
        else:
            lines.append("待补充")
        lines.append("")

        # 4. 时序约束
        lines.append("## 4. 时序约束")
        lines.append("")
        if doc.timing_constraints:
            lines.append("| 信号 A | 信号 B | 关系 | 周期 | 说明 |")
            lines.append("|--------|--------|------|------|------|")
            for tc in doc.timing_constraints:
                lines.append(f"| {tc.signal_a} | {tc.signal_b} | {tc.relation} | {tc.cycles} | {tc.description} |")
        else:
            lines.append("待补充")
        lines.append("")

        # 5. 功耗约束
        lines.append("## 5. 功耗约束")
        lines.append("")
        if doc.power_constraints:
            lines.append("| 模式 | 功耗 | 说明 |")
            lines.append("|------|------|------|")
            for pc in doc.power_constraints:
                lines.append(f"| {pc.mode} | ≤ {pc.power_mw}mW | {pc.description} |")
        else:
            lines.append("待补充")
        lines.append("")

        return "\n".join(lines)
