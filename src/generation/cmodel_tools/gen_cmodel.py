"""Generate UVM C-Model Predictor SV + DPI C++ wrapper — generic over signal lists.

Usage:
    python -m src.tools.compilesim.gen_cmodel <cmodel_dir> [module_name] [in_agent] [out_agent]

Signals are auto-detected from agent YAML configs in src/tools/uvm/tool_uvm/.
"""
import sys, yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


def _detect_signals(module_name: str) -> dict:
    """Auto-detect input/output signal lists from agent YAML configs."""
    yaml_dir = Path("src/tools/uvm/tool_uvm")
    input_signals = []
    output_signals = []
    agent_in_type = f"{module_name}_seq_item"
    agent_out_type = f"{module_name}_out_seq_item"

    # Try to find matching YAML files
    candidates = [
        yaml_dir / f"{module_name}_in.yaml",
        yaml_dir / f"{module_name.upper()}_in.yaml",
    ]
    out_candidates = [
        yaml_dir / f"{module_name}_out.yaml",
        yaml_dir / f"{module_name.upper()}_out.yaml",
    ]

    for yf in candidates:
        if yf.exists():
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            iface = data.get("interfaces", data)
            for var in iface.get("transaction_vars", []):
                name = var.get("name", "")
                if var.get("isrand", "True") == "True":
                    input_signals.append(name)
            agent_in_type = f"{iface.get('name', module_name)}_seq_item"
            break

    for yf in out_candidates:
        if yf.exists():
            data = yaml.safe_load(yf.read_text(encoding="utf-8"))
            iface = data.get("interfaces", data)
            for var in iface.get("transaction_vars", []):
                output_signals.append(var.get("name", ""))
            agent_out_type = f"{iface.get('name', module_name + '_out')}_seq_item"
            break

    return {
        "input_signals": input_signals or ["a", "b", "op"],
        "output_signals": output_signals or ["result", "flags"],
        "agent_in_type": agent_in_type,
        "agent_out_type": agent_out_type,
    }


def generate_cmodel(cmodel_dir: str, module_name: str = "dut",
                    agent_in: str = "", agent_out: str = "") -> dict:
    """Generate UVM cmodel predictor + DPI wrapper from C++ ref model."""
    from src.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR
    from src.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer

    cmodel = Path(cmodel_dir)
    cmodel.mkdir(parents=True, exist_ok=True)
    renderer = JinjaRenderer(TEMPLATES_DIR)

    signals = _detect_signals(module_name)
    ctx = {
        "module_name": module_name,
        "agent_in_name": agent_in,
        "agent_out_name": agent_out,
        **signals,
    }

    # DPI wrapper
    dpi_code = renderer.render("environment_templates/cmodel_dpi.cpp.j2", ctx)
    dpi_path = cmodel / f"{module_name}_dpi_wrapper.cpp"
    dpi_path.write_text(dpi_code, encoding="utf-8")

    # UVM predictor
    sv_code = renderer.render("environment_templates/cmodel_predictor.sv.j2", ctx)
    sv_path = cmodel / f"{module_name}_cmodel_predictor.sv"
    sv_path.write_text(sv_code, encoding="utf-8")

    return {"status": "PASS", "files": [str(sv_path), str(dpi_path)],
            "signals": signals}


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else "output/cmodel"
    n = sys.argv[2] if len(sys.argv) > 2 else "dut"
    r = generate_cmodel(d, n)
    print(f"{r['status']}: {len(r['files'])} files → {r['cmodel_dir']}")
    print(f"  Inputs: {r['signals']['input_signals']}")
    print(f"  Outputs: {r['signals']['output_signals']}")
    for f in r["files"]:
        print(f"  {f}")
