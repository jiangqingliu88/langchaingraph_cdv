"""Tool: check_loopback -- 闭环编译+仿真检查
"""
import sys, json
from pathlib import Path
from src.runtime_plane.tools.common.lib.uvm_context import ctx
from src.runtime_plane.tools.common.lib.loopback import run_loopback_check

def run(env_dir: str = "") -> str:
    od = Path(env_dir) if env_dir else Path(ctx.output_dir)
    r = run_loopback_check(od, ctx.agents, ctx.env_name)
    return json.dumps(r, ensure_ascii=False, default=str)

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
