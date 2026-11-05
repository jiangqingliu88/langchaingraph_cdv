#!/usr/bin/env python3
"""CI 入口：文件行数 / 函数圈复杂度预算（实现见 config/architecture_guard.py）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config.architecture_guard import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
