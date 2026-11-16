"""
共享的输出目录命名规则 —— 所有模块统一导入此处。

两条路径：

* **ChipStack 工程目录（默认）**：当前目录有 `cli_config.yaml` 时，默认输出
  根落到 `<DESIGN_ROOT>/chipstack_artifacts/<top>-<run_id>/`，并写 run
  manifest；不再生成游离的 `output_<user>_<ts>` 目录。
* **旧前缀式**（无 `cli_config.yaml` 或显式给了非默认 base）：
  `{prefix}_{user}_{YYYYMMDD_HHMMSS}`。

两种形态都保证幂等：已含时间戳后缀的路径原样返回。
"""
from __future__ import annotations

import getpass
import os
import re
from datetime import datetime
from pathlib import Path

# 旧格式：..._用户名_YYYYMMDD_HHMMSS
#
# 末尾那个可选 `_\d+` 是给"同一秒内的第二次运行"留的：时间戳只到秒，
# 串行启动两次很容易落在同一秒，`RunService` 于是给第二次加一个 `_2` 后缀。
# 不加这一项的话，`_2` 会让正则匹配不上，后续任何一次 `make_output_root`
# 都会**再追加一个时间戳**，目录名变成
# `output_x_20261002_120000_2_x_20261002_120000` —— 幂等承诺在改名的那一刻失效。
_TIMESTAMPED = re.compile(r"_[a-z]+\d*_\d{8}_\d{6}(_\d+)?$")

# ChipStack RUN_ID 格式：`<top>-YYYY_MM_DD_HH_MM_SS` 或 `..._YYYY_MM_DD_HH_MM_SS`
# （可带 `_2` 冲突后缀）
_LAYOUT_TIMESTAMPED = re.compile(r"[-_]\d{4}(?:_\d{2}){5}(?:_\d+)?$")

#: 默认 base 的名字 —— 只有它会被重定向到 L4 产物根
_DEFAULT_BASE = "output"


def _layout_enabled() -> bool:
    return os.environ.get("SIGNOFFAI_LAYOUT", "").strip().lower() not in (
        "0", "false", "no", "off")


def _layout_output_root() -> str | None:
    """有 cli_config.yaml 时走 ChipStack 目录；否则返回 None（旧行为）。"""
    if not _layout_enabled():
        return None
    cwd = Path.cwd()
    if not (cwd / "cli_config.yaml").is_file():
        return None
    try:
        from src.runtime_plane.core.project_layout import ProjectLayout
    except Exception:                                  # noqa: BLE001 目录契约不可用时退回旧行为
        return None
    layout = ProjectLayout.discover(cwd)
    top = layout.top_module or layout.name
    run_id = os.environ.get("SIGNOFFAI_RUN_ID", "").strip() or None
    run = layout.create_run(top, run_id=run_id, entrypoint="pipeline")
    return str(run.root)


def make_output_root(base: str | None = None) -> str:
    """生成一次运行目录（幂等）。

    Args:
        base: 目录前缀。None / "output" 且当前目录是 ChipStack 工程 → L4 产物根
            下的 `<top>-<run_id>/`；其它值保持旧前缀式命名。
            已含时间戳（两种格式）→ 直接返回。

    Returns:
        输出目录路径。
    """
    prefix = base if base else _DEFAULT_BASE
    # 显式 `-o`：VPlan execute 要的是**精确运行目录**（`<run>/inputs/vplan/`），
    # 不能再被各 executor 追加时间戳另起一个目录。
    if os.environ.get("SIGNOFFAI_OUTPUT_EXACT", "").strip().lower() in (
            "1", "true", "yes") and base:
        return str(prefix)
    # 幂等：两种时间戳格式都直接返回，避免层层追加
    if _TIMESTAMPED.search(prefix) or _LAYOUT_TIMESTAMPED.search(prefix):
        return prefix
    if prefix == _DEFAULT_BASE:
        layout_root = _layout_output_root()
        if layout_root:
            return layout_root
    user = getpass.getuser()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{user}_{ts}"
