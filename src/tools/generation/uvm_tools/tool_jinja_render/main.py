"""Tool: jinja_render — Jinja2 渲染 UVM 代码（确定性生成）

用法:
    python d:/cdv_a/src/tools/generation/uvm_tools/tool_jinja_render/main.py [output_dir]
    from src.tools.generation.uvm_tools.tool_jinja_render.main import run
    result = run(output_dir)
"""
import sys, json
import builtins
from pathlib import Path

from src.tools.common.lib.uvm_context import ctx
from src.tools.generation.uvm_tools.tool_uvm.generators.orchestrator import UVMGenerator
from src.tools.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer
from src.tools.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR


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
    # **一次把全部 YAML 交给生成器**，不要逐个文件调。
    #
    # 逐个调会切断**跨文件**的推导：`env_name` 已从 YAML 下线，bench / constraint 的
    # 环境名由「**本次调用**解析出的 environment」回填（见 `gen_uvm.run` 的
    # `default_env = environments[0].env_name if environments else ""`）。逐个文件调时
    # 处理 `bench.yaml` 的那一次里根本没有 environments —— 于是 `bench.env_name`
    # 停在空串，渲染出来的 tb_top 里就是 `import _test_pkg::*`（`_test_pkg` 这个包
    # 不存在，vlog 报 `Could not find the package`）。
    all_files = list(generator.run(yaml_files))
    print(f"    {len(yaml_files)} 个 YAML -> {len(all_files)} 个文件", flush=True)

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
