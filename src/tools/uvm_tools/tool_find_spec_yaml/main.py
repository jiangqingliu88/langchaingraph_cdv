"""
Tool: find_spec_yaml — 从 spec 文本查找已有 YAML 或构造新的 YAML

用法:
    python -m src.tools.uvm_tools.tool_find_spec_yaml.main "module alu(...);"
    # 或编程调用:
    from src.tools.uvm_tools.tool_find_spec_yaml.main import run
    result = run(spec_text)
"""
import sys, json, re
from pathlib import Path
import shutil as _shutil

from src.tools.lib.uvm_context import ctx
from src.tools.uvm_tools.tool_uvm.gen_uvm import TEMPLATES_DIR


def run(spec_text: str) -> str:
    """查找已有 YAML 或从 spec 构造 YAML，复制到 output/inputs/yaml/uvm/。

    返回 JSON: {status, yaml_files, module_name, agent_names}
    """
    yaml_dir = (Path(__file__).resolve().parent.parent / "tool_uvm")
    output_dir = Path(ctx.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    module_match = re.search(r'module:\s*(\w+)', spec_text, re.IGNORECASE)
    if not module_match:
        module_match = re.search(r'(?:#|module\s+)\s*(\w+)', spec_text, re.IGNORECASE)
    module_name = module_match.group(1) if module_match else ""
    # 回退：使用共享上下文中已设置的 env_name（去除 _env 后缀）
    if not module_name or module_name.lower() in ("dut", "dut_top"):
        env = ctx.env_name or ""
        if env.endswith("_env"):
            env = env[:-4]
        if env and env.lower() not in ("dut", "dut_top"):
            module_name = env
    if not module_name:
        module_name = "dut"

    # 尝试找已有 YAML
    name_variants = [module_name, module_name.upper(), module_name.lower()]
    for seg in re.split(r'[_\-\s]+', module_name):
        if len(seg) >= 2:
            name_variants.extend([seg, seg.upper()])

    existing_yamls = []
    if yaml_dir.exists():
        for variant in name_variants:
            found = sorted(yaml_dir.glob(f"{variant}_*.yaml"))
            if found:
                existing_yamls = found
                break

    uvm_yaml_archive = output_dir / "inputs" / "yaml" / "uvm"
    uvm_yaml_archive.mkdir(parents=True, exist_ok=True)
    yaml_files = []

    if existing_yamls:
        print(f"  [find_yaml] Found {len(existing_yamls)} YAML for '{module_name}'", flush=True)
        for yp in existing_yamls:
            dest = uvm_yaml_archive / yp.name
            _shutil.copy2(yp, dest)
            yaml_files.append(str(dest))
    else:
        print(f"  [find_yaml] No YAML for '{module_name}', constructing...", flush=True)
        for direction in ["in", "out"]:
            agent_name = f"{module_name}_{direction}"
            yaml_str = f"""interfaces:
  name: {agent_name}
  clock: clk
  reset: rst
  parameters:
    - {{ name: DATA_WIDTH, type: int, value: '32' }}
  ports:
    - {{ name: clk, dir: input, width: 1 }}
    - {{ name: rst, dir: input, width: 1 }}
    - {{ name: data, dir: {'output' if direction == 'in' else 'input'}, width: DATA_WIDTH }}
    - {{ name: valid, dir: {'output' if direction == 'in' else 'input'}, width: 1 }}
    - {{ name: ready, dir: {'input' if direction == 'in' else 'output'}, width: 1 }}
  transaction_vars:
    - {{ name: data, type: "bit [DATA_WIDTH-1:0]", iscompare: 'True', isrand: 'True' }}
  transaction_constraints:
    - name: valid_c
      value: '{{{{ data inside {{{{[0:255]}}}}; }}}}'
  config:
    is_active: UVM_ACTIVE
"""
            yaml_path = uvm_yaml_archive / f"{agent_name}.yaml"
            yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
            yaml_files.append(str(yaml_path))

        # env YAML
        env_str = f"""environment:
  name: {module_name}_env
  agents:
    {module_name}_in:
      interface: {module_name}_in
      clock: clk
      reset: rst
    {module_name}_out:
      interface: {module_name}_out
      clock: clk
      reset: rst
"""
        env_path = uvm_yaml_archive / "env.yaml"
        env_path.write_text(env_str, encoding="utf-8", errors="replace")
        yaml_files.append(str(env_path))

        # bench YAML
        bench_str = f"""bench:
  name: {module_name}_bench
  env_name: {module_name}_env
  timeout: 10ms
  clk_rst:
    clocks:
      - {{ name: clk, period: 10ns, init: 0 }}
    resets:
      - {{ name: rst_n, init: 0, release_delay: 0 }}
  wire_decls:
    - {{ name: data_in,  width: 32 }}
    - {{ name: data_out, width: 32 }}
    - {{ name: valid_in, width: 1 }}
    - {{ name: ready_in, width: 1 }}
    - {{ name: valid_out, width: 1 }}
    - {{ name: ready_out, width: 1 }}
  assignments:
    - {{ lhs: ready_out, rhs: "1'b0" }}
  agents:
    {module_name}_in:
      interface: {module_name}_in
      clock: clk
      reset: rst_n
      instance: {module_name}_in_if
      connections:
        - {{ port: clk, wire: clk }}
        - {{ port: rst, wire: rst_n }}
        - {{ port: data, wire: data_in }}
        - {{ port: valid, wire: valid_in }}
        - {{ port: ready, wire: ready_in }}
    {module_name}_out:
      interface: {module_name}_out
      clock: clk
      reset: rst_n
      instance: {module_name}_out_if
      connections:
        - {{ port: clk, wire: clk }}
        - {{ port: rst, wire: rst_n }}
        - {{ port: data, wire: data_out }}
        - {{ port: valid, wire: valid_out }}
        - {{ port: ready, wire: ready_out }}
  dut:
    module: {module_name}
    instance: u_{module_name}
    parameters:
      - {{ name: DATA_WIDTH, value: 32 }}
    ports:
      - {{ name: clk, connection: clk }}
      - {{ name: rst_n, connection: rst_n }}
      - {{ name: data_in, connection: data_in }}
      - {{ name: valid_in, connection: valid_in }}
      - {{ name: ready_in, connection: ready_in }}
      - {{ name: data_out, connection: data_out }}
      - {{ name: valid_out, connection: valid_out }}
      - {{ name: ready_out, connection: ready_out }}
"""
        bench_path = uvm_yaml_archive / "bench.yaml"
        bench_path.write_text(bench_str, encoding="utf-8", errors="replace")
        yaml_files.append(str(bench_path))

    ctx.update_env_name(f"{module_name}_env")

    return json.dumps({
        "status": "ok",
        "module_name": module_name,
        "yaml_files": yaml_files,
        "yaml_count": len(yaml_files),
        "env_name": f"{module_name}_env",
    }, ensure_ascii=False)


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "module dut(input clk);"
    print(run(spec))
