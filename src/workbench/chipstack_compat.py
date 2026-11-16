"""ChipStack 2.0 对齐层 —— 接口名、配置查找、Skills、离线产物浏览器。

这里只做**适配与诚实映射**，不伪造 Cadence 专有能力：

* CLI 名（`mental-model`、`formal-agent`、`uvm-agentic-flow`…）来自
  `agent_plane.domains`，真实执行仍走既有 Agent/Harness/Engine；
* 配置查找顺序与 `cli_config.yaml` 组按 2.0 手册实现；
* `seed-skills` / `install-skills claude-code` 复制仓库内 skills；
* `artifact-review-html` 生成单文件离线浏览器（MONITOR 状态 + ARTIFACTS 编辑）。

Jasper / Verisium / xrun / Stratus 等专有工具不在本仓库内，缺失时保持
`NOT_RUN` / `BLOCKED_EDA_MISSING`，不补造报告。
"""
from __future__ import annotations

import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from src.agent_plane.domains import all_agents
from src.runtime_plane.core.project_layout import (
    CLI_CONFIG_NAME,
    RESERVED_ARTIFACT_NAMES,
    default_home,
    install_root,
)

#: 2.0 手册正文列出的 TUI 模式（CLI choices 用这一组）
GUIDE_TUI_MODES = (
    "mental_model", "formal", "functional_coverage", "uvm",
    "rtl_designer", "debug", "workflows",
)

#: 手册 TUI 模式 → 本仓库 AgentMode preset
TUI_MODES: Dict[str, str] = {
    "mental_model": "mental_model",
    "formal": "formal",
    "functional_coverage": "functional_coverage",
    "uvm": "uvm",
    "rtl_designer": "rtl_designer",
    "debug": "debug",
    "workflows": "workflows",
    # 手册之外的兼容入口（不列入 `tui --mode` 的正式 choices）
    "unit_testing": "unit_testing",
    "agentic_chat": "agentic_chat",
}

#: `cli_config.yaml` 的关键组（2.0 手册 §4）
CONFIG_GROUPS = {
    "tools": (
        "sim_bin_path", "cov_bin_path", "formal_bin_path", "lint_tool_bin_path",
        "verisium_debug_root", "ppa_bin_path", "hls_stratus_root",
    ),
    "flow": (
        "sim_autocorrect_attempts", "formal_autocorrect_attempts",
        "max_syntax_fix_attempts", "max_parallel_workers", "formal_flow_mode",
        "simulation_flow_mode", "functional_coverage_flow_mode",
        "enable_mental_model", "enable_user_checkpoints", "reuse_runid",
    ),
    "llm": ("llm_timeout", "use_litellm_client", "is_azure_model", "reasoning"),
    "context": ("summarization_threshold",),
    "mental_model": (
        "use_mental_model_lite_steps", "use_mental_model_very_lite",
        "force_mental_model_inconsistency_check", "use_rag_for_spec_files",
    ),
}


@dataclass(frozen=True)
class ConfigResolution:
    path: Optional[Path]
    data: Dict[str, Any]
    sources: Sequence[Path]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": str(self.path) if self.path else "",
            "sources": [str(p) for p in self.sources],
            "data": self.data,
        }


def agent_cli_rows() -> List[Dict[str, Any]]:
    """手册 CLI 名 → 当前 agent；同一 CLI 名可能覆盖多个 agent（如 UVM）。"""
    rows: List[Dict[str, Any]] = []
    for spec in all_agents():
        if not spec.cli_name:
            continue
        rows.append({
            "cli": spec.cli_name,
            "agent_id": spec.agent_id,
            "domain": spec.domain,
            "title": spec.title,
            "tui_mode": spec.tui_mode,
            "artifact_dir": spec.artifact_dir,
            "inputs": spec.inputs,
        })
    return rows


# ════════════════════════════════════════════════════════════════
# 配置
# ════════════════════════════════════════════════════════════════

def config_search_paths(explicit: str | Path | None = None,
                        design_root: str | Path | None = None) -> List[Path]:
    """2.0 查找顺序：`--config` → 安装目录 → `$CHIPSTACK_HOME` → 工程根。"""
    paths: List[Path] = []
    if explicit:
        paths.append(Path(explicit).expanduser())
    paths.append(install_root() / CLI_CONFIG_NAME)
    paths.append(default_home() / CLI_CONFIG_NAME)
    if design_root:
        paths.append(Path(design_root).expanduser() / CLI_CONFIG_NAME)
    return paths


def load_effective_config(explicit: str | Path | None = None,
                          design_root: str | Path | None = None) -> ConfigResolution:
    """按查找顺序合并；**先出现的来源优先**，后面的只补缺键。"""
    sources: List[Path] = []
    merged: Dict[str, Any] = {}
    for path in config_search_paths(explicit, design_root):
        if not path.is_file():
            continue
        try:
            import yaml

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, ImportError):
            continue
        if not isinstance(data, dict):
            continue
        sources.append(path)
        for key, value in data.items():
            merged.setdefault(key, value)
    return ConfigResolution(sources[0] if sources else None, merged, sources)


# ════════════════════════════════════════════════════════════════
# Skills
# ════════════════════════════════════════════════════════════════

def _skill_source(root: Path | None = None) -> Path:
    repo = Path(root) if root else install_root()
    for candidate in (repo / "skills", repo / ".claude" / "skills"):
        if candidate.is_dir():
            return candidate
    return repo / ".claude" / "skills"


def _skill_dirs(source: Path) -> List[Path]:
    if not source.is_dir():
        return []
    return [p for p in source.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()]


def seed_skills(home: str | Path | None = None,
                source: str | Path | None = None) -> List[Path]:
    """复制默认 skills 到 `<CHIPSTACK_HOME>/skills`；**已存在的不覆盖**。"""
    target_root = (Path(home).expanduser() if home else default_home()) / "skills"
    target_root.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for skill in _skill_dirs(_skill_source(Path(source) if source else None)):
        target = target_root / skill.name
        if target.exists():
            continue
        shutil.copytree(skill, target)
        written.append(target)
    return written


def install_skills(client: str = "claude-code", *, project: bool = False,
                   source: str | Path | None = None) -> List[Path]:
    """安装 skills 到 coding agent 的技能目录（目前支持 claude-code）。"""
    if client not in ("claude-code", "claude"):
        raise ValueError(f"暂只支持 claude-code；收到 {client!r}")
    base = Path.cwd() / ".claude" / "skills" if project else Path.home() / ".claude" / "skills"
    base.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for skill in _skill_dirs(_skill_source(Path(source) if source else None)):
        target = base / skill.name
        shutil.copytree(skill, target, dirs_exist_ok=True)
        written.append(target)
    return written


# ════════════════════════════════════════════════════════════════
# 单文件离线产物浏览器（Web UI / Standalone Artifacts Browser 的静态版）
# ════════════════════════════════════════════════════════════════

_MAX_ARTIFACT_BYTES = 2_000_000
_ARTIFACT_SUFFIXES = {".md", ".json", ".yaml", ".yml"}


def collect_artifacts(run_dir: str | Path) -> List[Dict[str, Any]]:
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"不是运行目录：{root}")
    rows: List[Dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in _ARTIFACT_SUFFIXES:
            continue
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        try:
            if path.stat().st_size > _MAX_ARTIFACT_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rows.append({
            "path": path.relative_to(root).as_posix(),
            "suffix": path.suffix.lower(),
            "text": text,
        })
    return rows


_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>SignOffAI / ChipStack artifacts — {run_name}</title>
<style>
 body{{margin:0;font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#1e1f22;color:#e6e6e6}}
 header{{padding:10px 16px;background:#2b2d31;border-bottom:1px solid #3a3d43}}
 #wrap{{display:flex;height:calc(100vh - 52px)}}
 #side{{width:320px;overflow:auto;border-right:1px solid #3a3d43;background:#232428;padding:8px}}
 .item{{padding:6px 8px;border-radius:4px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
 .item:hover{{background:#2f3136}} .item.active{{background:#3b3d44}}
 #main{{flex:1;display:flex;flex-direction:column;padding:10px;gap:8px;min-width:0}}
 #head{{display:flex;gap:8px;align-items:center}} #path{{flex:1;color:#9aa0a6;font-family:ui-monospace,monospace}}
 textarea{{flex:1;width:100%;box-sizing:border-box;background:#1b1c1f;color:#e6e6e6;border:1px solid #3a3d43;border-radius:4px;padding:10px;font:13px/1.55 ui-monospace,Consolas,monospace;resize:none}}
 #preview{{flex:1;overflow:auto;background:#1b1c1f;border:1px solid #3a3d43;border-radius:4px;padding:12px;display:none}}
 #preview h1,#preview h2,#preview h3{{color:#fff}} #preview code{{background:#2b2d31;padding:1px 4px;border-radius:3px}}
 #preview pre{{background:#2b2d31;padding:10px;border-radius:4px;overflow:auto}}
 button{{background:#3b6ea5;color:#fff;border:0;border-radius:4px;padding:6px 12px;cursor:pointer}}
 button.secondary{{background:#3a3d43}} .muted{{color:#9aa0a6}}
</style></head><body>
<header><b>SignOffAI / ChipStack artifacts</b> — {run_name}
 <span class="muted">　单文件离线浏览器（编辑后点“下载副本”；不写回服务器）</span></header>
<div id="wrap">
 <div id="side"></div>
 <div id="main">
  <div id="head"><span id="path" class="muted">选择左侧产物</span>
   <button class="secondary" id="toggle">预览</button>
   <button id="download">下载副本</button></div>
  <textarea id="editor" spellcheck="false" placeholder="选择左侧产物"></textarea>
  <div id="preview"></div>
 </div>
</div>
<script>
const DATA = {data};
let current = null;
const side = document.getElementById('side'), editor = document.getElementById('editor');
const preview = document.getElementById('preview'), pathEl = document.getElementById('path');
function renderMd(text){{
  let out = text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  out = out.replace(/^```([\\s\\S]*?)```/gm, (_,code)=>'<pre>'+code+'</pre>');
  out = out.replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>');
  out = out.replace(/\\*\\*(.+?)\\*\\*/g,'<b>$1</b>').replace(/`([^`]+)`/g,'<code>$1</code>');
  out = out.replace(/^[-*] (.*)$/gm,'<li>$1</li>').replace(/(<li>[\\s\\S]*?<\\/li>)/g,'<ul>$1</ul>');
  return out.replace(/\\n/g,'<br>');
}}
function show(row, el){{
  current = row; [...side.children].forEach(x=>x.classList.remove('active')); el.classList.add('active');
  pathEl.textContent = row.path; editor.value = row.text;
  preview.innerHTML = renderMd(row.text);
}}
DATA.forEach((row, i)=>{{
  const el = document.createElement('div'); el.className='item'; el.textContent=row.path;
  el.onclick = ()=>show(row, el); side.appendChild(el);
}});
document.getElementById('toggle').onclick = ()=>{{
  const p = preview.style.display === 'block'; preview.style.display = p?'none':'block';
  editor.style.display = p?'block':'none';
}};
document.getElementById('download').onclick = ()=>{{
  if(!current) return; const blob = new Blob([editor.value], {{type:'text/plain;charset=utf-8'}});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = current.path.split('/').pop(); a.click(); URL.revokeObjectURL(a.href);
}};
if (DATA.length) show(DATA[0], side.firstChild);
</script></body></html>
"""


def build_artifact_review_html(run_dir: str | Path, out: str | Path) -> Path:
    """把一次运行的 `.md/.json/.yaml` 打成单文件 HTML（离线可编辑/下载）。"""
    rows = collect_artifacts(run_dir)
    payload = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    text = _HTML.format(run_name=html.escape(Path(run_dir).name), data=payload)
    target = Path(out).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


__all__ = [
    "GUIDE_TUI_MODES",
    "TUI_MODES",
    "RESERVED_ARTIFACT_NAMES",
    "CONFIG_GROUPS",
    "ConfigResolution",
    "agent_cli_rows",
    "config_search_paths",
    "load_effective_config",
    "seed_skills",
    "install_skills",
    "collect_artifacts",
    "build_artifact_review_html",
]
