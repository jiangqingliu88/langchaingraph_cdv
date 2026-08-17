"""
Tool Documentation Generator — 从 ToolManifest 自动生成文档 (Phase 3)

功能:
  1. 生成 Markdown 格式的工具使用文档
  2. 生成 LLM Prompt 使用的工具描述
  3. 生成 JSON Schema 可视化
  4. 批量生成所有工具的索引页面

用法:
  from src.layers.l2_orchestration.tool_doc_generator import ToolDocGenerator
  gen = ToolDocGenerator()
  gen.generate_all("docs/tools/")
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.layers.l2_orchestration.communication.tool_protocol import ToolManifest, ToolRisk, ToolStatus
from src.layers.l2_orchestration.communication.tool_hub import ToolHub


class ToolDocGenerator:
    """工具文档自动生成器"""

    def __init__(self, hub: ToolHub = None):
        self._hub = hub or ToolHub.get_instance()

    # ═══════════════════════════════════════════════════════════
    # 单工具文档
    # ═══════════════════════════════════════════════════════════

    def generate_tool_md(self, manifest: ToolManifest, detail_level: str = "full") -> str:
        """为单个工具生成 Markdown 文档"""
        lines = [f"# {manifest.name}", ""]

        # Badges
        risk_emoji = {"safe": "🟢", "write": "🟡", "danger": "🔴"}
        status_emoji = {"active": "✅", "deprecated": "⚠️", "experimental": "🧪", "disabled": "🚫"}
        lines.append(
            f"{risk_emoji.get(manifest.risk_level.value, '⚪')} "
            f"Risk: `{manifest.risk_level.value}` | "
            f"{status_emoji.get(manifest.status.value, '❓')} "
            f"Status: `{manifest.status.value}` | "
            f"Version: `{manifest.version}`"
        )
        lines.append("")

        # Description
        lines.append(f"## Description")
        lines.append(f"{manifest.description}")
        lines.append("")

        # Metadata table
        lines.append("## Metadata")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|-------|-------|")
        lines.append(f"| **Author** | {manifest.author or 'N/A'} |")
        lines.append(f"| **License** | {manifest.license or 'N/A'} |")
        lines.append(f"| **Category** | {manifest.category or 'N/A'} |")
        lines.append(f"| **Tags** | {', '.join(f'`{t}`' for t in manifest.tags) or 'N/A'} |")
        lines.append(f"| **Timeout** | {manifest.timeout_s}s |")
        lines.append(f"| **Retry** | {manifest.retry_count}x |")
        lines.append(f"| **Execution** | {manifest.execution_mode.value} |")
        lines.append("")

        # Dependencies
        if manifest.requires_binaries or manifest.requires_packages:
            lines.append("## Dependencies")
            lines.append("")
            if manifest.requires_binaries:
                lines.append("**Required Binaries:**")
                for b in manifest.requires_binaries:
                    lines.append(f"- `{b}`")
                lines.append("")
            if manifest.requires_packages:
                lines.append("**Required Python Packages:**")
                for p in manifest.requires_packages:
                    lines.append(f"- `{p}`")
                lines.append("")
            if manifest.requires_python:
                lines.append(f"**Python:** {manifest.requires_python}")
                lines.append("")

        # Input Schema
        if manifest.input_schema and manifest.input_schema.get("properties"):
            lines.append("## Input Parameters")
            lines.append("")
            lines.append("| Parameter | Type | Required | Description |")
            lines.append("|-----------|------|----------|-------------|")
            required = manifest.input_schema.get("required", [])
            for name, prop in manifest.input_schema.get("properties", {}).items():
                ptype = prop.get("type", "string")
                is_req = "✅" if name in required else "❌"
                desc = prop.get("description", "")
                if "enum" in prop:
                    desc += f" (enum: {prop['enum']})"
                if "default" in prop:
                    desc += f" [default: `{prop['default']}`]"
                lines.append(f"| `{name}` | `{ptype}` | {is_req} | {desc} |")
            lines.append("")

        # Output Schema
        if manifest.output_schema and manifest.output_schema.get("properties"):
            lines.append("## Output")
            lines.append("")
            lines.append("| Field | Type | Description |")
            lines.append("|-------|------|-------------|")
            for name, prop in manifest.output_schema.get("properties", {}).items():
                lines.append(f"| `{name}` | `{prop.get('type', 'string')}` | {prop.get('description', '')} |")
            lines.append("")

        # Examples
        if manifest.examples:
            lines.append("## Examples")
            lines.append("")
            for i, ex in enumerate(manifest.examples, 1):
                lines.append(f"### Example {i}: {ex.description}")
                lines.append("")
                lines.append("```json")
                lines.append(json.dumps(ex.args, indent=2, ensure_ascii=False))
                lines.append("```")
                if ex.expected_output:
                    lines.append(f"**Expected Output:** {ex.expected_output}")
                lines.append("")

        # Tips
        if manifest.tips:
            lines.append("## Tips")
            lines.append("")
            for tip in manifest.tips:
                lines.append(f"- {tip}")
            lines.append("")

        # LLM Usage
        if detail_level == "full":
            lines.append("## LLM Integration")
            lines.append("")
            lines.append("### Function Calling Spec")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(manifest.to_llm_function_spec(), indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")

            # Audit stats
            stats = self._hub.get_stats(manifest.name)
            if stats.get("calls", 0) > 0:
                lines.append("### Usage Statistics")
                lines.append("")
                lines.append(f"- Total calls: {stats['calls']}")
                lines.append(f"- Failures: {stats['failures']}")
                lines.append(f"- Total time: {stats['total_time_s']:.1f}s")
                lines.append("")

        return "\n".join(lines)

    def generate_tool_prompt(self, manifest: ToolManifest) -> str:
        """生成 LLM Prompt 中使用的工具描述"""
        lines = [f"## {manifest.name}"]
        lines.append(f"**When to use:** {manifest.description}")
        lines.append("")

        # Parameters summary
        props = manifest.input_schema.get("properties", {})
        required = manifest.input_schema.get("required", [])
        if props:
            lines.append("**Parameters:**")
            for name, prop in props.items():
                req_mark = " (required)" if name in required else ""
                lines.append(f"- `{name}`: {prop.get('type', 'string')}{req_mark} — {prop.get('description', '')[:100]}")
            lines.append("")

        if manifest.tips:
            lines.append("**Tips:** " + "; ".join(manifest.tips))
            lines.append("")

        return "\n".join(lines)

    # ═══════════════════════════════════════════════════════════
    # 批量生成
    # ═══════════════════════════════════════════════════════════

    def generate_all(self, output_dir: str = "docs/tools") -> Dict[str, str]:
        """为所有已注册工具生成文档"""
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        generated = {}

        manifests = self._hub.list_all()
        for manifest in manifests:
            md = self.generate_tool_md(manifest)
            filename = f"{manifest.name}.md"
            (out_path / filename).write_text(md, encoding="utf-8")
            generated[manifest.name] = str(out_path / filename)

        # 生成索引
        index = self.generate_index(manifests)
        (out_path / "index.md").write_text(index, encoding="utf-8")
        generated["index"] = str(out_path / "index.md")

        # 生成 LLM prompt 文件
        all_prompts = []
        for manifest in manifests:
            all_prompts.append(self.generate_tool_prompt(manifest))
        (out_path / "llm_tools_prompt.md").write_text(
            "\n---\n".join(all_prompts), encoding="utf-8"
        )
        generated["llm_prompt"] = str(out_path / "llm_tools_prompt.md")

        return generated

    def generate_index(self, manifests: List[ToolManifest] = None) -> str:
        """生成工具索引页面"""
        if manifests is None:
            manifests = self._hub.list_all()

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            f"# Tool Index",
            f"",
            f"> Generated: {now} | Total tools: {len(manifests)}",
            f"",
            "## By Category",
            "",
        ]

        # Group by category
        by_cat: Dict[str, List[ToolManifest]] = {}
        for m in manifests:
            cat = m.category or "uncategorized"
            by_cat.setdefault(cat, []).append(m)

        for cat in sorted(by_cat.keys()):
            lines.append(f"### {cat.title() or 'Uncategorized'}")
            lines.append("")
            lines.append("| Tool | Version | Risk | Description |")
            lines.append("|------|---------|------|-------------|")
            for m in by_cat[cat]:
                risk_icon = {"safe": "🟢", "write": "🟡", "danger": "🔴"}.get(m.risk_level.value, "⚪")
                desc = m.description[:80] + ("..." if len(m.description) > 80 else "")
                lines.append(f"| [{m.name}]({m.name}.md) | {m.version} | {risk_icon} | {desc} |")
            lines.append("")

        # By tag
        lines.append("## By Tag")
        lines.append("")
        by_tag: Dict[str, List[str]] = {}
        for m in manifests:
            for tag in m.tags:
                by_tag.setdefault(tag, []).append(m.name)

        for tag in sorted(by_tag.keys()):
            tool_links = ", ".join(f"[{n}]({n}.md)" for n in by_tag[tag])
            lines.append(f"- **{tag}**: {tool_links}")

        lines.append("")
        lines.append("---")
        lines.append(f"*Auto-generated by SignOffAI ToolDocGenerator at {now}*")

        return "\n".join(lines)
