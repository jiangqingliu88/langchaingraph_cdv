"""临时脚本：跑一轮七 Agent 闭环（specs/apb_uart）。"""
import asyncio, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.layers.l2_orchestration.execution import PipelineExecutionService


async def main():
    spec_text = Path("specs/apb_uart/apb_uart_spec.md").read_text(encoding="utf-8")
    svc = PipelineExecutionService.get_instance()
    t0 = time.time()
    try:
        result = await svc.run_closed_loop(
            spec_text, output_root="output/apb_uart_run", max_rounds=10,
        )
    except Exception as e:
        import traceback
        print("EXCEPTION:", e)
        traceback.print_exc()
        return
    elapsed = time.time() - t0
    print("=" * 70)
    print(f"final_coverage    : {result.get('final_coverage')}")
    print(f"effective_coverage: {result.get('effective_coverage')}")
    print(f"converged         : {result.get('converged')}")
    print(f"status            : {result.get('status')}")
    print(f"iterations        : {result.get('iterations')}")
    print(f"target            : {result.get('target')}")
    print(f"elapsed           : {elapsed:.1f}s")
    print(f"exclude           : {result.get('exclude')}")
    print("-" * 70)
    for p in result.get("phases", []):
        print(f"  {p.get('name','?'):22s} {p.get('status','?'):14s} "
              f"score={p.get('score','-')} {p.get('reason','') or p.get('action','')}")
    print("=" * 70)


asyncio.run(main())
