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


def _load_spec(output_dir: Path) -> dict | None:
    """尝试从输出目录加载 spec.json（由 verify_architect 保存）"""
    spec_path = output_dir / "spec.json"
    if spec_path.exists():
        try:
            return json.loads(spec_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return None


def _parse_rtl_module(rtl_dir: Path, module_name: str) -> dict | None:
    """扫描 RTL 目录，找到 module_name 对应的模块定义，返回端口列表"""
    if not rtl_dir.exists():
        return None
    # 收集所有模块定义
    modules = {}  # module_name → {ports: [{name, dir, width}], params: [{name, value}]}
    for sv in sorted(rtl_dir.glob("*.sv")):
        try:
            text = sv.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        # 匹配 module X #(...) (...);  或  module X (...);
        m = re.search(r'module\s+(\w+)\s*(#\s*\([^)]*\))?\s*\(([^)]*)\)\s*;', text, re.DOTALL)
        if not m:
            continue
        mod_name = m.group(1)
        ports_str = m.group(3) if m.group(3) else ""

        ports = []
        params = []
        # 解析参数
        param_str = m.group(2) or ""
        for pm in re.finditer(r'parameter\s+(\w+)\s*=\s*(\d+)', param_str):
            params.append({"name": pm.group(1), "value": pm.group(2)})

        # 解析端口: input/output/inout [type] [width] name
        for line in ports_str.split(","):
            line = line.strip()
            if not line:
                continue
            # 匹配: input/output/inout [可选类型] [可选宽度] name
            pm = re.match(
                r'(input|output|inout)\s+(?:logic|wire|reg|bit)?\s*(?:\[(\d+)(?::(\d+))?\])?\s*(\w+)',
                line.strip()
            )
            if pm:
                direction = pm.group(1)
                hi = int(pm.group(2)) if pm.group(2) else 0
                lo = int(pm.group(3)) if pm.group(3) else 0
                width = (hi - lo + 1) if pm.group(2) else 1
                ports.append({"name": pm.group(4), "direction": direction, "width": width})
            else:
                # 简化匹配: input/output name
                sm = re.match(r'(input|output|inout)\s+(\w+)', line.strip())
                if sm:
                    ports.append({"name": sm.group(2), "direction": sm.group(1), "width": 1})

        modules[mod_name] = {"ports": ports, "params": params}

    if not modules:
        return None

    # 查找匹配的顶层模块
    def _name_match(target, mods):
        """大小写不敏感查找，精确匹配 > 前缀匹配 > 包含匹配"""
        tl = target.lower()
        for mn in mods:
            if mn.lower() == tl:
                return mn
        for mn in mods:
            if mn.lower().startswith(tl):
                return mn
        for mn in mods:
            if tl in mn.lower():
                return mn
        return None

    matched = _name_match(module_name, modules)
    if matched:
        return modules[matched] | {"module_name": matched}

    # 回退 1：找 *_top.sv 文件中的模块（顶层模块命名惯例）
    for sv in sorted(rtl_dir.glob("*top*.sv")):
        try:
            text = sv.read_text(encoding="utf-8", errors="replace")[:1000]
            m = re.search(r'module\s+(\w+)', text)
            if m and m.group(1) in modules:
                return modules[m.group(1)] | {"module_name": m.group(1)}
        except Exception:
            continue

    # 回退 2：找实例化其他子模块最多的那个模块（顶层模块特征）
    if len(modules) > 1:
        best_mod, best_count = None, -1
        for mn, md in modules.items():
            inst_count = 0
            for sv in rtl_dir.glob("*.sv"):
                try:
                    text = sv.read_text(encoding="utf-8", errors="replace")
                    inst_count += len(re.findall(r'\b\w+\s+(?:#\s*\([^)]*\)\s*)?\w+\s*\(', text))
                except Exception:
                    continue
            if inst_count > best_count:
                best_count = inst_count
                best_mod = mn
        if best_mod:
            return modules[best_mod] | {"module_name": best_mod}

    # 回退 3：端口数最多的模块
    if modules:
        best = max(modules.items(), key=lambda x: len(x[1]["ports"]))
        return best[1] | {"module_name": best[0]}

    return None


def _yaml_escape(v) -> str:
    """值转 YAML 安全字符串"""
    s = str(v)
    if isinstance(v, bool) or (isinstance(v, str) and v.upper() in ("TRUE", "FALSE")):
        return s
    if s.isdigit() or (s.startswith("'") and s.endswith("'")):
        return s
    return f"'{s}'"


def _indent(text: str, n: int = 2) -> str:
    prefix = " " * n
    return "\n".join(prefix + line for line in text.split("\n"))


def _is_clock_port(name: str) -> bool:
    """检测是否为时钟端口"""
    n = name.lower()
    return "clk" in n or "clock" in n


def _is_reset_port(name: str) -> bool:
    """检测是否为复位端口"""
    n = name.lower()
    return "rst" in n or "reset" in n


def _generate_interface_yaml(agent: dict, interface: dict, module_name: str) -> str:
    """根据 spec 中的 agent + interface 数据生成 agent YAML"""
    ag_name = agent.get("name", f"{module_name}_agent")
    ports = agent.get("ports", [])
    if not ports:
        sigs = interface.get("signals", {})
        ports = [{"name": sig_name, "direction": sig.get("direction", "input"),
                  "width": sig.get("width", 1)}
                 for sig_name, sig in sigs.items()]

    # 从 ports 中识别 clock/reset（优先级：端口名检测 > agent 预设 > 默认值）
    detected_clock = None
    detected_reset = None
    data_ports = []
    for p in ports:
        if _is_clock_port(p["name"]):
            detected_clock = p
        elif _is_reset_port(p["name"]):
            detected_reset = p
        else:
            data_ports.append(p)
    clock_name = (detected_clock or {}).get("name") or agent.get("clock", "") or "clk"
    reset_name = (detected_reset or {}).get("name") or agent.get("reset", "") or "rst"
    # 接口端口列表：clock/reset 作为 input 加入（SV interface 需要它们声明为端口）
    all_interface_ports = []
    if detected_clock:
        all_interface_ports.append({"name": detected_clock["name"], "direction": "input",
                                     "width": detected_clock.get("width", 1)})
    else:
        all_interface_ports.append({"name": clock_name, "direction": "input", "width": 1})
    if detected_reset:
        all_interface_ports.append({"name": detected_reset["name"], "direction": "input",
                                     "width": detected_reset.get("width", 1)})
    else:
        all_interface_ports.append({"name": reset_name, "direction": "input", "width": 1})
    all_interface_ports.extend(data_ports)

    trans_vars = agent.get("transaction_vars", [])
    if not trans_vars:
        trans_vars = []
        for p in data_ports:
            w = p.get("width", 1)
            ttype = "bit [" + str(w - 1) + ":0]" if w > 1 else "bit"
            trans_vars.append({"name": p["name"], "type": ttype,
                               "iscompare": "True", "isrand": "True"})

    active = "UVM_ACTIVE" if agent.get("type", "").upper() in ("UVM_ACTIVE", "ACTIVE") else "UVM_PASSIVE"

    # Build YAML line by line
    lines = []
    lines.append("interfaces:")
    lines.append("  name: " + ag_name)
    lines.append("  clock: " + clock_name)
    lines.append("  reset: " + reset_name)

    lines.append("  parameters:")
    has_params = False
    for p in data_ports:
        w = p.get("width", 1)
        if w > 1:
            lines.append("    - { name: " + p['name'].upper() + "_WIDTH, type: int, value: '" + str(w) + "' }")
            has_params = True
    if not has_params:
        lines.append("    []")

    lines.append("  ports:")
    for p in all_interface_ports:
        w = p.get("width", 1)
        lines.append("    - { name: " + p['name'] + ", dir: " + p['direction'] + ", width: " + str(w) + " }")

    lines.append("  transaction_vars:")
    if trans_vars:
        for tv in trans_vars:
            lines.append("    - { name: " + tv['name'] + ", type: \"" + tv['type'] + "\","
                         " iscompare: '" + tv.get('iscompare', 'True') + "',"
                         " isrand: '" + tv.get('isrand', 'True') + "' }")
    else:
        lines.append("    []")

    # Compute constraint using first random transaction variable
    if trans_vars and data_ports:
        first_tv = trans_vars[0]["name"]
        first_p = data_ports[0]
        max_w = first_p.get("width", 1)
        if max_w > 1:
            max_val = (1 << min(max_w, 16)) - 1
            constraint_val = "{" + first_tv + " inside {[0:" + str(max_val) + "]}; }"
        else:
            constraint_val = "{" + first_tv + " inside {[0:1]}; }"
    else:
        constraint_val = "{ data inside {[0:255]}; }"
    lines.append("  transaction_constraints:")
    lines.append("    - name: data_c")
    lines.append("      value: '" + constraint_val + "'")

    lines.append("  config:")
    lines.append("    is_active: " + active)
    return "\n".join(lines) + "\n"


def run(spec_text: str) -> str:
    """查找已有 YAML 或从 spec 构造 YAML，复制到 output/inputs/yaml/uvm/。

    返回 JSON: {status, yaml_files, module_name, agent_names}
    """
    yaml_dir = (Path(__file__).resolve().parent.parent / "tool_uvm")
    output_dir = Path(ctx.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 确定模块名 ──
    module_match = re.search(r'module:\s*(\w+)', spec_text, re.IGNORECASE)
    if not module_match:
        module_match = re.search(r'(?:#|module\s+)\s*(\w+)', spec_text, re.IGNORECASE)
    module_name = module_match.group(1) if module_match else ""
    if not module_name or module_name.lower() in ("dut", "dut_top"):
        env = ctx.env_name or ""
        if env.endswith("_env"):
            env = env[:-4]
        if env and env.lower() not in ("dut", "dut_top"):
            module_name = env
    if not module_name:
        module_name = "dut"

    # ── 2. 尝试加载 spec 数据 ──
    spec = _load_spec(output_dir)

    # ── 3. 尝试解析 RTL 端口 ──
    rtl_data = _parse_rtl_module(output_dir / "rtl", module_name)

    # ── 4. 已有 YAML 检查 ──
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
    # 清理旧 YAML，避免残留 dut_* 文件
    for old in uvm_yaml_archive.glob("*.yaml"):
        try:
            old.unlink()
        except Exception:
            pass
    yaml_files = []

    if existing_yamls:
        print(f"  [find_yaml] Found {len(existing_yamls)} YAML for '{module_name}'", flush=True)
        for yp in existing_yamls:
            dest = uvm_yaml_archive / yp.name
            _shutil.copy2(yp, dest)
            yaml_files.append(str(dest))
    else:
        print(f"  [find_yaml] No YAML for '{module_name}', constructing...", flush=True)

        # ── 确定 agents 列表 ──
        agents_spec = []
        if spec and isinstance(spec, dict):
            va = spec.get("verification_architecture", {}) or {}
            ifaces = spec.get("interfaces", []) or []
            iface_map = {i.get("name", ""): i for i in ifaces}
            for ag in va.get("agents", []) or []:
                iface = iface_map.get(ag.get("interface", ""), {})
                agents_spec.append((ag, iface))

        if not agents_spec:
            # 回退：从 RTL 端口构造 in/out agents
            if rtl_data and rtl_data.get("ports"):
                in_ports = [p for p in rtl_data["ports"] if p["direction"] == "input"]
                out_ports = [p for p in rtl_data["ports"] if p["direction"] == "output"]
                if in_ports:
                    agents_spec.append((
                        {"name": f"{module_name}_in", "type": "UVM_ACTIVE",
                         "ports": in_ports},
                        {"name": f"{module_name}_in"}
                    ))
                if out_ports:
                    agents_spec.append((
                        {"name": f"{module_name}_out", "type": "UVM_PASSIVE",
                         "ports": out_ports},
                        {"name": f"{module_name}_out"}
                    ))

        if not agents_spec:
            # 最终回退：通用 in/out 模板
            for direction in ["in", "out"]:
                agent_name = f"{module_name}_{direction}"
                yaml_str = (
                    f"interfaces:\n  name: {agent_name}\n  clock: clk\n  reset: rst\n"
                    f"  parameters:\n    - {{ name: DATA_WIDTH, type: int, value: '32' }}\n"
                    f"  ports:\n    - {{ name: clk, dir: input, width: 1 }}\n"
                    f"    - {{ name: rst, dir: input, width: 1 }}\n"
                    f"    - {{ name: data, dir: {'output' if direction == 'in' else 'input'}, width: DATA_WIDTH }}\n"
                    f"    - {{ name: valid, dir: {'output' if direction == 'in' else 'input'}, width: 1 }}\n"
                    f"    - {{ name: ready, dir: {'input' if direction == 'in' else 'output'}, width: 1 }}\n"
                    f"  transaction_vars:\n    - {{ name: data, type: \"bit [DATA_WIDTH-1:0]\","
                    f" iscompare: 'True', isrand: 'True' }}\n"
                    f"  transaction_constraints:\n    - name: valid_c\n"
                    f"      value: '{{{{ data inside {{{{[0:255]}}}}; }}}}'\n"
                    f"  config:\n    is_active: UVM_ACTIVE\n"
                )
                yaml_path = uvm_yaml_archive / f"{agent_name}.yaml"
                yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
                yaml_files.append(str(yaml_path))
            print(f"  [find_yaml] Using generic data/valid/ready template (no spec/RTL data)", flush=True)

        # ── 5. 从 spec/RTL 数据生成 agent YAML ──
        agent_names = []
        clock_port = "clk"
        reset_port = "rst"
        for ag, iface in agents_spec:
            ag_name = ag.get("name", f"{module_name}_agent")
            agent_names.append(ag_name)
            clock_port = ag.get("clock", iface.get("clock", "clk"))
            reset_port = ag.get("reset", "clk")  # The reset port name for agents

            yaml_str = _generate_interface_yaml(ag, iface, module_name)
            yaml_path = uvm_yaml_archive / f"{ag_name}.yaml"
            yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
            yaml_files.append(str(yaml_path))
            print(f"  [find_yaml] Generated {ag_name}.yaml (from spec interfaces)" if spec else
                  f"  [find_yaml] Generated {ag_name}.yaml (from RTL ports)", flush=True)

        # ── 6. 生成 env YAML ──
        env_agents_lines = []
        for ag_name in agent_names:
            env_agents_lines.append(f"    {ag_name}:\n      interface: {ag_name}\n      clock: {clock_port}\n      reset: {reset_port}")
        env_str = (
            f"environment:\n  name: {module_name}_env\n  agents:\n"
            + "\n".join(env_agents_lines) + "\n"
        )
        env_path = uvm_yaml_archive / "env.yaml"
        env_path.write_text(env_str, encoding="utf-8", errors="replace")
        yaml_files.append(str(env_path))

        # ── 7. 生成 bench YAML ──
        # 收集所有端口用于 DUT 例化和 wire 声明
        all_ports = []
        if rtl_data and rtl_data.get("ports"):
            # 用 RTL 端口（最准确），模块名也来自 RTL
            all_ports = rtl_data["ports"]
            dut_module = rtl_data.get("module_name") or module_name
        elif spec and isinstance(spec, dict):
            # 从 spec interfaces 收集信号
            for iface in (spec.get("interfaces", []) or []):
                sigs = iface.get("signals", {})
                for sig_name, sig in sigs.items():
                    if isinstance(sig, dict):
                        all_ports.append({
                            "name": sig_name,
                            "direction": sig.get("direction", "input"),
                            "width": sig.get("width", 1)
                        })
            dut_module = module_name

        if not all_ports:
            # 最终回退
            all_ports = [
                {"name": "clk", "direction": "input", "width": 1},
                {"name": "rst_n", "direction": "input", "width": 1},
                {"name": "data_in", "direction": "input", "width": 32},
                {"name": "valid_in", "direction": "input", "width": 1},
                {"name": "ready_in", "direction": "input", "width": 1},
                {"name": "data_out", "direction": "output", "width": 32},
                {"name": "valid_out", "direction": "output", "width": 1},
                {"name": "ready_out", "direction": "output", "width": 1},
            ]
            dut_module = module_name

        # Wire declarations
        wire_lines = []
        for p in all_ports:
            w = p.get("width", 1)
            wire_lines.append(
                f"    - {{ name: {p['name']}, width: {w} }}"
                if w > 1 else
                f"    - {{ name: {p['name']}, width: 1 }}"
            )

        # DUT ports
        dut_port_lines = []
        for p in all_ports:
            dut_port_lines.append(f"      - {{ name: {p['name']}, connection: {p['name']} }}")

        # DUT parameters
        dut_params_lines = []
        for p in all_ports:
            w = p.get("width", 1)
            if w > 1:
                dut_params_lines.append(f"      - {{ name: {p['name'].upper()}_WIDTH, value: {w} }}")

        # Agent connections (connect each agent's ports to corresponding wires)
        agent_bench_lines = []
        for ag_name in agent_names:
            ag_data = None
            for ag, _ in agents_spec:
                if ag.get("name") == ag_name:
                    ag_data = ag
                    break
            ag_ports = ag_data.get("ports", []) if ag_data else []
            # 找对应的 clock/reset
            ag_clock = ag_data.get("clock", clock_port) if ag_data else clock_port
            ag_reset = ag_data.get("reset", reset_port) if ag_data else reset_port

            conn_lines = []
            for p in ag_ports:
                conn_lines.append(f"        - {{ port: {p['name']}, wire: {p['name']} }}")
            # 确保 clock 和 reset 连接
            if not any(c for c in conn_lines if f"port: {ag_clock}" in c):
                conn_lines.insert(0, f"        - {{ port: {ag_clock}, wire: {ag_clock} }}")
            if not any(c for c in conn_lines if f"port: {ag_reset}" in c):
                conn_lines.insert(1, f"        - {{ port: {ag_reset}, wire: {ag_reset} }}")

            agent_bench_lines.append(
                f"    {ag_name}:\n"
                f"      interface: {ag_name}\n"
                f"      clock: {ag_clock}\n"
                f"      reset: {ag_reset}\n"
                f"      instance: {ag_name}_if\n"
                f"      connections:\n"
                + "\n".join(conn_lines)
            )

        bench_str = f"""bench:
  name: {module_name}_bench
  env_name: {module_name}_env
  timeout: 10ms
  clk_rst:
    clocks:
      - {{ name: {clock_port}, period: 10ns, init: 0 }}
    resets:
      - {{ name: {reset_port}, init: 0, release_delay: 0 }}
  wire_decls:
{chr(10).join(wire_lines)}
  assignments: []
  agents:
{chr(10).join(agent_bench_lines)}
  dut:
    module: {dut_module}
    instance: u_{dut_module}
    parameters:
{chr(10).join(dut_params_lines) if dut_params_lines else '      []'}
    ports:
{chr(10).join(dut_port_lines)}
"""
        bench_path = uvm_yaml_archive / "bench.yaml"
        bench_path.write_text(bench_str, encoding="utf-8", errors="replace")
        yaml_files.append(str(bench_path))

    env_name = f"{module_name}_env"
    ctx.update_env_name(env_name)

    # ── 8. 生成回归框架 YAML ──
    reg_yaml_path = _generate_regression_yaml(
        output_dir=output_dir, yaml_dir=uvm_yaml_archive,
        module_name=module_name, env_name=env_name,
        top_module=dut_module, agents=agent_names,
        filelist_name="filelist.f"
    )
    yaml_files.append(str(reg_yaml_path))
    print(f"  [find_yaml] Generated regression.yaml", flush=True)

    return json.dumps({
        "status": "ok",
        "module_name": module_name,
        "yaml_files": yaml_files,
        "yaml_count": len(yaml_files),
        "env_name": f"{module_name}_env",
    }, ensure_ascii=False)


def _generate_regression_yaml(output_dir: Path, yaml_dir: Path,
                               module_name: str, env_name: str,
                               top_module: str,
                               agents: list, filelist_name: str = "filelist.f") -> Path:
    """生成回归框架可用的 regression.yaml（builds + tests）。

    从 spec.json 提取 test_points 作为测试用例列表。
    """
    reg_dir = output_dir / "inputs" / "yaml"
    reg_dir.mkdir(parents=True, exist_ok=True)
    reg_path = reg_dir / "regression.yaml"

    fl_dir = output_dir / "inputs" / "filelists"
    fl_path = fl_dir / filelist_name

    # 从 spec.json 提取测试点
    test_points = []
    spec_path = output_dir / "spec.json"
    if spec_path.exists():
        try:
            spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
            test_points = spec_data.get("test_points", []) or []
        except Exception:
            pass

    # 构建测试列表
    test_lines = []
    if test_points:
        for i, tp in enumerate(test_points):
            tid = tp.get("id", f"test_{i}")
            tname = tid.lower().replace("-", "_")
            desc = tp.get("description", tp.get("feature", ""))
            priority = tp.get("priority", "P1")
            test_lines.append(f"  - name: {tname}")
            test_lines.append(f"    build: build_{module_name}")
            test_lines.append(f"    count: 1")
            test_lines.append(f"    run_opts:")
            test_lines.append(f'      - "+UVM_TESTNAME={env_name}_base_test"')
            test_lines.append(f"    expect:")
            test_lines.append(f"      errors: 0")
            test_lines.append(f"    tags: [\"{priority.lower()}\", \"{tid}\"]")
            if desc:
                test_lines.append(f"    desc: \"{desc[:80]}\"")
            test_lines.append("")
    else:
        # 回退：基于 agent 生成烟雾测试
        for ag in agents:
            test_lines.append(f"  - name: test_{ag}_loopback")
            test_lines.append(f"    build: build_{module_name}")
            test_lines.append(f"    count: 1")
            test_lines.append(f"    run_opts:")
            test_lines.append(f'      - "+UVM_TESTNAME={ag}_loopback_test"')
            test_lines.append(f"    expect:")
            test_lines.append(f"      errors: 0")
            test_lines.append(f"    tags: [\"smoke\", \"loopback\"]")
            test_lines.append("")
        test_lines.append(f"  - name: test_{module_name}_base")
        test_lines.append(f"    build: build_{module_name}")
        test_lines.append(f"    count: 1")
        test_lines.append(f"    run_opts:")
        test_lines.append(f'      - "+UVM_TESTNAME={env_name}_base_test"')
        test_lines.append(f"    expect:")
        test_lines.append(f"      errors: 0")
        test_lines.append(f"    tags: [\"smoke\"]")
        test_lines.append("")

    tests_section = "\n".join(test_lines)

    # 收集所有 RTL 文件路径
    rtl_files = []
    rtl_dir = output_dir / "rtl"
    if rtl_dir.exists():
        rtl_files = [str(p.resolve()).replace("\\", "/") for p in sorted(rtl_dir.glob("*.sv"))]

    filelist_ref = str(fl_path.resolve()).replace("\\", "/") if fl_path.exists() else ""

    yaml_content = f"""# 回归测试配置 — 由 find_spec_yaml 自动生成
# 用法: python regression.py --config {reg_path.as_posix()} --action all --mode local

global_vars:
  SEED: 12345
  WAVES: 0

settings:
  default_build: build_{module_name}
  default_count: 1
  build_cache: true
  simulators:
    questa:
      compile: "vlog -work {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')} -sv -mfcu -f {filelist_ref}"
      run: "vsim -c -onfinish stop -work {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')} {top_module}_bench_tb_top +UVM_TESTNAME=${{UVM_TESTNAME}} -do 'log -r /*; run -all; quit -f'"

builds:
  - name: build_{module_name}
    compile_opts: ["-sv", "-mfcu"]
    files:
{chr(10).join('      - ' + f for f in rtl_files) if rtl_files else '      - ' + filelist_ref}

tests:
{tests_section}
"""

    reg_path.write_text(yaml_content, encoding="utf-8", errors="replace")
    return reg_path


def _name_match_rtl(target: str, rtl_dir: Path) -> str | None:
    """在 RTL 目录中查找匹配 target 的模块名，返回实际模块名"""
    if not rtl_dir.exists():
        return None
    for sv in rtl_dir.glob("*.sv"):
        try:
            text = sv.read_text(encoding="utf-8", errors="replace")[:500]
            m = re.search(r'module\s+(\w+)', text)
            if m:
                mn = m.group(1)
                if mn.lower() == target.lower():
                    return mn
        except Exception:
            continue
    return None


if __name__ == "__main__":
    spec = sys.argv[1] if len(sys.argv) > 1 else "module dut(input clk);"
    print(run(spec))
