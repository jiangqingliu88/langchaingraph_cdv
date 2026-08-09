"""
OpenTitan UART 端到端验证 — 从 spec 到 signoff
==============================================
读取 opentitan/hw/ip/uart/doc/theory_of_operation.md
→ spec_planner 生成结构化 spec
→ 写入 projects/earlgrey/hw/ip/uart/data/uart.hjson
→ 生成 uart_testplan.hjson
→ (后续) 输入 dvsim 回归
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

# ── 路径 ──
OPENTITAN_UART = Path("opentitan/hw/ip/uart")
SPEC_MD  = OPENTITAN_UART / "doc" / "theory_of_operation.md"
REG_MD   = OPENTITAN_UART / "doc" / "registers.md"
IFACE_MD = OPENTITAN_UART / "doc" / "interfaces.md"
GROUND_TRUTH_HJSON = OPENTITAN_UART / "data" / "uart.hjson"
GROUND_TRUTH_TESTPLAN = OPENTITAN_UART / "data" / "uart_testplan.hjson"

OUTPUT_DIR = Path("projects/earlgrey/hw/ip/uart/data")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


async def step1_read_spec() -> str:
    """Step 1: 读取 OpenTitan UART 设计文档"""
    console.print(Panel.fit("Step 1: Reading OpenTitan UART spec docs", title="Pipeline"))

    spec_text = ""
    for path, label in [(SPEC_MD, "Theory of Operation"),
                         (REG_MD, "Registers"),
                         (IFACE_MD, "Interfaces")]:
        if path.exists():
            content = path.read_text(encoding="utf-8", errors="replace")
            spec_text += f"\n\n## {label}\n{content}"
            console.print(f"  [green]OK[/green] {label}: {len(content)} chars")
        else:
            console.print(f"  [yellow]SKIP[/yellow] {label}: file not found at {path}")

    console.print(f"  Total spec text: {len(spec_text)} chars\n")
    return spec_text[:8000]  # limit for LLM context


async def step2_spec_planner(spec_text: str) -> dict:
    """Step 2: 运行 spec_planner Agent 生成结构化 spec"""
    console.print(Panel.fit("Step 2: Running spec_planner Agent", title="Pipeline"))

    from src.agents.spec_planner import SpecAndTestPlanner
    agent = SpecAndTestPlanner()
    await agent.initialize()

    task = {"input": spec_text}
    console.print("  Sending to LLM (deepseek-chat)...")
    result = await agent.execute_task(task)

    if result.success:
        spec = result.data.get("spec", {}) or result.data
        console.print(f"  [green]OK[/green] Score: {result.data.get('score', '?')}")
        console.print(f"  Design: {spec.get('design_name', '?')}")
        console.print(f"  Features: {len(spec.get('features', []))}")
        console.print(f"  Interfaces: {len(spec.get('interfaces', []))}")
        console.print(f"  Registers: {len(spec.get('registers', []))}")
        console.print(f"  Test points: {sum(len(tp.get('tests', [])) for tp in spec.get('test_points', []))}")
        return spec
    else:
        console.print(f"  [red]FAILED[/red]: {result.error}")
        return {}


async def step3_generate_hjson(spec: dict) -> str:
    """Step 3: 将结构化 spec 转为 OpenTitan 风格的 uart.hjson"""
    console.print(Panel.fit("Step 3: Generating uart.hjson", title="Pipeline"))

    import hjson as hjson_lib

    # Build hjson compatible dict
    hjson_data = {
        "name": spec.get("design_name", "uart"),
        "human_name": spec.get("design_name", "UART"),
        "one_line_desc": spec.get("overview", "")[:100],
        "one_paragraph_desc": spec.get("overview", ""),
        "clocking": [{"clock": "clk_i", "reset": "rst_ni"}],
        "bus_interfaces": [
            {"protocol": iface.get("type", "TLUL"), "direction": "device",
             "data_width": iface.get("data_width", 32)}
            for iface in spec.get("interfaces", [])
        ],
        "available_input_list": [
            {"name": sig_name, "desc": sig_desc}
            for iface in spec.get("interfaces", [])
            for sig_name, sig_desc in iface.get("signals", {}).items()
            if "in" in sig_desc.lower() or "input" in sig_desc.lower()
        ],
        "available_output_list": [
            {"name": sig_name, "desc": sig_desc}
            for iface in spec.get("interfaces", [])
            for sig_name, sig_desc in iface.get("signals", {}).items()
            if "out" in sig_desc.lower() or "output" in sig_desc.lower()
        ],
        "interrupt_list": [
            {"name": reg.get("name", ""), "desc": reg.get("description", "")}
            for reg in spec.get("registers", [])
            if "int" in reg.get("name", "").lower() or "status" in reg.get("name", "").lower()
        ],
        "features": [
            {"id": f"FEAT-{i:03d}", "name": f.get("name", ""),
             "priority": f.get("priority", "P1"), "stage": "V1"}
            for i, f in enumerate(spec.get("features", []), 1)
        ],
        "registers": spec.get("registers", []),
    }

    hjson_str = hjson_lib.dumps(hjson_data, indent=2)
    output_path = OUTPUT_DIR / "uart.hjson"
    output_path.write_text(hjson_str, encoding="utf-8")
    console.print(f"  [green]OK[/green] Written to {output_path}")

    # Compare with ground truth
    if GROUND_TRUTH_HJSON.exists():
        gt = GROUND_TRUTH_HJSON.read_text(encoding="utf-8", errors="replace")
        console.print(f"  Ground truth: {GROUND_TRUTH_HJSON} ({len(gt)} chars)")
        console.print(f"  Generated:    {len(hjson_str)} chars")

    return hjson_str


async def step4_generate_testplan(spec: dict) -> str:
    """Step 4: 从 spec 推导 testplan.hjson"""
    console.print(Panel.fit("Step 4: Generating uart_testplan.hjson", title="Pipeline"))

    import hjson as hjson_lib

    test_points = spec.get("test_points", [])
    features = spec.get("features", [])

    # Build testplan
    testplan_data = {
        "name": spec.get("design_name", "uart"),
        "import_testplans": [
            "{proj_root}/hw/dv/tools/dvsim/testplans/csr_testplan.hjson",
            "{proj_root}/hw/dv/tools/dvsim/testplans/intr_test_testplan.hjson",
            "{proj_root}/hw/dv/tools/dvsim/testplans/stress_all_with_reset_testplan.hjson",
        ],
        "testpoints": [],
        "covergroups": [],
    }

    # Generate testpoints from spec
    for cat in test_points[:10]:
        cat_name = cat.get("category", "unknown")
        for t in cat.get("tests", [])[:20]:
            testpoint = {
                "name": t.get("name", "").replace("test_", ""),
                "desc": t.get("description", ""),
                "stage": "V1" if cat_name == "basic_function" else "V2",
                "tests": [t.get("name", "")],
            }
            testplan_data["testpoints"].append(testpoint)

    # Generate covergroups from features
    for feat in features[:8]:
        cg = {
            "name": f"{feat.get('name', 'feat')}_cg",
            "desc": feat.get("description", ""),
            "coverpoints": [
                {"name": f"{feat.get('name', 'feat')}_check", "bins": ["covered"]}
            ],
        }
        testplan_data["covergroups"].append(cg)

    hjson_str = hjson_lib.dumps(testplan_data, indent=2)
    output_path = OUTPUT_DIR / "uart_testplan.hjson"
    output_path.write_text(hjson_str, encoding="utf-8")
    console.print(f"  [green]OK[/green] Written to {output_path}")
    console.print(f"  Testpoints: {len(testplan_data['testpoints'])}")
    console.print(f"  Covergroups: {len(testplan_data['covergroups'])}")

    if GROUND_TRUTH_TESTPLAN.exists():
        gt = GROUND_TRUTH_TESTPLAN.read_text(encoding="utf-8", errors="replace")
        console.print(f"  Ground truth: {len(gt)} chars | Generated: {len(hjson_str)} chars")

    return hjson_str


async def step5_compare_with_ground_truth():
    """Step 5: 对比 AI 生成的 vs OpenTitan 人工编写的"""
    console.print(Panel.fit("Step 5: Comparing with ground truth", title="Pipeline"))

    table = Table(title="AI Generated vs Ground Truth")
    table.add_column("Item", style="cyan")
    table.add_column("AI Generated")
    table.add_column("OpenTitan")

    # Count testpoints
    if (OUTPUT_DIR / "uart_testplan.hjson").exists():
        import hjson as hjson_lib
        ai = hjson_lib.loads((OUTPUT_DIR / "uart_testplan.hjson").read_text(encoding="utf-8"))
        gt = hjson_lib.loads(GROUND_TRUTH_TESTPLAN.read_text(encoding="utf-8"))

        table.add_row("Testpoints", str(len(ai.get("testpoints", []))),
                       str(len(gt.get("testpoints", []))))
        table.add_row("Covergroups", str(len(ai.get("covergroups", []))),
                       str(len(gt.get("covergroups", []))))
        table.add_row("Import testplans", str(len(ai.get("import_testplans", []))),
                       str(len(gt.get("import_testplans", []))))

    console.print(table)


async def main():
    console.print(Panel.fit(
        "[bold]OpenTitan UART → SignOffAI Pipeline[/bold]\n"
        f"Source: {SPEC_MD}\n"
        f"Target: {OUTPUT_DIR}",
        title="End-to-End Verification"
    ))

    try:
        # Step 1-4: generate spec + testplan
        spec_text = await step1_read_spec()
        spec = await step2_spec_planner(spec_text)
        if not spec:
            console.print("[red]Spec planner failed — check LLM API[/red]")
            return

        await step3_generate_hjson(spec)
        await step4_generate_testplan(spec)

        # Step 5: compare
        if GROUND_TRUTH_TESTPLAN.exists():
            await step5_compare_with_ground_truth()

        console.print(f"\n[bold green]Pipeline complete![/bold green]")
        console.print(f"  [cyan]vagent verify --pipeline full_verification --scope ip.uart[/cyan]")

    except Exception as e:
        console.print(f"[red]Pipeline failed: {e}[/red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
