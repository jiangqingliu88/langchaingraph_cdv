"""Tool: check_health -- 环境顶层健康检查
"""
import sys, json
from pathlib import Path
from src.runtime_plane.tools.common.lib.uvm_context import ctx
from src.runtime_plane.tools.common.lib.compile import run_compile_check

def run(env_dir: str = "") -> str:
    od = Path(env_dir) if env_dir else Path(ctx.output_dir)
    r = run_compile_check(od, ctx.agents, ctx.env_name)
    return json.dumps({"status": r.get("status","?"), "errors": r.get("errors",0), "score": f"{r.get('score',0)}/25"}, ensure_ascii=False)

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
