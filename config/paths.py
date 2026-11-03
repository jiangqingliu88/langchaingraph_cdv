"""项目级路径 —— **数据库位置只有一个真相源**。

历史上有两份库散落在仓库根：

    ic_verification.db       主库（SQLAlchemy / auth / persistence）
    regression_trend.db      回归框架的趋势库（runs / task_details）

两者各写各的，CLI 的 `regression trend` 却只读主库的 `regression_records`
—— 结果是"趋势写了一份、读的是另一份"。现在统一到：

    <repo>/database/ic_verification.db

`regression_trend.db` 的历史数据已并入主库的同名 `runs` / `task_details` 表；
`TrendDatabase` 直接写主库。**不再有第二份趋势库。**
"""
from __future__ import annotations

import os
from pathlib import Path

#: 仓库根（本文件在 `<repo>/config/paths.py`）
_REPO_ROOT = Path(__file__).resolve().parent.parent

#: 运行期根目录：
#:   · 源码/仓库运行 → 仓库根（database/ 就在仓库里）
#:   · pip 安装后运行 → 用 SIGNOFFAI_HOME 指到用户数据目录，
#:     否则数据库会写进 site-packages。
PROJECT_ROOT = Path(os.environ.get("SIGNOFFAI_HOME", _REPO_ROOT)).expanduser().resolve()

#: 所有运行期数据库的唯一目录（不进 git）
DATABASE_DIR = PROJECT_ROOT / "database"

#: 主库 —— 领域数据 + 回归趋势 + 权限等（趋势没有第二份库）
MAIN_DB = DATABASE_DIR / "ic_verification.db"

#: 领域注册表 / 成长库 —— 仍然一库一域，但**位置统一**在 database/
MODEL_DB = DATABASE_DIR / "model_registry.db"
LINEAGE_DB = DATABASE_DIR / "lineage.db"
TESTCASE_DB = DATABASE_DIR / "testcase_registry.db"
IP_DB = DATABASE_DIR / "ip_registry.db"
EXCLUDE_DB = DATABASE_DIR / "exclude_registry.db"
COVERAGE_EXPERIENCE_DB = DATABASE_DIR / "coverage_experience.db"
DEBUG_EXPERIENCE_DB = DATABASE_DIR / "debug_experience.db"
RULE_STATS_DB = DATABASE_DIR / "rule_stats.db"
HINT_STATS_DB = DATABASE_DIR / "hint_stats.db"
REFERENCE_FINDER_CACHE_DB = DATABASE_DIR / "reference_finder_cache.db"


def ensure_database_dir() -> Path:
    """创建 database/（幂等）。"""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    return DATABASE_DIR


def db_path(path: str | Path | None = None) -> Path:
    """解析数据库路径：显式路径优先，否则用主库。"""
    return Path(path) if path else MAIN_DB


def sqlite_url(path: str | Path | None = None) -> str:
    """SQLAlchemy 用的绝对 SQLite URL（Windows 盘符也走 POSIX 分隔符）。"""
    return f"sqlite+aiosqlite:///{db_path(path).as_posix()}"
