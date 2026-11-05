"""清单文件与业务输入路径的解析。

约定：
  · 默认清单 = `<仓库根>/config/workbench.yaml`（与 `config/agent_config.yaml`
    同级，`pyproject.toml` 的 `include = ["config*"]` 已经把它打进包里）
  · 可被命令行第一个位置参数覆盖，也可被环境变量 `WORKBENCH_MANIFEST` 覆盖
  · 清单里 `ModuleSpec.input` 的**相对路径按清单所在目录解析** —— 这样把
    `config/` 整个搬到别处，清单里的相对引用不会断
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Union

ENV_VAR = "WORKBENCH_MANIFEST"
DEFAULT_RELATIVE = Path("config") / "workbench.yaml"


def repo_root() -> Path:
    """仓库根 —— `src/workbench/config.py` 往上三级。"""
    return Path(__file__).resolve().parents[2]


def default_manifest_path() -> Path:
    """默认清单路径。环境变量优先，最后回落到仓库根。"""
    override = os.environ.get(ENV_VAR, "").strip()
    if override:
        return Path(override).expanduser()
    return repo_root() / DEFAULT_RELATIVE


def resolve_manifest_path(given: Optional[Union[str, Path]] = None) -> Path:
    """命令行没给就取默认 —— 单一入口，免得两处各写一遍回落逻辑。"""
    if given is None or str(given).strip() == "":
        return default_manifest_path()
    return Path(given).expanduser()


def resolve_input(manifest_path: Path, spec_input: str) -> Optional[Path]:
    """把一个 `ModuleSpec.input` 解析成绝对路径。

    绝对路径原样返回；相对路径按**清单所在目录**拼。空字符串 → None
    （表示「这个模块启动时不加载输入」，不是错误）。
    """
    text = (spec_input or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return candidate
    return (Path(manifest_path).resolve().parent / candidate).resolve()
