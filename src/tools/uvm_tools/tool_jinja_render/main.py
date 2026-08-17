"""Tool: jinja_render — Jinja2 渲染 UVM 代码（确定性生成）

用法:
    python d:/cdv_a/src/tools/uvm_tools/tool_jinja_render/main.py [output_dir]
    from src.tools.uvm_tools.tool_jinja_render.main import run
    result = run(output_dir)
"""
import sys, json
import builtins
from pathlib import Path

from src.tools.lib.uvm_context import ctx
from src.tools.uvm_tools.tool_uvm.gen_uvm import UVMGenerator, JinjaRenderer, TEMPLATES_DIR


def print(*args, **kwargs):
    """本模块诊断日志默认写 stderr（stdout 保留给业务输出/--json，不被污染）。"""
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


def run(output_dir: str = "") -> str:
    """用 Jinja2 渲染所有 YAML → UVM SystemVerilog 骨架文件。

    Returns JSON: {status, file_count, agents, files}
    """
    od = Path(output_dir) if output_dir else Path(ctx.output_dir)
    od.mkdir(parents=True, exist_ok=True)

    yaml_dir = od / "inputs" / "yaml" / "uvm"
    yaml_files = sorted(yaml_dir.glob("*.yaml")) if yaml_dir.exists() else []
    if not yaml_files:
        return json.dumps({"status": "error", "error": f"No YAML files in {yaml_dir}"}, ensure_ascii=False)

    renderer = JinjaRenderer(TEMPLATES_DIR)
    generator = UVMGenerator(renderer, od)
    all_files = []
    for yp in yaml_files:
        generated = generator.run([yp])
        all_files.extend(generated)
        print(f"    {yp.name} -> {len(generated)} files", flush=True)

    # 更新 ctx
    agent_names = set()
    for f in all_files:
        parts = Path(str(f)).parts
        if "agents" in parts:
            idx = parts.index("agents")
            if idx + 1 < len(parts):
                agent_names.add(parts[idx + 1])
    if agent_names:
        ctx.update_agents([{"name": n} for n in sorted(agent_names)])

    return json.dumps({
        "status": "ok",
        "file_count": len(all_files),
        "agents": sorted(agent_names),
        "files": [str(f) for f in all_files],
    }, ensure_ascii=False)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else ""
    print(run(out))
