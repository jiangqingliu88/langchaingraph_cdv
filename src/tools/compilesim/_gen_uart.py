"""UART UVM code generation — called by build_uart.bat"""
import asyncio, os
from pathlib import Path
from src.agents.spec_planner import SpecAndTestPlanner
from src.agents.architect import VerificationArchitect

GENDIR = Path(os.environ.get("GENDIR", "D:/tmp/uart_gen"))
SPEC_FILE = Path("spec_uart.txt")


async def main():
    spec = SPEC_FILE.read_text(encoding="utf-8")

    s = SpecAndTestPlanner()
    await s.initialize()
    r1 = await s.execute_task({"input": spec, "bypass": True})

    a = VerificationArchitect()
    await a.initialize()
    r2 = await a.execute_task({
        "input": r1.data["output"],
        "bypass": True,
        "output_dir": str(GENDIR),
    })

    fl = GENDIR / "filelist.f"
    print(f"success={r2.success} error={r2.error[:80] if r2.error else 'none'}")
    print(f"filelist={'OK' if fl.exists() else 'MISSING'} files={len(r2.data.get('files',[]))}")


if __name__ == "__main__":
    asyncio.run(main())
