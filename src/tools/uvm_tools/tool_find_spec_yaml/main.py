"""
Tool: find_spec_yaml — 从 spec 文本查找已有 YAML 或构造新的 YAML

用法:
    python -m src.tools.uvm_tools.tool_find_spec_yaml.main "module alu(...);"
    # 或编程调用:
    from src.tools.uvm_tools.tool_find_spec_yaml.main import run
    result = run(spec_text)
"""
import sys, json, re
import builtins
from pathlib import Path
import shutil as _shutil
import yaml as _yaml


def print(*args, **kwargs):
    """本模块诊断日志默认写 stderr（stdout 保留给业务输出/--json，不被污染）。"""
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


from src.tools.lib.uvm_context import ctx
from src.tools.uvm_tools.tool_uvm.gen_uvm import TEMPLATES_DIR


def _load_spec(output_dir: Path) -> dict | None:
    """尝试从输出目录加载 spec.json（由 testbench_orchestrator 保存）"""
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


def _spec_iface_to_port(iface: dict) -> dict:
    """spec.interfaces 项 → 端口 dict（去掉 [N:0] 后缀，方向小写，宽度取 data_width）。"""
    name = str(iface.get("name", "")).split("[")[0].strip()
    direction = str(iface.get("direction", "input") or "input").lower()
    try:
        width = int(iface.get("data_width", 1) or 1)
    except (TypeError, ValueError):
        width = 1
    return {"name": name, "direction": direction, "width": width}


def _classify_protocol_by_name(name: str) -> str:
    """按命名约定推断 protocol（确定性兜底，LLM 不可用时用）。

    规则与 LLM 分类 prompt 保持一致，保证两条路径行为可复现。
    """
    n = name.lower()
    if "clk" in n or "clock" in n:
        return "clock"
    if "rst" in n or "reset" in n or "preset" in n:
        return "reset"
    if n in ("tx", "rx") or "uart" in n:
        return "uart"
    if n in ("irq", "intr") or "irq" in n or "interrupt" in n or "intr" in n:
        return "intr"
    if n in ("paddr", "pwdata", "prdata", "pwrite", "psel", "penable",
             "pready", "pslverr", "pselx"):
        return "apb"
    # AXI 前缀：aw/w/b/ar/r + 后续字母（awaddr/wdata/bresp/araddr/rdata）
    if re.match(r'^(aw|w|b|ar|r)[a-z]', n) and len(n) > 1:
        return "axi"
    return "generic"


def _llm_classify_protocols(names: list) -> dict:
    """LLM 按信号名分类 protocol，返回 {name: protocol}；失败返回 {}。"""
    if not names:
        return {}
    try:
        from src.tools.lib.llm_custom_logic import _call_llm_raw
    except Exception:
        return {}
    prompt = (
        "你是 IC 验证工程师。把以下 DUT 端口按协议分类，只从这些类别选："
        "apb, uart, intr, axi, clock, reset, generic。\n"
        "规则：clk/clock→clock；rst/reset/preset→reset；tx/rx→uart；"
        "irq/interrupt/intr→intr；paddr/pwdata/prdata/pwrite/psel/penable→apb；"
        "aw/w/b/ar/r 前缀→axi；其余→generic。\n"
        f"端口列表：{json.dumps(names, ensure_ascii=False)}\n"
        "只输出 JSON 对象 {\"端口名\": \"protocol\", ...}，不要任何解释或代码块。"
    )
    try:
        raw = (_call_llm_raw(prompt, "", "") or "").strip()
    except Exception:
        return {}
    if not raw:
        return {}
    raw = re.sub(r'^```(?:json)?\s*', '', raw)
    raw = re.sub(r'\s*```$', '', raw)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    if not m:
        return {}
    try:
        result = json.loads(m.group(0))
    except Exception:
        return {}
    if isinstance(result, dict):
        return {str(k): str(v).lower() for k, v in result.items()}
    return {}


def _group_agents_by_protocol(spec: dict, rtl_data: dict, module_name: str) -> list:
    """按协议边界分组 agents（优先 spec.protocol，缺失时 LLM/命名约定分类）。

    返回 [(agent_dict, iface_dict), ...]，空列表表示无法分组（交由方向兜底）。
    """
    ports = []  # [{name, direction, width, protocol}]
    if spec and isinstance(spec, dict) and spec.get("interfaces"):
        for i in spec["interfaces"]:
            if not isinstance(i, dict):
                continue
            p = _spec_iface_to_port(i)
            if not p["name"]:
                continue
            p["protocol"] = str(i.get("protocol", "") or "").strip().lower()
            ports.append(p)
    elif rtl_data and rtl_data.get("ports"):
        for p in rtl_data["ports"]:
            ports.append({
                "name": p["name"],
                "direction": str(p.get("direction", "input") or "input").lower(),
                "width": int(p.get("width", 1) or 1),
                "protocol": "",
            })

    if not ports:
        return []

    # 补全缺失 protocol：LLM 分类 → 命名约定兜底
    missing = [p for p in ports if not p["protocol"] or p["protocol"] == "generic"]
    if missing:
        llm_map = _llm_classify_protocols([p["name"] for p in missing])
        for p in missing:
            p["protocol"] = (llm_map.get(p["name"])
                             or _classify_protocol_by_name(p["name"])
                             or "generic")

    # 按 protocol 分组（clock/reset 是 clocking，不单独成 agent）
    groups = {}
    for p in ports:
        proto = p["protocol"] or "generic"
        if proto in ("clock", "reset", "clk", "rst"):
            continue
        groups.setdefault(proto, []).append(p)

    generic_ports = groups.pop("generic", [])
    if generic_ports:
        print(f"  [find_yaml] 警告: {len(generic_ports)} 个端口无法分类协议，"
              f"将走方向兜底: {[p['name'] for p in generic_ports]}", flush=True)

    if not groups:
        return []

    print(f"  [find_yaml] 按协议分组: "
          f"{', '.join(f'{k}({len(v)})' for k, v in sorted(groups.items()))}", flush=True)

    agents_spec = []
    for proto, grp in groups.items():
        # 有 DUT input 端口（需驱动）→ ACTIVE；纯 DUT output（仅监控）→ PASSIVE
        has_drive = any(p["direction"] == "input" for p in grp)
        agent_type = "UVM_ACTIVE" if has_drive else "UVM_PASSIVE"
        agents_spec.append((
            {"name": proto, "type": agent_type, "ports": grp},
            {"name": proto},
        ))
    return agents_spec


def _gen_env_yaml(module_name: str, agent_names: list, agents_spec: list,
                  clock_port: str, reset_port: str, registers: list = None) -> str:
    """生成 env.yaml：agents + 按协议自动带 predictor/scoreboard 闭环。

    只生成 environment.agents（含 env 级 is_active）。原先还会生成
    predictors + 依赖它的 scoreboards，但 predictors 已下线（见文末注释），
    故此处不再生成任何参考模型/比对组件。
    """
    # 激活模式落在 env 级 agents[].is_active（interface 级不再携带）：
    #   有 DUT input 端口（需驱动）→ active；纯 output（仅监控）→ passive。
    #   消费路径：_normalize_agents_list → AgentModel.active → 模板 agents[].is_active
    active_by_name = {}
    for ag, _iface in agents_spec:
        if ag.get("name"):
            active_by_name[ag["name"]] = (
                str(ag.get("type", "")).upper() in ("UVM_ACTIVE", "ACTIVE"))

    agent_lines = []
    for ag_name in agent_names:
        is_active = "true" if active_by_name.get(ag_name, True) else "false"
        agent_lines.append(f"    {ag_name}:\n      interface: {ag_name}\n"
                           f"      clock: {clock_port}\n      reset: {reset_port}\n"
                           f"      is_active: {is_active}")

    lines = [f"environment:\n  name: {module_name}_env\n  agents:\n" + "\n".join(agent_lines)]

    # 注：原先这里还会生成 predictors + 依赖它的 scoreboards。predictors 已下线
    # （schema 不再接受该字段，且 env 模板从不例化它——声明了只是个孤立文件），
    # 故一并移除。scoreboards 也必须一起去掉：它的 expected_from 唯一来源就是
    # predictor，留着会得到一个「永远收不到 expected」的空 scoreboard —— 它不会
    # 报错，只会永远不报 mismatch，比没有更危险。
    # 需要参考模型时走 analysis_components（见 examples/apb/apb_env.yaml）。

    return "\n".join(lines) + "\n"


def _gen_uart_serial_logic() -> str:
    """UART 帧串行化（driver 侧，8N1 LSB first）：req.data → rx 位流。

    返回 custom_drive_logic 内容（无前导缩进，模板用 indent(4) 注入）。
    波特率分频默认 10416（9600 @ 100MHz）；跨 agent 配置（APB 写 baud_div）暂不接。
    """
    return (
        "// UART 帧串行化 (8N1, LSB first)：req.data → rx 位流\n"
        "begin\n"
        "  int unsigned baud_div = 10416;   // 9600 @ 100MHz（默认，后续从 APB 配置）\n"
        "  vif.cb.rx <= 1'b0;               // 起始位\n"
        "  repeat (baud_div) @(vif.cb);\n"
        "  for (int i = 0; i < 8; i++) begin\n"
        "    vif.cb.rx <= req.data[i];      // 8 数据位\n"
        "    repeat (baud_div) @(vif.cb);\n"
        "  end\n"
        "  vif.cb.rx <= 1'b1;               // 停止位\n"
        "  repeat (baud_div) @(vif.cb);\n"
        "end"
    )


def _gen_uart_deserialize_logic() -> str:
    """UART 帧反串行化（monitor 侧，8N1 LSB first）：tx 位流 → data 字节。

    返回 custom_collect_logic 内容（无前导缩进，模板用 indent(4) 注入）。
    task 级：跨多拍采样（等起始位 → 逐位采样）。
    """
    return (
        "// UART 帧反串行化：tx 位流 → data 字节 (8N1, LSB first)\n"
        "begin\n"
        "  int unsigned baud_div = 10416;   // 9600 @ 100MHz\n"
        "  bit [7:0] byte_val;\n"
        "  @(negedge vif.tx);                        // 起始位下降沿\n"
        "  repeat (baud_div + baud_div / 2) @(vif.cb);  // 到数据位 0 中点\n"
        "  for (int i = 0; i < 8; i++) begin\n"
        "    byte_val[i] = vif.tx;                   // 采样\n"
        "    repeat (baud_div) @(vif.cb);            // 到下一数据位中点\n"
        "  end\n"
        "  item.data = byte_val;\n"
        "end"
    )


def _generate_uart_yaml(agent: dict, interface: dict, module_name: str) -> str:
    """生成 UART 帧级 agent YAML：事务 = data 字节 + irq，driver 串行化 rx。

    tx/rx 是物理串行线（端口），不进事务；tx 反串行化（monitor 侧）需
    task 级采样，当前 monitor 是 function 采样，暂不接（见 _gen_uart_serial_logic 注释）。
    """
    ag_name = agent.get("name", f"{module_name}_agent")
    ports = agent.get("ports", []) or []

    detected_clock = detected_reset = None
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

    all_interface_ports = [
        {"name": clock_name, "direction": "input", "width": 1},
        {"name": reset_name, "direction": "input", "width": 1},
    ]
    for p in data_ports:
        d = p.get("direction", p.get("dir", "input"))
        rev = "output" if d == "input" else "input"
        all_interface_ports.append({"name": p["name"], "direction": rev,
                                     "width": p.get("width", 1)})

    lines = []
    lines.append("interfaces:")
    lines.append("  name: " + ag_name)
    lines.append("  clock: " + clock_name)
    lines.append("  reset: " + reset_name)
    lines.append("  parameters:")
    lines.append("    - { name: BAUD_DIV, type: int, value: '10416' }")
    lines.append("  ports:")
    for p in all_interface_ports:
        lines.append("    - { name: " + p['name'] + ", dir: " + p['direction']
                     + ", width: " + str(p.get('width', 1)) + " }")
    lines.append("  transaction_vars:")
    lines.append("    - { name: data, type: \"bit [7:0]\", iscompare: 'True', isrand: 'True' }")
    lines.append("  custom_drive_logic: |")
    for ln in _gen_uart_serial_logic().split("\n"):
        lines.append("    " + ln)
    lines.append("  custom_collect_logic: |")
    for ln in _gen_uart_deserialize_logic().split("\n"):
        lines.append("    " + ln)
    return "\n".join(lines) + "\n"


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
    # 数据端口方向反转：DUT input → interface output（TB/driver 驱动）；DUT output → interface input（TB/monitor 采样）
    for p in data_ports:
        d = p.get("direction", p.get("dir", "input"))
        rev = "output" if d == "input" else "input"
        all_interface_ports.append({"name": p["name"], "direction": rev,
                                     "width": p.get("width", 1)})

    trans_vars = agent.get("transaction_vars", [])
    if not trans_vars:
        trans_vars = []
        for p in data_ports:
            w = p.get("width", 1)
            ttype = "bit [" + str(w - 1) + ":0]" if w > 1 else "bit"
            trans_vars.append({"name": p["name"], "type": ttype,
                               "iscompare": "True", "isrand": "True"})

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

    # 从 RTL 端口识别 clock/reset（供 agent/bench 一致使用，避免 output agent 默认 rst 与 rst_n 不一致）
    rtl_clock_port = None
    rtl_reset_port = None
    if rtl_data and rtl_data.get("ports"):
        rtl_clock_port = next((p["name"] for p in rtl_data["ports"] if _is_clock_port(p["name"])), None)
        rtl_reset_port = next((p["name"] for p in rtl_data["ports"] if _is_reset_port(p["name"])), None)

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
            # 按协议边界分组（spec.protocol 优先；缺失时 LLM/命名约定分类）
            agents_spec = _group_agents_by_protocol(spec, rtl_data, module_name)

        if not agents_spec:
            # 回退：从 RTL 端口构造 in/out agents（无 protocol 信息时的最后手段，带告警）
            if rtl_data and rtl_data.get("ports"):
                print("  [find_yaml] 警告: 无 protocol 信息，退化为方向拆分 _in/_out（需人工 review）",
                      flush=True)
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
                )
                yaml_path = uvm_yaml_archive / f"{agent_name}.yaml"
                yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
                yaml_files.append(str(yaml_path))
            print(f"  [find_yaml] Using generic data/valid/ready template (no spec/RTL data)", flush=True)

        # ── 5. 从 spec/RTL 数据生成 agent YAML ──
        agent_names = []
        clock_port = rtl_clock_port or "clk"
        reset_port = rtl_reset_port or "rst"
        for ag, iface in agents_spec:
            ag_name = ag.get("name", f"{module_name}_agent")
            agent_names.append(ag_name)
            # 注入一致的 clock/reset：agent 自身 > iface > RTL 检测值 > 默认
            ag["clock"] = ag.get("clock") or iface.get("clock") or clock_port
            ag["reset"] = ag.get("reset") or iface.get("reset") or reset_port
            clock_port = ag["clock"]
            reset_port = ag["reset"]

            if ag_name.lower() == "uart":
                yaml_str = _generate_uart_yaml(ag, iface, module_name)
            else:
                yaml_str = _generate_interface_yaml(ag, iface, module_name)
            yaml_path = uvm_yaml_archive / f"{ag_name}.yaml"
            yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
            yaml_files.append(str(yaml_path))
            print(f"  [find_yaml] Generated {ag_name}.yaml (from spec interfaces)" if spec else
                  f"  [find_yaml] Generated {ag_name}.yaml (from RTL ports)", flush=True)

        # ── 6. 生成 env YAML（agents + predictors + scoreboards 闭环）──
        registers = (spec or {}).get("registers", []) if isinstance(spec, dict) else []
        env_str = _gen_env_yaml(module_name, agent_names, agents_spec,
                                clock_port, reset_port, registers)
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

        # 从实际端口重新识别 clock/reset（覆盖 agent 循环里的默认值，修复 reset 误设为 clk）
        _clk = next((p["name"] for p in all_ports if _is_clock_port(p["name"])), None)
        _rst = next((p["name"] for p in all_ports if _is_reset_port(p["name"])), None)
        if _clk:
            clock_port = _clk
        if _rst:
            reset_port = _rst

        # Wire declarations（排除 clock/reset，它们已在 bench 模板中声明为 reg）
        wire_lines = []
        for p in all_ports:
            if _is_clock_port(p["name"]) or _is_reset_port(p["name"]):
                continue
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

        # DUT parameters（从 RTL 实际 parameter 列表，不从端口宽度推断）
        dut_params_lines = []
        if rtl_data and rtl_data.get("params"):
            for param in rtl_data["params"]:
                dut_params_lines.append(
                    f"      - {{ name: {param['name']}, value: {param['value']} }}"
                )

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
      - {{ name: {reset_port}, init: 0, release_delay: 10 }}
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
        # ── 参考模型接入（黄金模型命中时）：tb_top 真实实例化 DUT vs 参考模型比对 ──
        # 修复历史缺口：ref_model_enabled 默认 false → "参考模型比对"从未真正发生。
        # 现在按 spec 接口匹配黄金库（apb_slave 等），生成端口映射 + 比对输出。
        try:
            from src.tools.lib.golden_library import build_ref_model_config
            _norm_ifaces = []
            for _iface in (spec.get("interfaces", []) if isinstance(spec, dict) else []) or []:
                if not isinstance(_iface, dict):
                    continue
                if _iface.get("signals"):
                    # 嵌套格式 {signals: {sig: {direction, width}}}
                    for _sig, _s in _iface["signals"].items():
                        _norm_ifaces.append({
                            "name": _sig,
                            "direction": (_s or {}).get("direction", "input"),
                            "protocol": _iface.get("protocol", ""),
                        })
                else:
                    # 扁平格式 {name, direction, protocol}
                    _norm_ifaces.append({
                        "name": _iface.get("name", ""),
                        "direction": _iface.get("direction", "input"),
                        "protocol": _iface.get("protocol", ""),
                    })
            _ref_cfg = build_ref_model_config(
                module_name, _norm_ifaces,
                (spec.get("registers") if isinstance(spec, dict) else None) or [])
            if _ref_cfg:
                _g = _ref_cfg.get("golden", {})
                _g_str = f"{{ ip: {_g.get('ip', '')}"
                if _g.get("version"):
                    _g_str += f", version: {_g['version']}"
                if _g.get("parts"):
                    _g_str += f", parts: [{', '.join(_g['parts'])}]"
                _g_str += " }"
                _ref_lines = [
                    "  ref_model:",
                    f"    enabled: {str(_ref_cfg['enabled']).lower()}",
                    f"    module: {_ref_cfg['module']}",
                    f"    golden: {_g_str}",
                    "    port_map:",
                ]
                for _m in _ref_cfg["port_map"]:
                    _ref_lines.append(
                        f"      - {{ ref_port: {_m['ref_port']}, dut_port: {_m['dut_port']} }}")
                _ref_lines.append(
                    f"    compare_outputs: [{', '.join(_ref_cfg['compare_outputs'])}]")
                bench_str += "\n".join(_ref_lines) + "\n"
                print(f"  [find_yaml] 参考模型接入: {_ref_cfg['module']} "
                      f"({_ref_cfg['golden']['ip']} {_ref_cfg['golden']['version']})")
        except Exception as e:
            print(f"  [find_yaml] 参考模型接入失败: {e}")

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


def _is_agent_active(output_dir: Path, agent_name: str) -> bool:
    """检查 agent 是否 active（被动 agent 无 driver，loopback 自闭环无意义）。

    激活模式由 env 级 agents[].is_active 决定（interface 级不再携带）。
    """
    yp = output_dir / "inputs" / "yaml" / "uvm" / "env.yaml"
    if not yp.exists():
        return True
    try:
        data = _yaml.safe_load(yp.read_text(encoding="utf-8", errors="replace")) or {}
        agents = (data.get("environment") or {}).get("agents") or {}
        if isinstance(agents, dict):
            entry = agents.get(agent_name)
        else:
            entry = next((a for a in agents
                          if isinstance(a, dict) and a.get("name") == agent_name), None)
        if isinstance(entry, dict) and entry.get("is_active") is not None:
            return str(entry["is_active"]).strip().lower() in ("true", "1", "yes", "on")
    except Exception:
        return True
    return True


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

    # filelist 引用固定路径（filelist.f 的实际生成在回归执行时由 L1.run_regression 完成，
    # 因为 find_spec_yaml 运行于 jinja_render 之前，agents/env/bench 尚未生成）
    fl_dir = output_dir / "inputs" / "filelists"
    fl_path = fl_dir / filelist_name
    filelist_ref = str(fl_path.resolve()).replace("\\", "/")

    # 从 spec.json 提取测试点
    test_points = []
    spec_path = output_dir / "spec.json"
    if spec_path.exists():
        try:
            spec_data = json.loads(spec_path.read_text(encoding="utf-8"))
            test_points = spec_data.get("test_points", []) or []
        except Exception:
            pass

    # 从 case 库（testcase_registry）读用例 —— case 库是"用例真相源"，regression.yaml 与它对齐
    # 注意：case 库是跨 run 共享的，在项目根 .signoffai/（而非 run 目录 .signoffai/）
    cases = []
    try:
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry
        case_reg = TestcaseRegistry()
        cases = case_reg.get_priority_order(stage=0, limit=50)
        # 回归模式开关：增量（默认，只跑未 passed）/ 全量（跑所有用例）
        try:
            from config.settings import Settings
            incremental = Settings.get_instance().verification.incremental_regression
        except Exception:
            incremental = True
        if incremental:
            cases = [c for c in cases if c.get("status") in ("planned", "generated")]
        case_reg.close()
    except Exception:
        cases = []

    # 构建测试列表
    test_lines = []
    if cases:
        # case 库对齐：每个 case 一个 test（run_opts 用 random_test，case 名用于追踪 + 回写状态）
        for c in cases:
            cname = c.get("name", "case")
            priority = c.get("priority", "P1")
            scenario = c.get("scenario", "")
            test_lines.append(f"  - name: {cname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.append(f"    count: 1")
            test_lines.append(f"    run_opts:")
            test_lines.append(f'      - "+UVM_TESTNAME={env_name}_random_test"')
            test_lines.append(f"    expect:")
            test_lines.append(f"      errors: 0")
            test_lines.append(f"    tags: [\"{priority.lower()}\", \"{scenario}\"]")
            test_lines.append("")
    elif test_points:
        for i, tp in enumerate(test_points):
            tid = tp.get("id", f"test_{i}")
            tname = tid.lower().replace("-", "_")
            desc = tp.get("description", tp.get("feature", ""))
            priority = tp.get("priority", "P1")
            test_lines.append(f"  - name: {tname}")
            test_lines.append(f"    build: build_{module_name}_dut")
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
        # 回退：环境级测试（base/directed/random）—— env/tests 里真正生成的 test 类
        for _tname in (f"{env_name}_base_test", f"{env_name}_directed_test", f"{env_name}_random_test"):
            test_lines.append(f"  - name: test_{_tname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.append(f"    count: 1")
            test_lines.append(f"    run_opts:")
            test_lines.append(f'      - "+UVM_TESTNAME={_tname}"')
            test_lines.append(f"    expect:")
            test_lines.append(f"      errors: 0")
            test_lines.append(f"    tags: [\"smoke\"]")
            test_lines.append("")

    # ── loopback 测试（每个 active agent 一个，独立 build + 独立顶层 {ag}_loopback_tb）──
    # 同时把 loopback 用例注册进 case 库（用例真相源），跨 run 沉淀。
    for ag in agents:
        if not _is_agent_active(output_dir, ag):
            continue
        try:
            from src.layers.l4_memory.testcase_registry import TestcaseRegistry
            _cr = TestcaseRegistry()
            _cr.register(f"test_{ag}_loopback", purpose="smoke",
                         scenario="loopback", priority="P0")
            _cr.close()
        except Exception:
            pass
        test_lines.append(f"  - name: test_{ag}_loopback")
        test_lines.append(f"    build: build_{module_name}_{ag}_loopback")
        test_lines.append(f"    count: 1")
        test_lines.append(f"    run_opts:")
        test_lines.append(f'      - "+UVM_TESTNAME={ag}_loopback_test"')
        test_lines.append(f"    expect:")
        test_lines.append(f"      errors: 0")
        test_lines.append(f"    tags: [\"smoke\", \"loopback\"]")
        test_lines.append("")

    tests_section = "\n".join(test_lines)

    # 构建 builds 段：DUT build（top={module}_bench_tb_top）+ per-agent loopback build（top={ag}_loopback_tb）。
    # 每个 build 指定自己的 top（顶层模块）和 files（filelist），shell 生成器按 {top}/{files} 填充。
    builds_lines = [
        f"  - name: build_{module_name}_dut",
        f"    simulator: questa",
        f"    top: {top_module}_bench_tb_top",
        f'    compile_opts: ["-sv", "-mfcu"]',
        f"    files:",
        f"      - {filelist_ref}",   # env + DUT 全在 filelist.f
    ]
    for ag in agents:
        if not _is_agent_active(output_dir, ag):
            continue
        lb_ref = str((fl_dir / f"filelist_{ag}_lb.f").resolve()).replace("\\", "/")
        builds_lines.append(f"  - name: build_{module_name}_{ag}_loopback")
        builds_lines.append(f"    simulator: questa")
        builds_lines.append(f"    top: {ag}_loopback_tb")
        builds_lines.append(f'    compile_opts: ["-sv", "-mfcu"]')
        builds_lines.append(f"    files:")
        builds_lines.append(f"      - {lb_ref}")
    builds_section = "\n".join(builds_lines)

    from config.settings import questa_home
    _questa_root = questa_home().replace("\\", "/")

    yaml_content = f"""# 回归测试配置 — 由 find_spec_yaml 自动生成
# 用法: python regression.py --config {reg_path.as_posix()} --action all --mode local

global_vars:
  SEED: 12345
  WAVES: 0

settings:
  default_build: build_{module_name}_dut
  default_count: 1
  default_simulator: questa
  build_cache: False
  simulators:
    questa:
      compile: "vlog -work {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')} -sv -mfcu +incdir+{_questa_root}/verilog_src/uvm-1.2/src {_questa_root}/verilog_src/uvm-1.2/src/uvm_pkg.sv -f {{files}}"
      run: "vsim -c -sv_lib {_questa_root}/uvm-1.2/win64/uvm_dpi -onfinish stop -work {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')} {{top}} {{run_opts}} -do 'log -r /*; run -all; quit -f'"

builds:
{builds_section}

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
