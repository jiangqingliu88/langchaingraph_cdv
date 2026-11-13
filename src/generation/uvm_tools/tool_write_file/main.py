"""Tool: write_file -- 写入/覆盖 SystemVerilog 文件
"""
import sys
from pathlib import Path
from src.tools.common.lib.uvm_context import ctx

def run(path_content: str) -> str:
    parts = path_content.split("::", 1)
    if len(parts) != 2:
        return "ERROR: use format 'path::content'"
    path, content = parts
    p = Path(path.strip())
    if not p.is_absolute():
        p = Path(ctx.output_dir) / path.strip()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content.strip(), encoding="utf-8")
    return f"OK: wrote {len(content)} bytes to {p}"

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
