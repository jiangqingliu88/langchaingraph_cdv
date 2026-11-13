"""Tool: jinja_render — Jinja2 渲染 UVM 代码（确定性生成）

用法:
    python d:/cdv_a/src/generation/uvm_tools/tool_jinja_render/main.py [output_dir]
    from src.generation.uvm_tools.tool_jinja_render.main import run
    result = run(output_dir)
"""
import sys, json
import builtins
from pathlib import Path

from src.tools.common.lib.uvm_context import ctx
from src.generation.uvm_tools.tool_uvm.generators.orchestrator import UVMGenerator
from src.generation.uvm_tools.tool_uvm.render.jinja_renderer import JinjaRenderer
from src.generation.uvm_tools.tool_uvm.constants import TEMPLATES_DIR


def print(*args, **kwargs):
    """本模块诊断日志默认写 stderr（stdout 保留给业务输出/--json，不被污染）。"""
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


def run(output_dir: str = "", dest_dir: str = "") -> str:
    """用 Jinja2 渲染所有 YAML → UVM SystemVerilog 骨架文件。

    `output_dir` 是 run 根（YAML 输入在 `<run>/inputs/yaml/uvm`）；
    `dest_dir` 是可选的渲染落点（verify 在 VPlan 布局下传入暂存目录，
    避免先写顶层 `agents/` 再搬进 `sv/`）。缺省时与 `output_dir` 相同。

    Returns JSON: {status, file_count, agents, files, dest}
    """
    src_root = Path(output_dir) if output_dir else Path(ctx.output_dir)
    dest_root = Path(dest_dir) if dest_dir else src_root
    dest_root.mkdir(parents=True, exist_ok=True)

    yaml_dir = src_root / "inputs" / "yaml" / "uvm"
    yaml_files = sorted(yaml_dir.glob("*.yaml")) if yaml_dir.exists() else []
    if not yaml_files:
        return json.dumps({"status": "error", "error": f"No YAML files in {yaml_dir}"}, ensure_ascii=False)

    renderer = JinjaRenderer(TEMPLATES_DIR)
    generator = UVMGenerator(renderer, dest_root, source_root=src_root)
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
        "dest": str(dest_root),
    }, ensure_ascii=False)


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else ""
    print(run(out))
