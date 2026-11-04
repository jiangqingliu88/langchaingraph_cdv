"""
Tool: find_spec_yaml — 从 spec 文本查找已有 YAML 或构造新的 YAML

用法:
    python -m src.tools.generation.uvm_tools.tool_find_spec_yaml.main "module alu(...);"
    # 或编程调用:
    from src.tools.generation.uvm_tools.tool_find_spec_yaml.main import run
    result = run(spec_text)
"""
import sys, json, re
import builtins
from pathlib import Path
from typing import Any, Dict, List
import shutil as _shutil
import yaml as _yaml


def print(*args, **kwargs):
    """本模块诊断日志默认写 stderr（stdout 保留给业务输出/--json，不被污染）。"""
    kwargs.setdefault("file", sys.stderr)
    builtins.print(*args, **kwargs)


# 回归产物已拆到 `generators/regression_gen.py`；这里保留同名 re-export，
# 旧调用方/测试仍从 main 取。
from .generators.regression_gen import (  # noqa: E402,F401
    _dedupe_loopback_tests, _generate_regression_yaml, _is_agent_active,
    _seed_lines, _seed_offset, _seed_plan, _tp_regression_lines,
)

from src.tools.common.lib.uvm_context import ctx
from src.tools.generation.uvm_tools.generation.constants import TEMPLATES_DIR


from .helpers import (  # noqa: E402
    _copy_project_util_comp,
    _load_spec,
    _strip_comments,
    _match_paren,
    _width_of,
    _port_list_span,
    _parse_rtl_module,
    _yaml_escape,
    _indent,
    _is_clock_port,
    _is_reset_port,
    _spec_iface_to_port,
    _classify_protocol_by_name,
    _llm_classify_protocols,
    _group_agents_by_protocol,
    _iface_name_of,
    _spec_agent_of,
    _is_active_type,
    _ref_mirror_gate,
    _gen_env_yaml,
    _gen_uart_serial_logic,
    _gen_uart_deserialize_logic,
    _generate_uart_yaml,
    _generate_interface_yaml,
    _name_match_rtl,
    _generate_models_yaml,
    _registry_model,
    _util_component_yaml,
    _casemodel_test_lines,
)

def run(spec_text: str) -> str:
    """查找已有 YAML 或从 spec 构造 YAML，复制到 output/inputs/yaml/uvm/。

    返回 JSON: {status, yaml_files, module_name, agent_names}
    """
    yaml_dir = (Path(__file__).resolve().parent.parent / "tool_uvm")
    output_dir = Path(ctx.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── 1. 确定模块名 ──
    #
    # **标识符必须是 ASCII**（`[A-Za-z_][A-Za-z0-9_]*`），不能图省事写 `\w+`：
    # Python 的 `\w` **匹配中文**，于是散文里一句"端口来自 module 声明"会被下面
    # 那条回退式当成一次模块声明，模块名解成 `声明` —— 整套产物落成
    # `声明_env_*.sv` / `声明_in_agent/`，而**不报任何错**。实测踩过：`--rtl`
    # 模式跑一遍，env 名就是 spec 里那句中文注记的第一个词。
    # SV 的模块名本来就只能是 ASCII，收紧是**更对**而不是更严。
    _ident = r'[A-Za-z_][A-Za-z0-9_]*'
    module_match = re.search(rf'module:\s*({_ident})', spec_text, re.IGNORECASE)
    if not module_match:
        module_match = re.search(rf'(?:#|module\s+)\s*({_ident})', spec_text,
                                 re.IGNORECASE)
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
    # **不清空共享目录**：只删本工具上一轮自己生成的文件（manifest 记录）。
    # 旧实现 `glob("*.yaml").unlink()` 会把更早阶段写进来的东西一起删掉 ——
    # 那是"文档约定"，不是机制；拿不到 manifest 就一个都不删（宁可留旧文件，
    # 也不误删别人的产物）。
    from .ownership import clean_owned_yaml, record_owned_yaml

    clean_owned_yaml(uvm_yaml_archive)
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

        #: 回退路径**自己写过** YAML 的 agent —— 主循环别再生成一遍把内容覆盖掉
        prewritten: set = set()

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
                # **也要登记进 agents_spec**：此前这里只写文件、不登记，于是
                # agent_names 是空的 —— env.yaml 写出 `agents:` 空值（schema 判
                # "None 不是 array"）、bench 的 harness 一个 interface 都没有。
                # 文件已经写过了，所以记进 prewritten，免得主循环再生成一遍覆盖掉。
                agents_spec.append((
                    {"name": agent_name,
                     "type": "UVM_ACTIVE" if direction == "in" else "UVM_PASSIVE",
                     "ports": [{"name": n} for n in ("clk", "rst", "data", "valid", "ready")]},
                    {"name": agent_name},
                ))
                prewritten.add(agent_name)
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

            if ag_name in prewritten:          # 回退路径自己写过，别覆盖
                continue
            if ag_name.lower() == "uart":
                yaml_str = _generate_uart_yaml(ag, iface, module_name)
            else:
                yaml_str = _generate_interface_yaml(ag, iface, module_name)
            yaml_path = uvm_yaml_archive / f"{ag_name}.yaml"
            yaml_path.write_text(yaml_str, encoding="utf-8", errors="replace")
            yaml_files.append(str(yaml_path))
            print(f"  [find_yaml] Generated {ag_name}.yaml (from spec interfaces)" if spec else
                  f"  [find_yaml] Generated {ag_name}.yaml (from RTL ports)", flush=True)

        # ── 6. 生成 env YAML（agents + 参考模型比对闭环）──
        registers = (spec or {}).get("registers", []) if isinstance(spec, dict) else []
        ifaces = (spec or {}).get("interfaces", []) if isinstance(spec, dict) else []
        # 工程级 pred 装配单（SV 参考模型）优先：specs/<module>/util_comp.yaml
        # 或 config/uvm/<module>_util_comp.yaml。它会在 _gen_env_yaml 中被读取、
        # 校验端口类型，并写回本 run 的 util_comp.yaml。
        _util_src = _copy_project_util_comp(uvm_yaml_archive, module_name)
        if _util_src:
            print(f"  [find_yaml] util_comp.yaml 来自 {_util_src}", flush=True)
        env_str, util_str = _gen_env_yaml(
            module_name, agent_names, agents_spec,
            clock_port, reset_port, registers, ifaces,
            uvm_yaml_dir=uvm_yaml_archive, with_util=True)
        # ── casemodel 产的属性测试 → `environment.tests` ──
        # `casemodel.yaml` 由 front 从 spec 跑出来（测试点分解 + 维度组合），
        # `run_uvm_tests` 把每个维度取值摊平成一条 UVM_TEST。**接在这里**：
        # 缺这一段，casemodel 产的东西就永远停在 casemodel.yaml 里 ——
        # 生成不出 test 类，也进不了回归（实测：env/tests/ 只有手写模板那三个）。
        _cm = _casemodel_test_lines(output_dir)
        if _cm:
            env_str = env_str.replace("  clk_rst_vip:",
                                      chr(10).join(_cm) + chr(10) + "  clk_rst_vip:", 1)
            print(f"  [find_yaml] env.yaml 注入 {len(_cm)} 行 casemodel tests", flush=True)

        # pred 装配单**单独一份** `util_comp.yaml`；env.yaml 只引用它。
        # 双向 agent 但既没有 verified 模型、也没有用户 pred 时，
        # `_gen_env_yaml` 已抛错（不写 env），这里不会走到。
        util_path = uvm_yaml_archive / "util_comp.yaml"
        util_path.write_text(util_str or "util_components: []\n",
                             encoding="utf-8", errors="replace")
        yaml_files.append(str(util_path))

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

        # ── 接口实例清单（**bind 式 harness 已退役**）──
        #
        # 形状照着 `examples/apb/apb_bench.yaml`：tb_top 直接例化每个接口，再把 DUT
        # 的**同名端口**接上去（`.paddr(apb_if_inst.paddr)`），并把接口广播给 agent。
        # 三个字段挨着消费侧对：
        #   · `dut_module` + `dut_instance` —— tb_top 靠它例化 DUT
        #     （`harness.bind_to` 是退役的写法，tb_top 只在没有 `dut_module` 时才回退到它）
        #   · `interfaces[].type_name` = `{agent}_if` —— interface 模板生成的 SV
        #     接口**类型名**（interface_templates/interface.sv.j2）
        #   · `interfaces[].agent_path` = `[{agent}_agent_h]` —— env 里 agent 的
        #     **实例路径**（env.yaml 的 `agents[].name` + `_agent_h`），
        #     tb_top 用它做 `uvm_config_db#(virtual ...)::set(null, "*.<path>*", "vif", ...)`
        #
        # `ports` 是**接口与 DUT 同名直连**的信号名：接口端口必须真的存在、且 DUT
        # 里也得有同名端口，两个条件同时满足才写进来（不同名的宁可不连 —— 悬空端口在
        # SV 里合法，连到不存在的信号直接编译不过）。
        dut_port_names = {p["name"] for p in all_ports}

        def _port_names(ag_name: str) -> List[str]:
            """这个 agent 的接口有哪些端口 —— **与 `_generate_interface_yaml` 同源**。

            两处必须一致：tb_top 直连的是接口的端口，接口的端口写错了名字，
            这里连的就不是同一个东西。所以取法照抄那边：先看 agent 自带的
            `ports`，没有就用 spec 接口的 `signals`（嵌套写法）。
            """
            ag_data, iface = next(
                ((ag, i) for ag, i in agents_spec if ag.get("name") == ag_name),
                (None, None))
            names = [p.get("name") for p in ((ag_data or {}).get("ports") or [])
                     if isinstance(p, dict)]
            if not any(names) and isinstance(iface, dict):
                sigs = iface.get("signals")
                if isinstance(sigs, dict):
                    names = list(sigs)
                else:
                    names = [p.get("name") for p in (iface.get("ports") or [])
                             if isinstance(p, dict)]
            return [str(n) for n in names if n]

        bench_if_lines = []
        for ag_name in agent_names:
            # **时钟/复位不进 `ports`**：tb_top 已经把它们从 `clk_rst_if` 接到 DUT 上了
            #（`.pclk(pclk_vif.clk[0])`），再按接口同名接一遍会渲染出**重复的端口连接**
            #（`.pclk` 出现三次）→ vlog 判重名端口。所以这里只留数据信号。
            names = [n for n in _port_names(ag_name)
                     if n in dut_port_names and n not in (clock_port, reset_port)]
            ordered = [n for n in names if n not in (clock_port, reset_port)]
            block = [
                f"    - name: {ag_name}_if",          # interface **实例名**
                f"      type_name: {ag_name}_if",     # interface **类型名**
                f"      clock: {clock_port}",
                f"      reset: {reset_port}",
                # agent_path = env 里 agent 的**实例路径**（env.yaml 的 agents[].name + _agent_h）
                f"      agent_path: [{ag_name}_agent_h]",
            ]
            if ordered:
                block.append(f"      ports: [{', '.join(ordered)}]")
            bench_if_lines.append("\n".join(block))

        # 没有 agent 时 `interfaces:` 不能留空 —— 空值不是 array，schema 会判 None
        interfaces_block = ("\n" + "\n".join(bench_if_lines)) if bench_if_lines else " []"

        bench_str = f"""bench:
  name: {module_name}_bench
  include_assertions: false
  clk_rst_if:
    clocks:
      - {{ name: {clock_port}, period: 10ns, init: 0 }}
    resets:
      - {{ name: {reset_port}, init: 0, release_delay: 10 }}
  dut_module: {dut_module}
  dut_instance: u_{dut_module}
  interfaces:{interfaces_block}
"""
        # ── 参考模型接入（黄金模型命中时）：tb_top 真实实例化 DUT vs 参考模型比对 ──
        # 修复历史缺口：ref_model_enabled 默认 false → "参考模型比对"从未真正发生。
        # 现在按 spec 接口匹配黄金库（apb_slave 等），生成端口映射 + 比对输出。
        # 注：这里原先还会往 bench 里塞一段 `ref_model:`（黄金参考模型接入）。已删除：
        #   · `bench` 的 schema 是 `additionalProperties: false`，而 `ref_model` **不在**
        #     允许键里 —— 写了必然校验失败（这正是「点了启动就卡死」的触发源之一）
        #   · 没有任何模板读它（bench_templates 只用到 clk_rst / dut_instance /
        #     env_name / harness / name / wave_dump），也没有任何 python 读它
        # 也就是说它既进不去、又没人用。参考模型的正当归宿是 env 级的
        # `analysis_components`（见 examples/apb/apb_env.yaml），那是另一件事。

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

    # ── 9. 生成参考模型组件注册（TLM 1.0）──
    # 库在 `database/model_registry.db`，这里只把**选中那版**写成装配单。
    # 「SQL 是库（有哪些、验证过没有、哪一版），yaml 是这一轮的装配单」——
    # 缺这一步，库里存的东西就永远只是个文档，`tool_uvm` 拿不到它。
    try:
        models_path = _generate_models_yaml(output_dir=output_dir,
                                            yaml_dir=uvm_yaml_archive,
                                            module_name=module_name,
                                            agents=agent_names)
        if models_path:
            yaml_files.append(str(models_path))
            print(f"  [find_yaml] Generated {models_path.name}", flush=True)
    except Exception as e:                             # noqa: BLE001 模型库不该拖垮生成
        print(f"  [find_yaml] 模型组件注册未生成（不影响其它产物）: {e}", flush=True)

    # 记录本轮**本工具**产出的 YAML —— 下一轮只清这些，不清共享目录。
    record_owned_yaml(uvm_yaml_archive, yaml_files)
    return json.dumps({
        "status": "ok",
        "module_name": module_name,
        "yaml_files": yaml_files,
        "yaml_count": len(yaml_files),
        "env_name": f"{module_name}_env",
    }, ensure_ascii=False)


