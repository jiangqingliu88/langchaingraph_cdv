"""Tool: read_file -- 读取生成的 SystemVerilog 文件
"""
import sys
from pathlib import Path
from src.runtime_plane.tools.common.lib.uvm_context import ctx

def run(path: str) -> str:
    p = Path(path)
    if not p.is_absolute():
        p = Path(ctx.output_dir) / path
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else f"ERROR: file not found: {p}"

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
