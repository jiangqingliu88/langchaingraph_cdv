"""ChipStack 工程目录架构 —— SignOffAI 的唯一目录契约。

这份模块把 `CS-DIR-REQ-001` 的五层模型（L0 安装 / L1 用户配置 / L2 工程输入 /
L3 工程配置 / L4 产物 / L5 工作流）落成**一层可执行代码**：

    DESIGN_ROOT/                          L2 工程输入（spec/ rtl/ tb/ ecn/ ref/ ...）
    ├── cli_config.yaml                   L3 工程配置
    ├── workflows/<flow>/                 L5 工作流作者目录
    └── chipstack_artifacts/             L4 产物根（可整目录删除后重跑）
        ├── run_manifest.json            运行索引（最新 run + 历史）
        ├── artifacts.sqlite             跨 agent 查询索引
        ├── compile_config.yaml          编译配置（R-014/R-015）
        ├── cli_logs/cli_YYYYMMDD-HHMMSS.log  每次 CLI 调用一份（R-022）
        ├── Archive/<design>.<agent>.<timestamp>/  归档（R-026）
        ├── <top>/                         streamlined 按设计聚合
        └── <top>-<run_id>/                run 级 agent 目录（R-019/R-020）

约束（不要绕过这里去拼路径）：

* agent 子目录名来自 `AGENT_ARTIFACT_DIRS`，与 `agent_plane.domains` 一一对应；
* 所有 manifest / 日志 / 备份 / 归档都走本模块的原子写入；
* 本模块只依赖标准库，属于 Runtime Plane 的最底层，不 import 任何上层平面。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Optional, Sequence

# ════════════════════════════════════════════════════════════════
# 常量：命名与固定目录
# ════════════════════════════════════════════════════════════════

SCHEMA = "signoffai_project_layout_v1"
RUN_MANIFEST_SCHEMA = "run_manifest_v1"
INDEX_SCHEMA = "run_manifest_index_v1"

ARTIFACT_DIRNAME = "chipstack_artifacts"
HOME_ENV = ("SIGNOFFAI_HOME", "CHIPSTACK_HOME")
ARTIFACT_ENV = ("SIGNOFFAI_ARTIFACT_ROOT", "CHIPSTACK_ARTIFACT_ROOT")

CLI_CONFIG_NAME = "cli_config.yaml"
COMPILE_CONFIG_NAME = "compile_config.yaml"
MANIFEST_NAME = "run_manifest.json"
SQLITE_NAME = "artifacts.sqlite"
CLI_LOGS_DIR = "cli_logs"
ARCHIVE_DIR = "Archive"
RESULTS_DIR = "run_results"
WORKFLOWS_DIR = "workflows"

INPUT_DIRS = ("spec", "rtl", "tb", "ecn", "ref", "scripts", "docs")

#: L1 技能池 target 目录（R-038）；用户技能按 target 分目录
SKILL_TARGETS = (
    "formal",
    "simulation",
    "coverage",
    "uvm",
    "lint",
    "rtl_generation",
    "mental_model",
    "dv_debug",
)

#: R-020 规定的 agent 固定子目录（也是验收清单的对照表）
ARTIFACT_DIRS_SPEC = (
    "formal_agent",
    "simulation_agent",
    "functional_coverage_agent",
    "uvm_agent",
    "lint_autofix",
    "mental_model_agent",
    "dv_debug",
    "rtl_generation",
    "rtl_early_estimation_agent",
)

#: 手册 §5：产物根下这些名字是保留目录，**不能当 design root**
RESERVED_ARTIFACT_NAMES = (
    "Archive",
    "tui_sessions",
    "app_state",
    "cli_logs",
    "symphony_logs",
    "tui",
    "tmp",
    "compile_fix",
    "semantic_cache",
)

#: 手册 §5：UVM 产物在 artifact root 下（不与 design root 混放）
ROOT_LEVEL_ARTIFACT_DIRS = ("uvm_agent",)

#: agent id（代码里的角色名） → 产物子目录。
#: 与 `src/agent_plane/domains.py` 的五个 Agent Domain 一一对应；
#: 新 agent 必须在这里登记，否则它只能拿到自己的同名目录。
AGENT_ARTIFACT_DIRS: Dict[str, str] = {
    "mental_model_agent": "mental_model_agent",
    "simulation_agent": "simulation_agent",
    "test_plan_agent": "test_plan_agent",
    "formal_agent": "formal_agent",
    "functional_coverage_agent": "functional_coverage_agent",
    "uvm_coding_agent": "uvm_agent",
    "uvm_coverage": "uvm_coverage",
    "dv_debug_agent": "dv_debug",
    "lint_autofix": "lint_autofix",
    "rtl_early_estimation_agent": "rtl_early_estimation_agent",
    "rtl_upgrade_agent": "rtl_generation",
    # 兼容旧调用名
    "uvm_agent": "uvm_agent",
    "dv_debug": "dv_debug",
    "rtl_generation": "rtl_generation",
}

#: 五个 Agent Domain 的代表性产物目录（GUI 分组与文档用；权威定义在
#: `agent_plane/domains.py`，这里只放字符串，避免 Runtime → Agent 的反向依赖）。
DOMAIN_ARTIFACT_HINTS: Dict[str, tuple] = {
    "design_understanding": ("mental_model_agent",),
    "design_verification": ("simulation_agent",),
    "verification": (
        "test_plan_agent",
        "formal_agent",
        "functional_coverage_agent",
        "uvm_agent",
        "dv_debug",
    ),
    "design_signoff": ("lint_autofix",),
    "design_generation": ("rtl_generation", "rtl_early_estimation_agent"),
}

DEFAULT_COMPILE_CONFIG: Dict[str, Any] = {
    "sv_version": "SV2009",
    "default_library_path": "",
    "errors_to_ignore_csv": "",
    "warnings_to_errors_csv": "",
    "errors_to_warning_csv": "",
    "modules_to_blackbox_csv": "",
    "custom_sv_extensions_csv": "",
    "parameter_overrides": {},
    "uvm_path": "",
}

#: 产物根/临时目录在 .gitignore 里的必备片段
GITIGNORE_ENTRIES = (
    ".env",
    "__pycache__/",
    "*.pyc",
    "*.db",
    "logs/",
    ".pytest_cache/",
    ".ruff_cache/",
)

_TIMESTAMPED = re.compile(r"^\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}$")
_CLI_LOG_STAMP = re.compile(r"^cli_\d{8}-\d{6}(_\d+)?$")
_ARCHIVE_NAME = re.compile(r"^[A-Za-z0-9_.-]+\.[A-Za-z0-9_.-]+\.\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}$")
_SECRET_LINE = re.compile(
    r"(?im)^\s*(?:[A-Za-z_][A-Za-z0-9_]*_)?(?:token|api[_-]?key|password|secret|jwt)\s*:\s*(?!['\"]?\s*$)(\S+)"
)


# ════════════════════════════════════════════════════════════════
# 小工具
# ════════════════════════════════════════════════════════════════

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_name(value: Any, *, default: str = "design") -> str:
    """把任意名字收敛成可做目录名的安全串（R-007：避免空格/中文目录）。"""
    text = str(value or "").strip()
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text).strip("._-")
    if not text or text in (".", ".."):
        return default
    return text


def run_id_now() -> str:
    """默认 RUN_ID：UTC 时间戳 `YYYY_MM_DD_HH_MM_SS`（与 ChipStack 一致）。"""
    return datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S")


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return default


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


def _write_text(path: Path, text: str, *, overwrite: bool = False) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError, ImportError):
        return {}
    return data if isinstance(data, dict) else {}


def _dump_yaml(value: Mapping[str, Any]) -> str:
    try:
        import yaml

        return yaml.safe_dump(dict(value), allow_unicode=True, sort_keys=False)
    except ImportError:  # PyYAML 是运行依赖；拿不到时退化成 JSON（仍是合法 YAML）
        return json.dumps(dict(value), ensure_ascii=False, indent=2) + "\n"


def _unique_path(path: Path, *, is_dir: bool = True) -> Path:
    """同名冲突时追加 `_2`、`_3` …… 不覆盖已有证据。"""
    if not path.exists():
        return path
    for index in range(2, 10_000):
        candidate = path.with_name(f"{path.name}_{index}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"无法为 {path} 找到唯一名字")


def default_home() -> Path:
    """L1 用户配置根：`$SIGNOFFAI_HOME` / `$CHIPSTACK_HOME` / `~/.signoffai`。"""
    for env in HOME_ENV:
        value = os.environ.get(env, "").strip()
        if value:
            return Path(value).expanduser()
    return Path.home() / ".signoffai"


def install_root() -> Path:
    """L0 安装根（本仓库根目录，只读）。"""
    return Path(__file__).resolve().parents[3]


# ════════════════════════════════════════════════════════════════
# 分层模型
# ════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class Layer:
    id: str
    title: str
    path: Path
    writable: bool
    description: str

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "path": str(self.path),
            "writable": self.writable,
            "exists": self.exists,
            "description": self.description,
        }


# ════════════════════════════════════════════════════════════════
# ProjectLayout —— L2/L3/L4 的根
# ════════════════════════════════════════════════════════════════

@dataclass
class ProjectLayout:
    """一个 DESIGN_ROOT 及其产物根。

    `discover()` 永远成功（目录不存在也不抛）——界面需要能展示「还没初始化的
    工程」，而不是因为目录不存在就白屏。
    """

    design_root: Path
    artifact_root: Path
    config: Dict[str, Any] = field(default_factory=dict)

    # ── 构造 ──

    @classmethod
    def discover(cls, root: str | Path | None = None,
                 artifact_root: str | Path | None = None) -> "ProjectLayout":
        design_root = Path(root or Path.cwd()).expanduser().resolve()
        config = _read_yaml(design_root / CLI_CONFIG_NAME)
        raw = artifact_root or next(
            (os.environ[e] for e in ARTIFACT_ENV if os.environ.get(e, "").strip()), ""
        ) or config.get("artifact_root") or config.get("run_dir") or ARTIFACT_DIRNAME
        artifact = Path(str(raw)).expanduser()
        if not artifact.is_absolute():
            artifact = design_root / artifact
        return cls(design_root=design_root, artifact_root=artifact.resolve(), config=config)

    # ── L2/L3 路径 ──

    @property
    def name(self) -> str:
        return self.design_root.name

    @property
    def top_module(self) -> str:
        value = str(self.config.get("top_module") or self.config.get("top") or "").strip()
        return safe_name(value) if value else ""

    @property
    def cli_config_path(self) -> Path:
        return self.design_root / CLI_CONFIG_NAME

    @property
    def workflows_dir(self) -> Path:
        return self.design_root / WORKFLOWS_DIR

    def input_dir(self, name: str) -> Path:
        return self.design_root / name

    # ── L4 路径 ──

    @property
    def compile_config_path(self) -> Path:
        return self.artifact_root / COMPILE_CONFIG_NAME

    @property
    def manifest_path(self) -> Path:
        return self.artifact_root / MANIFEST_NAME

    @property
    def sqlite_path(self) -> Path:
        return self.artifact_root / SQLITE_NAME

    @property
    def cli_logs_dir(self) -> Path:
        return self.artifact_root / CLI_LOGS_DIR

    @property
    def archive_root(self) -> Path:
        return self.artifact_root / ARCHIVE_DIR

    def design_dir(self, top: str | None = None) -> Path:
        return self.artifact_root / safe_name(top or self.top_module or self.name)

    # ── 分层视图 ──

    def layers(self) -> List[Layer]:
        return [
            Layer("L0", "安装层", install_root(), False,
                  "ChipStack/SignOffAI 安装目录，只读，禁止 agent 写入"),
            Layer("L1", "用户配置层", default_home(), True,
                  "每用户配置根：config.yaml、skills/<target>/"),
            Layer("L2", "工程输入层", self.design_root, True,
                  "版本管理：spec/ rtl/ tb/ ecn/ ref/ scripts/ docs/"),
            Layer("L3", "工程配置层", self.cli_config_path, True,
                  "工程级运行参数：artifact_root、top_module、模板"),
            Layer("L4", "产物层", self.artifact_root, True,
                  "可清理、可归档、按 run 隔离；删除后仅凭 L2/L3 可重跑"),
            Layer("L5", "工作流层", self.workflows_dir, True,
                  "工作流作者目录：<flow>/<flow>.yaml 与函数模块"),
        ]

    # ── 初始化 ──

    def ensure_home(self) -> Path:
        """初始化 L1 用户配置层：`config.yaml` + `skills/<target>/`（R-011/R-038）。"""
        home = default_home()
        (home / "skills").mkdir(parents=True, exist_ok=True)
        for target in SKILL_TARGETS:
            (home / "skills" / target).mkdir(parents=True, exist_ok=True)
        config = home / "config.yaml"
        if not config.exists():
            _write_text(config,
                        "# SignOffAI 用户级配置（L1）—— 不提交密钥，密钥走环境变量\n"
                        "skills_root: skills\n", overwrite=True)
        return home

    def ensure(self, *, create_compile_config: bool = True) -> "ProjectLayout":
        """创建 L4 骨架；不碰 L2 输入（输入归用户/版本库）。"""
        for path in (self.artifact_root, self.cli_logs_dir, self.archive_root,
                     self.artifact_root / "tui" / "sessions"):
            path.mkdir(parents=True, exist_ok=True)
        if create_compile_config and not self.compile_config_path.exists():
            _write_json(self.compile_config_path, DEFAULT_COMPILE_CONFIG)
        if not self.manifest_path.exists():
            _write_json(self.manifest_path, {
                "schema": INDEX_SCHEMA,
                "design_root": str(self.design_root),
                "artifact_root": str(self.artifact_root),
                "created_at": _now(),
                "latest_run_id": "",
                "runs": [],
            })
        self._ensure_sqlite()
        return self

    def scaffold(self, *, name: str = "", top: str = "", template: str = "default",
                 artifact_root: str = "") -> "ProjectLayout":
        """初始化 L2/L3/L4 全套目录（`project init` / GUI「初始化工程目录」）。"""
        design = self.design_root
        design.mkdir(parents=True, exist_ok=True)
        for sub in INPUT_DIRS:
            (design / sub).mkdir(parents=True, exist_ok=True)
        (design / WORKFLOWS_DIR).mkdir(parents=True, exist_ok=True)

        design_name = safe_name(name or design.name)
        top_name = safe_name(top or self.top_module or design_name)

        existing_config = _read_yaml(design / CLI_CONFIG_NAME)
        raw_artifact = (artifact_root
                        or existing_config.get("artifact_root")
                        or str(self.artifact_root))
        artifact = Path(str(raw_artifact)).expanduser()
        if not artifact.is_absolute():
            artifact = design / artifact
        artifact = artifact.resolve()

        config = {
            "schema": SCHEMA,
            "design_name": design_name,
            "top_module": top_name,
            "template": template,
            "artifact_root": os.path.relpath(artifact, design).replace("\\", "/"),
            "run_id_format": "%Y_%m_%d_%H_%M_%S",
            "paths": {
                "spec": "spec",
                "rtl": "rtl",
                "tb": "tb",
                "ecn": "ecn",
                "ref": "ref",
                "scripts": "scripts",
                "docs": "docs",
            },
        }
        if not existing_config:
            _write_text(design / CLI_CONFIG_NAME,
                        "# ChipStack 工程配置（L3）\n" + _dump_yaml(config),
                        overwrite=True)
        else:
            config = {**config, **existing_config}
        _write_text(design / "extra_instructions.md",
                    "# 额外约束\n\n（可选）项目级指令，供所有 agent 注入。\n")
        _write_text(design / "README.md", f"# {design_name}\n\n"
                    f"SignOffAI / ChipStack 工程目录（模板：{template}）。\n\n"
                    "- 输入：`spec/ rtl/ tb/ ecn/ ref/ scripts/ docs/`\n"
                    f"- 配置：`{CLI_CONFIG_NAME}`\n"
                    f"- 产物：`{config['artifact_root']}/`（可整目录删除后重跑）\n")
        _write_text(design / "spec" / f"{design_name}_spec.md",
                    f"# {design_name} Specification\n\n## Features\n- TODO\n\n"
                    "## Interfaces\n- NAME: clk, TYPE: input, WIDTH: 1\n"
                    "- NAME: rst_n, TYPE: input, WIDTH: 1\n")
        _write_text(design / "rtl" / f"{top_name}.sv", _rtl_template(top_name, template))
        _write_text(design / "rtl" / f"{top_name}.f", f"rtl/{top_name}.sv\n")
        _write_text(design / WORKFLOWS_DIR / "README.md",
                    "# 工作流\n\n每个流程一个目录：`<flow>/<flow>.yaml` + `<flow>_functions.py`。\n")

        gitignore = design / ".gitignore"
        existing = _read_text(gitignore)
        entries = list(GITIGNORE_ENTRIES)
        entries.append(config["artifact_root"].rstrip("/") + "/")
        missing = [e for e in entries if e not in existing.splitlines()]
        if missing:
            _write_text(gitignore, (existing + "\n" if existing else "")
                        + "\n".join(missing) + "\n", overwrite=True)

        layout = ProjectLayout(design, artifact, config)
        layout.ensure_home()
        layout.ensure()
        return layout

    # ── run ──

    def create_run(self, top: str | None = None, run_id: str | None = None, *,
                   scope: str = "run", entrypoint: str = "",
                   agents: Sequence[str] = ()) -> "RunLayout":
        """创建一次运行的目录契约。

        * `scope="run"`：`<artifact_root>/<top>-<run_id>/`（并发 run 隔离，R-019/R-049）
        * `scope="streamlined"`：`<artifact_root>/<top>/`（长期聚合，formal 等）
        """
        self.ensure()
        top_name = safe_name(top or self.top_module or self.name)
        if top_name in RESERVED_ARTIFACT_NAMES:
            raise ValueError(f"{top_name!r} 是 ChipStack 产物保留名，不能作为 design root")
        rid = str(run_id or run_id_now()).strip()
        if not _TIMESTAMPED.match(rid) and run_id:
            rid = safe_name(rid)
        if scope in ("streamlined", "design"):
            root = _unique_path(self.artifact_root / top_name)
        else:
            root = _unique_path(self.artifact_root / f"{top_name}-{rid}")
            if root.name != f"{top_name}-{rid}":
                rid = root.name[len(top_name) + 1:]
        run = RunLayout(self, top_name, rid, root, scope)
        run.ensure()
        if entrypoint or agents:
            run.begin(entrypoint=entrypoint, agents=agents)
        return run

    def open_run(self, run_id: str, top: str | None = None,
                 scope: str = "run") -> "RunLayout":
        """定位一个**已有** run —— 不建目录、不做唯一化（只读查看用）。"""
        top_name = safe_name(top or self.top_module or self.name)
        if scope in ("streamlined", "design"):
            root = self.artifact_root / top_name
        else:
            root = self.artifact_root / f"{top_name}-{safe_name(run_id)}"
        return RunLayout(self, top_name, str(run_id), root, scope)

    # ── 查询 ──

    def list_runs(self) -> List[Dict[str, Any]]:
        index = _read_json(self.manifest_path, {}) or {}
        runs = [r for r in index.get("runs") or [] if isinstance(r, dict)]
        if runs:
            return sorted(runs, key=lambda r: str(r.get("started_at") or ""))
        # 索引缺失时按目录补读，保证「只要 run 目录在就看得见」
        found: List[Dict[str, Any]] = []
        if self.artifact_root.is_dir():
            for child in sorted(self.artifact_root.iterdir()):
                manifest = _read_json(child / MANIFEST_NAME, None)
                if isinstance(manifest, dict) and manifest.get("run_id"):
                    found.append(manifest)
        return sorted(found, key=lambda r: str(r.get("started_at") or ""))

    def latest_run(self) -> Optional[Dict[str, Any]]:
        runs = self.list_runs()
        return runs[-1] if runs else None

    def index_run(self, manifest: Mapping[str, Any]) -> None:
        """把一次 run 写进 `run_manifest.json` 索引（原子写入）。"""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        index = _read_json(self.manifest_path, {}) or {}
        runs = [r for r in index.get("runs") or [] if isinstance(r, dict)]
        run_id = str(manifest.get("run_id") or "")
        runs = [r for r in runs if str(r.get("run_id") or "") != run_id]
        runs.append({
            "run_id": run_id,
            "design_name": manifest.get("design_name"),
            "top_module": manifest.get("top_module"),
            "entrypoint": manifest.get("entrypoint"),
            "status": manifest.get("status"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "scope": manifest.get("scope"),
            "run_dir": manifest.get("run_dir"),
            "agents_invoked": manifest.get("agents_invoked") or [],
        })
        _write_json(self.manifest_path, {
            "schema": INDEX_SCHEMA,
            "design_root": str(self.design_root),
            "artifact_root": str(self.artifact_root),
            "updated_at": _now(),
            "latest_run_id": run_id,
            "runs": runs,
        })

    # ── SQLite 索引（R-030） ──

    def _ensure_sqlite(self) -> None:
        try:
            with closing(sqlite3.connect(self.sqlite_path)) as conn, conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS runs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        design_name TEXT NOT NULL,
                        top_module TEXT NOT NULL,
                        entrypoint TEXT,
                        status TEXT,
                        started_at TEXT,
                        finished_at TEXT,
                        run_dir TEXT,
                        recorded_at TEXT NOT NULL,
                        UNIQUE(run_id)
                    );
                    CREATE TABLE IF NOT EXISTS agent_artifacts (
                        run_id TEXT NOT NULL,
                        agent_id TEXT NOT NULL,
                        artifact_dir TEXT NOT NULL,
                        status TEXT,
                        reason TEXT,
                        updated_at TEXT,
                        UNIQUE(run_id, agent_id)
                    );
                """)
        except sqlite3.Error:
            # 索引是便利设施，不是签核证据；写不了不影响目录契约。
            pass

    def index_run_sqlite(self, manifest: Mapping[str, Any]) -> None:
        self._ensure_sqlite()
        try:
            with closing(sqlite3.connect(self.sqlite_path)) as conn, conn:
                conn.execute(
                    "INSERT OR REPLACE INTO runs(run_id, design_name, top_module, entrypoint,"
                    " status, started_at, finished_at, run_dir, recorded_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifest.get("run_id", ""),
                        manifest.get("design_name", ""),
                        manifest.get("top_module", ""),
                        manifest.get("entrypoint", ""),
                        manifest.get("status", ""),
                        manifest.get("started_at", ""),
                        manifest.get("finished_at", ""),
                        manifest.get("run_dir", ""),
                        _now(),
                    ),
                )
                for agent_id, row in (manifest.get("agents") or {}).items():
                    if not isinstance(row, dict):
                        continue
                    conn.execute(
                        "INSERT OR REPLACE INTO agent_artifacts(run_id, agent_id,"
                        " artifact_dir, status, reason, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            manifest.get("run_id", ""), agent_id,
                            row.get("artifact_dir", ""), row.get("status", ""),
                            row.get("reason", ""), row.get("updated_at", ""),
                        ),
                    )
        except sqlite3.Error:
            pass

    # ── 验收清单（§7） ──

    def audit(self) -> List[Dict[str, Any]]:
        checks: List[Dict[str, Any]] = []

        def check(req: str, requirement: str, ok: bool, detail: str,
                  *, warn: bool = False) -> None:
            checks.append({
                "id": req,
                "requirement": requirement,
                "status": "PASS" if ok else ("WARN" if warn else "FAIL"),
                "detail": detail,
            })

        check("R-001", "唯一 DESIGN_ROOT", self.design_root.is_dir(),
              str(self.design_root), warn=True)

        home = default_home()
        skills = home / "skills"
        check("R-011", "用户级配置层", home.is_dir() and skills.is_dir(),
              str(home), warn=True)

        spec_files = list((self.design_root / "spec").glob("**/*")) if (self.design_root / "spec").is_dir() else []
        spec_files = [p for p in spec_files if p.is_file()]
        check("R-005", "提供 spec", bool(spec_files),
              f"{len(spec_files)} 个文件" if spec_files else "spec/ 下没有文件", warn=True)

        filelists = [p for p in (self.design_root / "rtl").glob("**/*.f")] \
            if (self.design_root / "rtl").is_dir() else []
        check("R-004", "提供 filelist (.f)", bool(filelists),
              ", ".join(str(p.relative_to(self.design_root)) for p in filelists[:3])
              if filelists else "rtl/ 下没有 .f（formal/simulation/lint 建议显式提供）", warn=True)

        check("R-003", "顶层 module 名", bool(self.top_module),
              self.top_module or "cli_config.yaml 缺 top_module", warn=True)

        check("R-012", "工程级配置 cli_config.yaml", self.cli_config_path.is_file(),
              str(self.cli_config_path))

        secrets = []
        if self.cli_config_path.is_file():
            for match in _SECRET_LINE.finditer(_read_text(self.cli_config_path)):
                secrets.append(match.group(0).strip().split(":")[0])
        check("R-017", "配置中无明文密钥", not secrets,
              "发现疑似明文键：" + ", ".join(secrets) if secrets else "未发现 token/api_key/password")

        compile_doc = _read_json(self.compile_config_path, {}) or {}
        check("R-014", "compile_config.yaml 字段",
              bool(compile_doc) and bool(compile_doc.get("sv_version")),
              str(self.compile_config_path) if compile_doc else "文件不存在或为空")

        separate = self.artifact_root != self.design_root and \
            not any(self.artifact_root.is_relative_to(self.design_root / d) for d in INPUT_DIRS)
        check("R-018", "产物根独立", separate, str(self.artifact_root))

        check("R-022", "CLI 日志目录", self.cli_logs_dir.is_dir(), str(self.cli_logs_dir))
        check("R-026", "归档目录", self.archive_root.is_dir(), str(self.archive_root))

        runs = self.list_runs()
        check("R-021", "run manifest", bool(runs), f"{len(runs)} 个 run",
              warn=True)

        mapped = {agent_artifact_dir(agent_id) for agent_id in AGENT_ARTIFACT_DIRS}
        missing_dirs = [name for name in ARTIFACT_DIRS_SPEC if name not in mapped]
        check("R-020", "agent 子目录固定名", not missing_dirs,
              ", ".join(missing_dirs) if missing_dirs else ", ".join(ARTIFACT_DIRS_SPEC))

        archived = [p for p in self.archive_root.iterdir()] if self.archive_root.is_dir() else []
        bad_archive = [p.name for p in archived if not _ARCHIVE_NAME.match(p.name)]
        check("R-026", "归档命名 <design>.<agent>.<timestamp>", not bad_archive,
              ", ".join(bad_archive[:3]) if bad_archive else
              (f"{len(archived)} 条" if archived else "暂无归档"), warn=True)

        gitignore = _read_text(self.design_root / ".gitignore")
        ignored = self.artifact_root.name in gitignore
        check("R-028", "产物可删除重建（已忽略）", ignored,
              f"已忽略 {self.artifact_root.name}/" if ignored
              else f".gitignore 未忽略 {self.artifact_root.name}/")

        return checks

    def summary(self) -> Dict[str, Any]:
        layers = [layer.to_dict() for layer in self.layers()]
        runs = self.list_runs()
        checks = self.audit()
        failures = [c for c in checks if c["status"] == "FAIL"]
        warnings = [c for c in checks if c["status"] == "WARN"]
        return {
            "schema": SCHEMA,
            "design_root": str(self.design_root),
            "artifact_root": str(self.artifact_root),
            "top_module": self.top_module,
            "layers": layers,
            "runs": runs,
            "latest_run_id": (runs[-1].get("run_id") if runs else ""),
            "checks": checks,
            "failures": len(failures),
            "warnings": len(warnings),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": SCHEMA,
            "design_root": str(self.design_root),
            "artifact_root": str(self.artifact_root),
            "config": self.config,
        }


# ════════════════════════════════════════════════════════════════
# RunLayout —— 一次 run 的目录契约
# ════════════════════════════════════════════════════════════════

@dataclass
class RunLayout:
    layout: ProjectLayout
    top: str
    run_id: str
    root: Path
    scope: str = "run"
    _manifest: Dict[str, Any] = field(default_factory=dict)

    # ── 路径 ──

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME

    @property
    def results_dir(self) -> Path:
        return self.root / RESULTS_DIR

    @property
    def backup_root(self) -> Path:
        return self.root / "backup"

    @property
    def cli_logs_dir(self) -> Path:
        return self.layout.cli_logs_dir

    @property
    def compile_config_path(self) -> Path:
        if self.scope in ("streamlined", "design"):
            return self.root / COMPILE_CONFIG_NAME
        return self.layout.compile_config_path

    def agent_dir(self, agent_id: str, *, create: bool = False) -> Path:
        name = AGENT_ARTIFACT_DIRS.get(str(agent_id), safe_name(agent_id, default="agent"))
        # 手册 §5：UVM 产物固定在 artifact root 下，不与 design root 混放
        path = (self.layout.artifact_root / name
                if name in ROOT_LEVEL_ARTIFACT_DIRS else self.root / name)
        if create:
            (path / "logs").mkdir(parents=True, exist_ok=True)
        return path

    def agent_dirs(self) -> Dict[str, Path]:
        rows: Dict[str, Path] = {}
        for agent_id in AGENT_ARTIFACT_DIRS:
            path = self.agent_dir(agent_id)
            if path.exists():
                rows[agent_id] = path
        known = {path.name for path in rows.values()}
        for name in ROOT_LEVEL_ARTIFACT_DIRS:
            path = self.layout.artifact_root / name
            if path.is_dir():
                rows.setdefault(name, path)
        if self.root.is_dir():
            for child in sorted(self.root.iterdir()):
                if child.is_dir() and child.name not in (
                        RESULTS_DIR, "backup", "logs", CLI_LOGS_DIR) \
                        and child.name not in known \
                        and child.name in ARTIFACT_DIRS_SPEC:
                    rows.setdefault(child.name, child)
        return rows

    # ── 初始化 ──

    def ensure(self) -> "RunLayout":
        for path in (self.root, self.results_dir, self.backup_root,
                     self.root / "logs", self.cli_logs_dir):
            path.mkdir(parents=True, exist_ok=True)
        if not self.compile_config_path.exists():
            _write_json(self.compile_config_path, DEFAULT_COMPILE_CONFIG)
        if not self.manifest_path.exists():
            self._manifest = self._base_manifest(status="CREATED")
            _write_json(self.manifest_path, self._manifest)
        else:
            self._manifest = _read_json(self.manifest_path, {}) or {}
        return self

    def _base_manifest(self, *, status: str) -> Dict[str, Any]:
        now = _now()
        return {
            "schema": RUN_MANIFEST_SCHEMA,
            "run_id": self.run_id,
            "started_at": now,
            "updated_at": now,
            "entrypoint": "",
            "design_name": self.layout.name,
            "top_module": self.top,
            "agents_invoked": [],
            "agents": {},
            "status": status,
            "scope": self.scope,
            "run_dir": str(self.root),
            "design_root": str(self.layout.design_root),
            "artifact_root": str(self.layout.artifact_root),
            "cli_logs": [],
        }

    # ── manifest ──

    def manifest(self) -> Dict[str, Any]:
        if not self._manifest:
            self._manifest = _read_json(self.manifest_path, {}) or {}
        return dict(self._manifest)

    def _save(self, doc: Mapping[str, Any]) -> None:
        doc = dict(doc)
        doc["updated_at"] = _now()
        _write_json(self.manifest_path, doc)
        self._manifest = doc
        self.layout.index_run(doc)
        self.layout.index_run_sqlite(doc)

    def begin(self, *, entrypoint: str = "", agents: Sequence[str] = ()) -> "RunLayout":
        doc = self.manifest() or self._base_manifest(status="RUNNING")
        doc["entrypoint"] = entrypoint or doc.get("entrypoint") or ""
        doc["started_at"] = doc.get("started_at") or _now()
        doc["status"] = "RUNNING"
        invoked = [str(a) for a in agents if str(a).strip()]
        doc["agents_invoked"] = sorted(set(list(doc.get("agents_invoked") or []) + invoked))
        self._save(doc)
        return self

    def finish(self, status: str = "FINISHED", **extra: Any) -> "RunLayout":
        doc = self.manifest()
        doc["status"] = status
        doc["finished_at"] = _now()
        doc.update({k: v for k, v in extra.items() if v is not None})
        self._save(doc)
        return self

    # ── agent 状态 ──

    def record_agent(self, agent_id: str, status: str, reason: str = "",
                     **details: Any) -> Path:
        directory = self.agent_dir(agent_id, create=True)
        row = {
            "agent_id": agent_id,
            "artifact_dir": str(directory),
            "status": status,
            "reason": reason,
            "updated_at": _now(),
            **details,
        }
        _write_json(directory / "status.json", row)
        doc = self.manifest()
        agents = dict(doc.get("agents") or {})
        agents[agent_id] = row
        doc["agents"] = agents
        doc["agents_invoked"] = sorted(set(list(doc.get("agents_invoked") or []) + [agent_id]))
        self._save(doc)
        return directory

    def agent_scope(self, agent_id: str):
        """`with run.agent_scope("formal_agent") as dir:` —— 自动写 RUNNING/FAILED。"""
        return _AgentScope(self, agent_id)

    # ── 日志 ──

    def log_cli(self, command: str | Sequence[str], *, note: str = "",
                extra: Mapping[str, Any] | None = None) -> Path:
        """每次 CLI 调用一份日志（R-022）。同秒冲突加 `_2`，不覆盖。"""
        self.cli_logs_dir.mkdir(parents=True, exist_ok=True)
        base = datetime.now().strftime("cli_%Y%m%d-%H%M%S")
        path = _unique_path(self.cli_logs_dir / f"{base}.log", is_dir=False)
        lines = [
            "# SignOffAI CLI log",
            f"captured_at: {_now()}",
            f"command: {' '.join(command) if isinstance(command, (list, tuple)) else command}",
            f"cwd: {Path.cwd()}",
            f"design_root: {self.layout.design_root}",
            f"artifact_root: {self.layout.artifact_root}",
            f"run_id: {self.run_id}",
        ]
        if note:
            lines.append(f"note: {note}")
        for key, value in (extra or {}).items():
            lines.append(f"{key}: {value}")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        doc = self.manifest()
        logs = list(doc.get("cli_logs") or [])
        logs.append(str(path))
        doc["cli_logs"] = logs
        self._save(doc)
        return path

    # ── 备份 / 归档 ──

    def backup(self, paths: Iterable[str | Path], *, reason: str = "") -> Optional[Path]:
        """修改 RTL 等输入前备份原件（R-025）。返回本次备份目录。"""
        files: List[Path] = []
        for raw in paths:
            path = Path(raw)
            if not path.is_absolute():
                path = self.layout.design_root / path
            if path.exists():
                files.append(path)
        if not files:
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S")
        target = _unique_path(self.backup_root / stamp)
        target.mkdir(parents=True, exist_ok=True)
        records = []
        for source in files:
            try:
                relative = source.relative_to(self.layout.design_root)
            except ValueError:
                relative = Path(source.name)
            dest = target / relative
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, dest, dirs_exist_ok=True)
            else:
                shutil.copy2(source, dest)
            records.append({"source": str(source), "copy": str(dest)})
        _write_json(target / "backup_manifest.json", {
            "schema": "backup_manifest_v1",
            "created_at": _now(),
            "reason": reason,
            "files": records,
        })
        return target

    def archive_agent(self, agent_id: str, *, timestamp: str | None = None) -> Optional[Path]:
        """把某个 agent 目录归档为 `<design>.<agent>.<timestamp>`（R-026）。"""
        source = self.agent_dir(agent_id)
        if not source.is_dir():
            return None
        stamp = timestamp or datetime.now(timezone.utc).strftime("%Y_%m_%d_%H_%M_%S")
        name = f"{safe_name(self.layout.name)}.{safe_name(agent_id, default='agent')}.{stamp}"
        target = _unique_path(self.layout.archive_root / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        return target

    # ── 摘要 ──

    def summary_md(self) -> str:
        doc = self.manifest()
        lines = [
            f"# Run {self.run_id}",
            "",
            f"- design: `{doc.get('design_name')}`",
            f"- top: `{doc.get('top_module')}`",
            f"- status: `{doc.get('status')}`",
            f"- entrypoint: `{doc.get('entrypoint')}`",
            f"- started: `{doc.get('started_at')}`",
            f"- finished: `{doc.get('finished_at') or '-'}`",
            f"- run_dir: `{self.root}`",
            "",
            "## Agents",
        ]
        for agent_id, row in (doc.get("agents") or {}).items():
            lines.append(f"- `{agent_id}`: {row.get('status')}"
                         + (f" — {row.get('reason')}" if row.get("reason") else ""))
        if not doc.get("agents"):
            lines.append("- 尚未登记 agent 产物")
        return "\n".join(lines) + "\n"

    def write_summary(self) -> Path:
        path = self.results_dir / "summary.md"
        _write_text(path, self.summary_md(), overwrite=True)
        return path

    def to_dict(self) -> Dict[str, Any]:
        return {
            **self.manifest(),
            "run_root": str(self.root),
            "agent_dirs": {k: str(v) for k, v in self.agent_dirs().items()},
        }


class _AgentScope:
    """`RunLayout.agent_scope()` 的上下文管理器。"""

    def __init__(self, run: RunLayout, agent_id: str) -> None:
        self.run = run
        self.agent_id = agent_id
        self.path: Optional[Path] = None

    def __enter__(self) -> Path:
        self.path = self.run.record_agent(self.agent_id, "RUNNING", "agent 正在执行")
        return self.path

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.run.record_agent(self.agent_id, "FINISHED", "agent 正常结束")
        else:
            self.run.record_agent(
                self.agent_id, "FAILED",
                f"{exc_type.__name__}: {exc}" if exc else "agent 失败")
        return False


@contextmanager
def run_session(layout: ProjectLayout, top: str | None = None, *,
                entrypoint: str = "", agents: Sequence[str] = (),
                run_id: str | None = None, scope: str = "run") -> Iterator[RunLayout]:
    """`with run_session(layout, top, entrypoint="...") as run:`。

    进入时建目录 + 写 RUNNING manifest，正常结束写 FINISHED，异常写 FAILED
    并继续抛出 —— 失败 run 的 stdout/stderr/原始日志必须留下（R-012）。
    """
    run = layout.create_run(top, run_id=run_id, scope=scope,
                            entrypoint=entrypoint, agents=agents)
    run.begin(entrypoint=entrypoint, agents=agents)
    try:
        yield run
    except BaseException as exc:  # noqa: BLE001 —— 必须记录后原样抛出
        run.finish("FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    else:
        run.finish("FINISHED")


# ════════════════════════════════════════════════════════════════
# 模板
# ════════════════════════════════════════════════════════════════

def _rtl_template(top: str, template: str) -> str:
    if template == "uart":
        return f"""// {top} — UART (project template)
module {top} (
    input  logic clk,
    input  logic rst_n,
    input  logic rx,
    output logic tx
);
    // TODO: implement UART
endmodule
"""
    if template == "alu":
        return f"""// {top} — ALU (project template)
module {top} (
    input  logic        clk,
    input  logic        rst_n,
    input  logic [7:0]  a,
    input  logic [7:0]  b,
    output logic [15:0] y
);
    always_comb y = a + b;
endmodule
"""
    return f"""// {top} — project top (generated by SignOffAI / ChipStack layout)
module {top} (
    input  logic clk,
    input  logic rst_n
);
    // TODO: implement design
endmodule
"""


def agent_artifact_dir(agent_id: str) -> str:
    """agent id → 固定产物子目录名（R-020）。"""
    return AGENT_ARTIFACT_DIRS.get(str(agent_id), safe_name(agent_id, default="agent"))


__all__ = [
    "ARTIFACT_DIRNAME",
    "ARTIFACT_DIRS_SPEC",
    "AGENT_ARTIFACT_DIRS",
    "RESERVED_ARTIFACT_NAMES",
    "ROOT_LEVEL_ARTIFACT_DIRS",
    "DOMAIN_ARTIFACT_HINTS",
    "DEFAULT_COMPILE_CONFIG",
    "INPUT_DIRS",
    "SKILL_TARGETS",
    "Layer",
    "ProjectLayout",
    "RunLayout",
    "agent_artifact_dir",
    "default_home",
    "install_root",
    "run_id_now",
    "run_session",
    "safe_name",
]
