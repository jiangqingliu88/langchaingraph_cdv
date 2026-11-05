"""项目登记表 —— 「切到哪个芯片项目 / 哪套验证环境」。

## 为什么"项目"就是**一个工作目录**

隔离本身**已经是现成的**，不用新造一套机制：运行产物（`output/`）和记忆
（`database/*.db`：经验库、豁免登记册、IP 库、用例库、RL 策略）全是**相对
进程工作目录**的路径。所以换一个目录跑，产物与记忆天然互不可见 —— 这就是
「项目隔离」，也正是路线图里 Phase 3 那条。

这套代码**不打算**把它变成"多用户平台"：登记表就一个 YAML，记事本改得动。

## 切项目为什么要重启

不热切换不是偷懒：`Settings` / `RunService` / 各 L4 记忆库的**单例句柄**都在
启动时绑定了当时的 cwd，还有 agent 实例与 sqlite 连接挂着。热切等于把这些
全部重建一遍 —— 那是另一件工程，且容易切一半留下旧连接。所以这里的做法是
**用目标目录重新起一个进程、自己退出**（`relaunch_command`），干净且可解释。

## 登记表放哪

`~/.signoffai/projects.yaml` —— **用户级**，不是仓库级：项目本来就在别的目录
里，登记表跟仓库走的话，换台机器克隆一份仓库就不知道有哪些项目了。

    projects:
      - {id: apb_uart, name: APB-UART 验证, root: D:/work/apb_uart}
      - {id: m100,     name: M100 微码,     root: D:/work/m100, manifest: config/workbench.yaml}
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

#: 登记表的默认位置（用户级）
REGISTRY_ENV = "SIGNOFFAI_PROJECTS"
REGISTRY_NAME = "projects.yaml"


def registry_path() -> Path:
    """登记表路径：环境变量优先（测试与多套登记表用），否则 `~/.signoffai/`。"""
    import os

    override = os.environ.get(REGISTRY_ENV, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".signoffai" / REGISTRY_NAME


@dataclass(frozen=True)
class Project:
    """一个项目 = 一个工作目录（+ 可选的一份界面清单）。"""
    id: str
    name: str
    root: str
    manifest: str = ""          # 相对 root；空 = 用默认 config/workbench.yaml
    description: str = ""

    @property
    def path(self) -> Path:
        return Path(self.root)

    @property
    def manifest_path(self) -> Optional[Path]:
        """清单的绝对路径（**不存在就返回 None**，不返回一个打不开的路径）。"""
        if not self.manifest:
            default = self.path / "config" / "workbench.yaml"
            return default if default.exists() else None
        p = Path(self.manifest)
        if not p.is_absolute():
            p = self.path / self.manifest
        return p if p.exists() else None

    @property
    def exists(self) -> bool:
        return self.path.is_dir()

    def to_dict(self) -> Dict[str, str]:
        return {"id": self.id, "name": self.name, "root": self.root,
                "manifest": self.manifest, "description": self.description}


def load_projects(path: Optional[Path] = None) -> List[Project]:
    """读登记表。**读不到/坏了一律返回空表**，不抛 —— 界面起步不该被它挡住。

    条目缺 `id` 或 `root` 的跳过（写错一行不该让整张表失效）。
    """
    p = Path(path) if path else registry_path()
    if not p.exists():
        return []
    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception:                                  # noqa: BLE001
        return []
    out: List[Project] = []
    for item in (data.get("projects") or []):
        if not isinstance(item, dict):
            continue
        pid, root = str(item.get("id", "")).strip(), str(item.get("root", "")).strip()
        if not pid or not root:
            continue
        out.append(Project(id=pid, name=str(item.get("name") or pid), root=root,
                           manifest=str(item.get("manifest") or ""),
                           description=str(item.get("description") or "")))
    return out


def find(project_id: str, projects: Optional[List[Project]] = None) -> Optional[Project]:
    for project in (projects if projects is not None else load_projects()):
        if project.id == project_id:
            return project
    return None


def current(cwd: Optional[Path] = None) -> Optional[Project]:
    """当前进程跑在哪个项目里 —— 按工作目录匹配登记表。

    匹配不上返回 None（**没登记**不等于"没项目"：很多人就在仓库目录里跑）。
    """
    here = Path(cwd or Path.cwd()).resolve()
    for project in load_projects():
        try:
            if project.path.resolve() == here:
                return project
        except OSError:
            continue
    return None


def relaunch_command(project: Project) -> List[str]:
    """切到这个项目要跑的命令 —— 用目标目录当 cwd 重新起一个进程。

    `-m src.workbench` 而不是 `vagent`：这里的入口是**界面**；带清单时把清单
    路径显式传过去（登记表里写的那份）。
    """
    argv = [sys.executable, "-m", "src.workbench"]
    manifest = project.manifest_path
    if manifest is not None:
        argv.append(str(manifest))
    return argv


# ════════════════════════════════════════════════════════════════
# 登记（就地加一个项目，不用手改 YAML）
# ════════════════════════════════════════════════════════════════

def register(name: str, root: str, manifest: str = "",
             project_id: str = "", path: Optional[Path] = None) -> Project:
    """把一个目录登记成项目（同 id 覆盖）。**目录/文件不存在就建**。

    为什么要这个入口：登记表是用户级文件（`~/.signoffai/projects.yaml`），
    第一次用的人根本不知道它在哪 —— 界面上点一下就登记上，比让人去改 YAML 现实。
    """
    import yaml

    p = Path(path) if path else registry_path()
    pid = project_id or Path(root).name.lower().replace("-", "_") or "project"
    project = Project(id=pid, name=name or pid, root=str(Path(root).resolve()),
                      manifest=manifest)
    data = {"projects": []}
    if p.exists():
        try:
            loaded = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            if isinstance(loaded.get("projects"), list):
                data = loaded
        except Exception:                                  # noqa: BLE001 坏了就重写
            data = {"projects": []}
    kept = [x for x in data["projects"]
            if not (isinstance(x, dict) and str(x.get("id")) == pid)]
    kept.append(project.to_dict())
    data["projects"] = kept
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return project
