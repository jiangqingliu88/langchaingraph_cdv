"""生成 `schema/dsl.schema.json` —— 从 pydantic 模型现推。

**手改那份 JSON 没有意义**：`tests/test_schema.py` 会断言它与模型一致，
改了测试就红。要改契约就改 `domain/dsl.py`，然后跑这个脚本。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ..analysis.schema_check import DSL_SCHEMA_FILE, generated_schema


def main() -> int:
    target = Path(DSL_SCHEMA_FILE)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(generated_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(f"写出 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
