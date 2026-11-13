"""Tool: quality_report -- 质量报告（静态+编译+闭环评分）
"""
import sys, json
from pathlib import Path
from src.runtime_plane.tools.common.lib.uvm_context import ctx
from src.runtime_plane.tools.common.lib.quality_report import generate_quality_report

def run(output_dir: str = "") -> str:
    od = Path(output_dir) if output_dir else Path(ctx.output_dir)
    report = generate_quality_report(od, ctx.agents, ctx.env_name)
    return json.dumps({
        "status": "ok", "passed": report["passed"],
        "scores": report["scores"], "grade": report["grade"],
        "verdict": report["verdict"], "details": report["details"],
    }, ensure_ascii=False, default=str)

if __name__ == "__main__":
    print(run(sys.argv[1] if len(sys.argv) > 1 else ""))
