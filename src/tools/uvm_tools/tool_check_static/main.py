"""Tool: check_static -- 验证所有预期 UVM 文件是否存在
"""
import sys, json
from pathlib import Path
from src.tools.lib.uvm_context import ctx
from src.tools.lib.static_check import run_static_check

def run(env_dir: str = "") -> str:
    od = Path(env_dir) if env_dir else Path(ctx.output_dir)
    r = run_static_check(od, ctx.agents)
    return json.dumps(r, ensure_ascii=False)

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
