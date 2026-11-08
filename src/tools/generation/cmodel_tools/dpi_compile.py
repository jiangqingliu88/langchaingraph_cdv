"""DPI Compile: build C++ reference model + DPI wrapper → shared library for QuestaSim"""
import os, subprocess, sys
from pathlib import Path


def compile_cmodel_dpi(cmodel_dir: str, module_name: str = "dut",
                       questa_dir: str = None) -> dict:
    """
    Compile C++ model + DPI wrapper into a shared library.
    Returns {"status": "PASS"/"FAIL", "lib_path": "...", "log": "..."}
    questa_dir 为空时由 config.settings.questa_home() 解析。
    """
    cmodel = Path(cmodel_dir)
    if not cmodel.exists():
        return {"status": "FAIL", "error": f"cmodel dir not found: {cmodel_dir}"}
    if not questa_dir:
        from config.settings import questa_home
        questa_dir = questa_home()

    # Source files
    ref_h     = cmodel / f"{module_name}_ref_model.h"
    ref_cpp   = cmodel / f"{module_name}_ref_model.cpp"
    dpi_cpp   = cmodel / f"{module_name}_dpi_wrapper.cpp"
    test_cpp  = cmodel / f"test_{module_name}_ref_model.cpp"

    # Generate DPI wrapper from template if not exists
    if not dpi_cpp.exists():
        from src.tools.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR
        from src.tools.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer
        renderer = JinjaRenderer(TEMPLATES_DIR)
        dpi_code = renderer.render("interface_templates/cmodel_dpi.cpp.j2",
                                   {"module_name": module_name})
        dpi_cpp.write_text(dpi_code, encoding="utf-8")

    # Find QuestaSim GCC
    gcc_dir = Path(questa_dir) / "gcc-8.1.0" / "win64"
    gcc = None
    for candidate in [
        gcc_dir / "bin" / "g++.exe",
        Path(questa_dir) / ".." / "gcc-8.1.0" / "win64" / "bin" / "g++.exe",
    ]:
        if candidate.exists():
            gcc = str(candidate)
            break
    if not gcc:
        return {"status": "FAIL", "error": "g++ not found in QuestaSim directory"}

    # Include paths
    inc_dir = Path(questa_dir) / "include"
    includes = [f"-I{inc_dir}"] if inc_dir.exists() else []

    # Output library
    build_dir = cmodel / "build"
    build_dir.mkdir(exist_ok=True)
    lib_name = f"{module_name}_cmodel"
    lib_path = build_dir / f"{lib_name}.so"

    # Compile
    cmd = [gcc, "-shared", "-fPIC", "-std=c++17", "-o", str(lib_path)]
    cmd += includes
    cmd += [str(ref_cpp), str(dpi_cpp)]
    if test_cpp.exists():
        cmd += [str(test_cpp)]

    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                       cwd=str(cmodel))
    if r.returncode != 0:
        return {"status": "FAIL", "error": r.stderr[:500],
                "cmd": " ".join(cmd)}

    return {"status": "PASS", "lib_path": str(lib_path),
            "cmd": " ".join(cmd[:3]) + " ...",
            "output": f"Built {lib_name}.so ({lib_path.stat().st_size} bytes)"}


if __name__ == "__main__":
    result = compile_cmodel_dpi(sys.argv[1] if len(sys.argv) > 1 else "output/cmodel",
                                sys.argv[2] if len(sys.argv) > 2 else "dut")
    print(result["status"])
    if result["status"] == "PASS":
        print(f"  Library: {result['lib_path']}")
    else:
        print(f"  Error: {result.get('error', 'unknown')}")
