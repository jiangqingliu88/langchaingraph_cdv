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
from typing import Any, Dict, List
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


def _strip_comments(text: str) -> str:
    """去掉 SV 注释（`/* */` 与 `//`）—— 端口表逐段匹配前必须先剥。"""
    text = re.sub(r"/\*.*?\*/", " ", text, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", " ", text)


def _match_paren(text: str, start: int) -> int:
    """`text[start]` 是 `(` → 返回与它配平的 `)` 的下标（没有则 -1）。"""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return i
    return -1


def _width_of(rng: str, params: List[Dict[str, Any]] = None) -> int:
    """`[hi:lo]` → 位宽，**认符号宽度**（`[W-1:0]`，W 在参数表里）。

    为什么必须认：只认数字时，`input logic [W-1:0] data` 的宽度段整段匹配不上，
    正则就会**回溯**到把类型关键字 `logic` 当成端口名 —— 端口表里凭空多出一个叫
    `logic` 的信号、真正的 `data` 反而没了（实测）。名字错的危害比宽度错更大：
    agent 会去驱动一个**不存在**的信号。解不出就不猜（宽度 1），但名字一定是对的。
    """
    if not rng or ":" not in rng:
        return 1
    known = {p.get("name"): int(p.get("value")) for p in (params or [])}
    hi_s, lo_s = (t.strip() for t in rng.split(":", 1))

    def _val(expr: str):
        if expr.isdigit():
            return int(expr)
        if expr in known:
            return known[expr]
        m = re.fullmatch(r"(\w+)\s*-\s*(\d+)", expr)          # `W-1`
        if m and m.group(1) in known:
            return known[m.group(1)] - int(m.group(2))
        return None

    hi, lo = _val(hi_s), _val(lo_s)
    if hi is None or lo is None:
        return 1
    return max(1, hi - lo + 1)


def _port_list_span(text: str, after_name: int):
    """模块头 → `(参数表文本, 端口表文本)`；抓不到就 None。

    **不能用 `\\(([^)]*)\\)` 抓端口表**：那会在**第一个 `)` 处收尾** ——
    端口注释里写个 `(async)` 就会把后面**所有端口静默截掉**。它与"注释吃掉端口"
    是同一类故障：表少了几行、没有任何人报，最后表现为"信号没人驱动 / 覆盖点
    永远 0%"，离原因很远。所以这里数括号深度，取配平的那一个。
    """
    p = text.find("(", after_name)
    if p < 0:
        return None
    param_str = ""
    if "#" in text[after_name:p]:                 # `#( ... )` 参数表在前
        end = _match_paren(text, p)
        if end < 0:
            return None
        param_str = text[p:end + 1]
        p = text.find("(", end + 1)
        if p < 0:
            return None
    end = _match_paren(text, p)
    if end < 0:
        return None
    # 端口表后面应当只剩 `;`（允许中间夹注释）—— 这一条挡的是"在注释里
    # 提到 module 名字、又把后面某个括号当成端口表"那种误匹配。
    if not re.match(r"\s*;", _strip_comments(text[end + 1:end + 80])):
        return None
    return param_str, text[p + 1:end]


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
        m = re.search(r'\bmodule\s+(\w+)', text)
        if not m:
            continue
        mod_name = m.group(1)
        span = _port_list_span(text, m.end())
        if span is None:
            continue
        param_str, ports_str = span

        ports = []
        params = []
        # 解析参数
        for pm in re.finditer(r'parameter\s+(\w+)\s*=\s*(\d+)', param_str):
            params.append({"name": pm.group(1), "value": pm.group(2)})

        # 解析端口: input/output/inout [type] [width] name
        for line in ports_str.split(","):
            # ⚠️ **先剥注释再匹配**：下面两句都是 `re.match`（**锚定**的），
            # 段首若是 `// 说明文字`（上一个端口的**行尾注释**、或一段
            # `// ── 分组 ──`），整段就匹配不上 —— 那个端口**静默消失**。
            #
            # 实测（本仓库自己的 NPU DUT）：`instr_valid` / `barrier_type` /
            # `op_priority` / `issue_valid` 4 个端口的段首都带着注释，于是
            # 14 个端口解出 10 个 —— 表现是"这几个 DUT 输入没人驱动、对应的
            # 覆盖点永远 0%"，而没有一行日志说端口丢了。
            line = _strip_comments(line).strip()
            if not line:
                continue
            # 匹配: input/output/inout [可选类型] [可选宽度] name
            #
            # 宽度段收 `[^\]]+` 而**不是** `\[\d+(?::\d+)?\]`：后者认不出
            # `[W-1:0]` 这种符号宽度，于是整段回溯 —— `logic` 被当成端口名，
            # 真正的信号反而没了（实测）。宽度交给 `_width_of` 解。
            pm = re.match(
                r'(input|output|inout)\s+(?:logic|wire|reg|bit)?\s*'
                r'(?:\[([^\]]+)\])?\s*(\w+)',
                line
            )
            if pm:
                ports.append({"name": pm.group(3), "direction": pm.group(1),
                              "width": _width_of(pm.group(2), params)})
            else:
                # 简化匹配: input/output name
                sm = re.match(r'(input|output|inout)\s+(\w+)', line)
                if sm:
                    ports.append({"name": sm.group(2), "direction": sm.group(1), "width": 1})

        if not ports and ports_str.strip():
            # 非 ANSI 表头（`module x (a, b); input a; ...`）落在这里 ——
            # 那不是"这个模块没有端口"，是**没解析出来**。说出来，别让它变成
            # 一份"没有端口"的 spec 悄悄往下走（那种 spec 生成出来的 agent
            # 一个信号都不驱动，而覆盖率只是低，看不出哪里错了）。
            print(f"[find_spec_yaml] 警告：{sv.name}::{mod_name} 的端口表解析出 0 个"
                  f"端口 —— 可能是非 ANSI 风格的表头（当前只认 `input logic [w] name`）")

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
    """检测是否为时钟端口 —— **判定口径在 `src/tools/lib/ports.py`**（共用）。"""
    from src.tools.lib.ports import is_clock_port
    return is_clock_port(name)


def _is_reset_port(name: str) -> bool:
    """检测是否为复位端口 —— 同上，别在这里另写一份（两份会漂）。"""
    from src.tools.lib.ports import is_reset_port
    return is_reset_port(name)


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
        from src.tools.lib.llm_call import call_llm
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
        raw = (call_llm(prompt, "", "") or "").strip()
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


def _iface_name_of(ag_name: str) -> str:
    """agent 名 → 接口名。**一个接口出 master/slave 两个 agent**（见 interface yaml
    的头注释），所以接口名 = agent 名去掉 `_master`/`_slave` 后缀。"""
    n = str(ag_name or "")
    for suffix in ("_master", "_slave"):
        if n.endswith(suffix):
            return n[: -len(suffix)]
    return n


def _spec_agent_of(agents_spec: list, ag_name: str) -> dict:
    """从 spec 的 `agents[]` 里取该 agent 原始定义（取不到返回 {}）。"""
    for ag, _iface in agents_spec or []:
        if isinstance(ag, dict) and ag.get("name") == ag_name:
            return ag
    return {}


def _is_active_type(value: str) -> bool:
    """spec 的 `type` 是不是"激活模式"而不是类名。

    按协议分组那条路会把 `UVM_ACTIVE`/`UVM_PASSIVE` 塞在 `type` 里
    （见 `_group_agents_by_protocol`）—— 那种值不能原样写进 env.yaml 的 `type:`，
    否则 env 模板渲染出 `UVM_ACTIVE apb_agent_h;`。
    """
    return str(value or "").upper() in ("", "UVM_ACTIVE", "ACTIVE",
                                        "UVM_PASSIVE", "PASSIVE")


def _ref_mirror_gate(module_name: str, interfaces: list, registers: list):
    """能不能给这个设计接「寄存器镜像」参考模型？能则返回接线参数，不能返回 None。

    ## 为什么不能只凭「黄金命中」就接

    `match_golden()` 是**按协议/信号名关键词**匹配的（`golden_library.py:74-80`），
    它**没有任何语义证据**。于是只要有 `paddr/pwdata/prdata` 这几个 APB 名字，就会
    命中 `apb_slave` —— 哪怕这个 DUT 的 `prdata` 根本不来自寄存器堆。

    本仓库自己的 `apb_uart` 就是这种：生成物里 `assign prdata = fifo_rdata;`
    （FIFO 直出），而 spec 的 `registers` 是**空的**。给它接一个"写啥读啥"的寄存器
    镜像，每一条读事务都会 mismatch —— 那不是发现了 bug，是**我们自己造了一批
    假失败**，而且会污染整条回归的结论（`examples/apb/apb_env.yaml` 记的正是
    这个坑：expected 恒 0、actual 一堆真事务 → "scoreboard FAILED: extras=N"）。

    ## 所以判据是「有证据说明它就是个寄存器文件」

    三条同时成立才接：

      1. 黄金命中 `apb_slave`（只有这一份的语义被镜像实现了）；
      2. `registers` **非空** —— 空表说明设计根本没声明寄存器语义，没证据；
      3. 每条寄存器的 `access` 都是 **RW** —— 只要有 RO/WO，镜像的读期望值就与
         DUT 的真实行为（状态位、只读数据）对不上，必然假失败。

    条件不满足就**不接**，而不是接一个"将就"的。少一个比对是缺功能；接错一个
    比对是把整套回归的结论弄脏 —— 后者贵得多。
    """
    regs = [r for r in (registers or []) if isinstance(r, dict) and r.get("name")]
    if not regs:
        return None
    not_rw = [str(r.get("name")) for r in regs
              if str(r.get("access", "")).upper() not in ("RW", "")]
    if not_rw:
        return None

    try:
        from src.tools.lib.golden_library import build_ref_model_config

        cfg = build_ref_model_config(module_name, interfaces, registers)
    except Exception:                                  # noqa: BLE001 命中不了就当没有
        return None
    if not cfg or (cfg.get("golden") or {}).get("ip") != "apb_slave":
        return None
    if "prdata" not in (cfg.get("compare_outputs") or []):
        return None

    def _width(sig_names, default):
        """从 `paddr[7:0]` / `prdata[7:0]` 这类型里取位宽；取不到给默认。"""
        for i in interfaces:
            nm = str(i.get("name", ""))
            if any(k in nm.lower() for k in sig_names) and "[" in nm:
                rng = nm[nm.index("[") + 1:nm.index("]")]
                hi, _, lo = rng.partition(":")
                try:
                    return abs(int(hi) - int(lo or 0)) + 1
                except ValueError:
                    pass
        return default

    addr_w = _width(("paddr",), 8)
    data_w = _width(("prdata", "pwdata"), 8)
    goldie = cfg["golden"]
    return {
        "addr_w": addr_w,
        "data_w": data_w,
        "nregs": 1 << addr_w,
        "source": f"golden {goldie.get('ip')} {goldie.get('version', '')}".strip(),
    }


def _gen_env_yaml(module_name: str, agent_names: list, agents_spec: list,
                  clock_port: str, reset_port: str, registers: list = None,
                  interfaces: list = None) -> str:
    """生成 env.yaml：environment.agents（每个 agent 一条）。

    ── `interface` 是**从上层（spec 的 agents[]）传下来的**，不是 agent 名 ──

    spec 里的 agent 长这样：
        { "name": "apb_master", "interface": "apb", "type": ..., "is_master": true }
        { "name": "apb_slave",  "interface": "apb", "type": ..., "is_master": false }
    —— 两个 agent **共用**同一个接口 `apb`。

    这里原来写的是 `interface: {ag_name}`，即拿 agent 名冒充接口名，写出
    `interface: apb_master`。后果不是"多写了一个字段"，而是**整条 env 链作废**：
    env 模板渲染 `import {{ agent.interface }}_pkg::*` → `import apb_master_pkg::*`，
    而真实的包叫 `apb_pkg` —— 于是 env / env_config 里每一个跨包类型都变成
    "Invalid type"，一屏连带错误，根因却只是这一处的字段来源错了。

    字段语义的参考样本见 `examples/apb/apb_env.yaml`（那边是 list 形式，
    `_normalize_agents_list` 两种形式都收）。
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
        spec_ag = _spec_agent_of(agents_spec, ag_name)
        is_active = active_by_name.get(ag_name, True)
        # **接口名从上层传下来**（spec 的 agents[].interface），不是 agent 名。
        iface_name = str(spec_ag.get("interface") or "") or _iface_name_of(ag_name)
        # master/slave：spec 显式给了就用，否则按名字后缀推
        is_master = spec_ag.get("is_master")
        if is_master is None:
            is_master = not str(ag_name).endswith("_slave")
        # **`type` 必须写对**：env 模板靠它推 seq_item / config / sequence 类型名
        #（`base_name = type 去掉 _agent`）。不写或写成 `UVM_ACTIVE` 时，
        # env 渲染出 `apb_seq_item` / `apb_config` 这些**不存在的类** →
        # 生成物一片 "near \"::\": syntax error"。
        type_name = str(spec_ag.get("type") or "")
        if _is_active_type(type_name):
            type_name = f"{iface_name}_{'master' if is_master else 'slave'}_agent"
        agent_lines.append(
            f"    - name: {ag_name}\n"
            f"      is_active: {'true' if is_active else 'false'}\n"
            f"      is_master: {'True' if is_master else 'False'}\n"
            f"      interface: {iface_name}\n"
            f"      type: {type_name}\n"
            f"      clock: {clock_port}\n"
            f"      reset: {reset_port}")

    # ── clk_rst_vip：**必须有**，否则整条闭环是死的 ──
    #
    # 环境里的时钟/复位由 `clk_rst_agent` 驱动（tb_top 只实例化 `clk_rst_if`，
    # env 从 config_db 取出来转给 agent）。这段不写，env 模板就一个 clk_rst agent
    # 都不建 —— `pclk` 永远是 0，driver 里的 `@(posedge pclk)` 永远等不到，
    # 所有测试挂到 UVM 的 PH_TIMEOUT（9200 秒仿真时间），**覆盖率恒为 0**。
    # 实测踩过：回归"25/25 全过"其实是测试名不存在（UVM_FATAL INVTST）导致的假过；
    # 把名字修对之后 23 条全红，日志停在 "main_phase: start" 之后再无任何活动。
    #
    # 复位极性按**端口名**判断：`preset_n` / `rst_n` / `rstn` 这类以 n 结尾的是低有效。
    _rst = str(reset_port or "rst")
    _rst_low = _rst.lower().endswith("_n") or _rst.lower().endswith("n")

    lines = [
        f"environment:\n  name: {module_name}_env\n  agents:\n" + "\n".join(agent_lines),
        "  clk_rst_vip:",
        "    enabled: true",
        "    clocks:",
        f"      - {{ name: {clock_port}, period_ps: 10000, duty_cycle: 50, initial_value: 0, jitter_ps: 0 }}",
        "    resets:",
        f"      - {{ name: {_rst}, active_low: {'True' if _rst_low else 'False'}, assert_cycles: 10, recover_cycles: 5 }}",
    ]

    # ── 参考模型比对：analysis_components + scoreboards + tlm_connections ──
    #
    # 原先这里生成过 predictors + scoreboards，后来整段删了 —— 理由是当时那个
    # predictor 的 `process_<port>` 是个 **TODO 空壳**（`util_comp.sv.j2`），它永不写
    # `out_port`，于是接上去的 scoreboard expected 侧恒为 0、actual 是一堆真事务，
    # 每条用例都报假失败（`examples/apb/apb_env.yaml` 记的正是这一条）。
    #
    # 空壳那一半已经补上了：带 `ref_model` 的 util 组件会渲染出**真的**寄存器镜像
    # （见模板与 `#/$defs/refModelMirror`）。所以这里可以重新接 —— 但只在
    # `_ref_mirror_gate()` 认得出"这个设计确实是个寄存器文件"时才接（判据与理由
    # 都写在那儿的文档串里）。接不动就什么都不加：**没有 scoreboard** 的 env 至少
    # 是诚实的，假失败的 scoreboard 会让整条回归的结论不可信。
    # 参考模型来自 **SQL 库**（`ModelRegistry`）—— 不再是从 spec 的寄存器表推出来的
    # "写什么读什么"镜像。`_ref_mirror_gate`（registers 非空 + 全 RW）随之作废，
    # 这里只作**过渡兜底**（库里没有可用模型时才走它）。
    reg_model = _registry_model(module_name, agent_names, agents_spec)
    mirror = _ref_mirror_gate(module_name, interfaces or [], registers or [])
    util_blocks: List[str] = []
    if reg_model or mirror:
        # 找一个 **master** 的 APB agent：expected 侧要跟 actual 侧同一条事务流。
        bus = None
        for ag_name in agent_names:
            spec_ag = _spec_agent_of(agents_spec, ag_name)
            is_master = spec_ag.get("is_master")
            if is_master is None:
                is_master = not str(ag_name).endswith("_slave")
            iface = str(spec_ag.get("interface") or "") or _iface_name_of(ag_name)
            if is_master and iface:
                bus = (ag_name, iface)
                break
        if bus:
            ag_name, iface = bus
            # 有库模型就用**它的**事务类型与类名：这是"SQL 是库、yaml 是装配单"的
            # 落点。TLM 1.0 组件两侧类型**可以不同**（DUT 级：APB 进 / UART 出）。
            item_t = (reg_model["trans_in"] if reg_model
                      else f"{iface}_master_seq_item")
            api_t = (reg_model["trans_out"] if reg_model
                     else f"{iface}_master_seq_item")
            pred_cls = reg_model["name"] if reg_model else f"{iface}_ref_predictor"
            pred_h = f"{iface}_ref_pred"
            scb_h = f"{module_name}_scb"

            lines += [
                # env 级组件：predictor 由 `util_components` 生成（env_pkg 会 include 它），
                # 这里只声明/例化 —— 类型名 = 那个生成类的类名。
                "  analysis_components:",
                f"    - name: {pred_h}",
                f"      type: {pred_cls}",
                "  scoreboards:",
                f"    - name: {scb_h}",
                "      sb_type: in_order_scoreboard",
                f"      trans_type: {item_t}",
                f"      params: [{item_t}, {api_t}]",
                "  tlm_connections:",
                # actual：DUT 侧 monitor 出来的事务（`<agent>_agent_ap` 由 env 模板建）
                f"    - {{ driver: {ag_name}_agent_ap, receiver: {scb_h}.actual_export }}",
                # expected：参考模型镜像算出来的那份
                f"    - {{ driver: {pred_h}.out_port, receiver: {scb_h}.expected_export }}",
            ]
            util_blocks.append(
                "util_components:\n"
                f"  - name: {pred_cls}\n"
                "    type: uvm_component\n"
                "    description: \"参考模型镜像（APB 寄存器文件）—— 读事务给出期望 prdata\"\n"
                "    analysis_exports:\n"
                f"      - {{ name: in_export, type: {item_t} }}\n"
                "    analysis_ports:\n"
                f"      - {{ name: out_port, type: {item_t} }}\n"
                "    ref_model:\n"
                f"      nregs: {mirror['nregs']}\n"
                f"      addr_w: {mirror['addr_w']}\n"
                f"      data_w: {mirror['data_w']}\n"
                f"      source: '{mirror['source']}'")

    if reg_model:
        # 库里有模型 → 它**取代**上面那版镜像 util_components。组件本体由
        # `util_comp.sv.j2` 从 `body` 渲染（TLM 1.0 事务级）；出处与状态如实带上
        # （`draft` = 该版还没验证过），别让人以为验证过了。
        util_blocks = [_util_component_yaml(reg_model)]

    return "\n".join(lines + util_blocks) + "\n"


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
    # 注：这里原来还会写 `custom_drive_logic` / `custom_collect_logic`（UART 的
    # 串行化/反串行化 SV 代码）。**已删除**，因为那是 `custom_code` 功能的残骸，而
    # 那个功能下线了：`gen_uvm.py:539` 明写「pragma custom 区域不再从 YAML 回填
    # （custom_code 已下线）」。没有任何模板读这两个键（模板走的是 `// pragma custom
    # ... begin/end` 那套**人工**注入约定），`gen_uvm` 也不读。
    #
    # 后果不只是"写了没用"：`interface` 的 schema 是 `additionalProperties: false`，
    # 这两个键必然校验失败 → `gen_uvm` 抛 SystemExit → **UART 这条路整条跑不通**。
    # 与之前 bench 里那段 `ref_model:` 是同一个形状。
    #
    # `_gen_uart_serial_logic` / `_gen_uart_deserialize_logic` 两个函数**保留**：
    # 内容是能用的 SV，只是暂时没接线。要复活这个功能，正确的入口是
    # `gen_uvm` 的 PragmaCustomInjector（往 pragma 槽里注），而不是回填 YAML。
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
    # 清理旧 YAML，避免残留 dut_* 文件。
    #
    # ⚠️ **这个目录是本工具的私有产物目录 —— 这里会清空它。**
    # 任何**比本工具更早**的阶段写进这个目录的东西都会在这里被删掉，而本工具
    # 后面还可能要读它（实测：front 写的 `casemodel.yaml` 就是这么被删的，
    # 而接下来 `_casemodel_test_lines` 正要去读 —— 于是 `environment.tests`
    # 永远注入不进去，`env/tests` 里生成不出属性 test 类）。
    # 要跨阶段存活的东西**不要放这里**：casemodel 走
    # `layout.casemodel_path()`（`<run>/inputs/casemodel.yaml`）。
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
        env_str = _gen_env_yaml(module_name, agent_names, agents_spec,
                                clock_port, reset_port, registers, ifaces)
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
    # 库在 `.signoffai/model_registry.db`，这里只把**选中那版**写成装配单。
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


def _dedupe_loopback_tests(test_lines: list, lb_names: set) -> list:
    """重名 test 只保留**最后一次**出现的那条（带独立 loopback build + 正确顶层）。

    为什么必须"留最后一条"而不是"遇到重名就全删"：loopback 用例由**两处**产生 ——
      · case 库里那条：绑在 DUT build 上、顶层是 `<m>_bench_tb_top`（**错**）；
      · 本函数上面刚生成的那条：绑 `build_<m>_<ag>_loopback`、顶层 `<ag>_loopback_tb`（**对**）。
    后者排在后面。原先的写法把**所有**同名的都删了 —— 把对的那条也删掉，只剩绑错
    build 的那条；那目录里是给别的 top 用的脚本，一跑就是 "Error loading design"，
    记成 `unknown`，还会让闭环绕开覆盖率阶段。
    """
    if not lb_names:
        return list(test_lines)
    last: dict = {}
    for i, line in enumerate(test_lines):
        if line.startswith("  - name: "):
            name = line[len("  - name: "):].strip()
            if name in lb_names:
                last[name] = i
    kept: list = []
    skip = False
    for i, line in enumerate(test_lines):
        if line.startswith("  - name: "):
            name = line[len("  - name: "):].strip()
            # 只在**不是最后一次**出现时丢弃（即丢掉重复的早期那条）
            skip = name in lb_names and i != last.get(name)
        if not skip:
            kept.append(line)
    return kept


def _seed_plan(output_dir: Path) -> Dict[str, Dict[str, int]]:
    """`coverage/coverage_plan.yaml` → `{test 名: {base, count, explore}}`。

    计划是 **verify 阶段与 case 模型同批**落盘的（见
    `executors/verify/main.py::_write_coverage_plan`），这里只读不算 ——
    种子是**验证完备性的声明**（这一批要跑够几条），不是回归自己拍的参数。

    读不到就给空 dict（回归按默认 `count: 1` 跑）—— **不编一个种子出来**：
    编出来的种子会让"这一批到底跑够没有"变得无法回答。
    """
    path = output_dir / "coverage" / "coverage_plan.yaml"
    if not path.is_file():
        return {}
    try:
        import yaml as _yaml
        plan = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except Exception:
        return {}
    out: Dict[str, Dict[str, int]] = {}
    for b in (plan.get("batches") or []):
        if not isinstance(b, dict):
            continue
        test, seeds = str(b.get("test") or "").strip(), b.get("seeds") or {}
        if not test:
            continue
        # `dimensions` **两种形状都认**：计划里是列表，env 注入那份是逗号串
        # （注入走 YAML 流式一行，列表要另写缩进）。`str(list)` 会得到
        # `"['D_type']"` —— 那既是噪音又会在 desc 里露出来。
        dims = b.get("dimensions")
        dims = ",".join(str(x) for x in dims) if isinstance(dims, list) else str(dims or "")
        entry: Dict[str, Any] = {"theme": str(b.get("theme") or ""),
                                 "priority": str(b.get("priority") or ""),
                                 "dimensions": dims}
        if isinstance(seeds, dict):
            entry.update({k: int(v) for k, v in seeds.items()
                          if isinstance(v, int)})
        out[test] = entry
    return out


def _seed_offset(output_dir: Path) -> int:
    """闭环"扩种"动作留下的**种子偏移**（`coverage/seed_expand.json`）。

    ## 为什么需要这条线

    决策层选 `EXPAND_SEEDS` 时会把 `{"count": N}` 交给 `n_apply_expand_seeds`，
    那边写进 `state.seed` 并记一行"扩种 → seed += N" —— **但那个 state 只被当
    覆盖 agent 的输入用**，回归的 `SEED` 一直是写死的 `12345` + case 模型声明的
    `base`。于是这个动作是个**静默空转**：账上记着"扩了种"，仿真跑的却是同一批
    随机流，覆盖率每轮钉在同一个数（实测六轮 56.2 不动，而每轮 ucdb 的 sha256
    都不一样 —— 数据在采，只是采的是同一批激励）。

    约定：`n_apply_expand_seeds` 每轮把偏移**累加**着写进这个文件（单调递增，
    不覆盖历史），回归生成时把偏移加到每条 test 的基准种子上。
    读不到就是 `0`（没扩过种）—— 不编一个偏移出来。
    """
    path = Path(output_dir) / "coverage" / "seed_expand.json"
    if not path.is_file():
        return 0
    try:
        import json as _json
        return int((_json.loads(path.read_text(encoding="utf-8",
                                                 errors="replace")) or {}).get("offset", 0))
    except Exception:                                      # noqa: BLE001
        return 0


def _seed_lines(name: str, plan: Dict[str, Dict[str, int]],
                offset: int = 0) -> List[str]:
    """这条 test 的 `count` / `SEED` 两行（计划里没有就 `count: 1`）。

    **`count` 展开的种子是"基准 + 逐条递增"**（回归框架 `expand_count`）——
    所以这里只给**基准**，`count` 条各自拿 `base + i - 1`。`{{ SEED }}` 的
    落点是 `run_cmd`（`_sim_run_cmd` 里的 `+ntb_random_seed`）。

    `explore`（探索种子）**并进 count**：它是"防过拟合那几条"，跑法一样、只是
    目的不同；分成两条 test 反而让"这一批一共跑了多少次"说不清。

    `offset` 是闭环"扩种"动作累加出来的偏移（见 `_seed_offset`）—— 加到**基准**
    上，于是整段的随机流换一条（不是把 count 撑大：多跑几条同样的种子没有意义，
    要的是**没跑过的**那些）。
    """
    s = plan.get(name)
    if not s:
        return ["    count: 1"]
    total = int(s.get("count", 0)) + int(s.get("explore", 0))
    if total <= 0:
        return ["    count: 1"]
    return [f"    count: {total}",
            f"    variables: {{SEED: {int(s.get('base', 0)) + int(offset or 0)}}}"]


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

    # 种子管理：从**与 case 模型同批落盘**的功能覆盖率计划里读（只读不算）
    seed_plan = _seed_plan(output_dir)
    # 闭环"扩种"动作的偏移（`coverage/seed_expand.json`，由 apply 阶段写入）。
    # **不加这一条，扩种就是个静默空转**：决策记着"seed += N"，回归照旧跑
    # 写死的 12345 + 计划的 base，每轮同一批随机流（实测覆盖率六轮不动）。
    seed_offset = _seed_offset(output_dir)
    if seed_offset:
        print(f"  [find_yaml] 扩种偏移 +{seed_offset}：每条 test 的基准种子已顺移"
              f"（闭环扩种动作的落点）", flush=True)

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
        # **按模块筛**：这个库是项目级的，躺着所有跑过的模块 —— 不筛就会把
        # 别的项目的用例写进本项目的 regression.yaml（实测：NPU 的 p0 里跑了
        # 14 条 apb_uart 的名字，全用本地 test 兜底执行，同一个仿真数了十几遍）。
        cases = case_reg.get_priority_order(stage=0, limit=50, module=module_name)
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

    dut_build = f"build_{module_name}_dut"
    dut_top = f"{top_module}_bench_tb_top"

    def _sim_run_cmd(top: str, uvm_test: str) -> str:
        """一条完整的仿真命令（demo.yaml 的 `run_cmd` 写法）。

        比旧的 `run_opts` + 全局 `settings.simulators.<sim>.run` 模板强在：
        顶层模块名、日志文件、**跑完怎么判成败**都能直接写进来，不必挤占
        `run_opts`，也不必再管"框架会在命令尾巴追加 `> sim.log 2>&1`"。

        末尾那句 `! grep ...` 是**唯一的失败判据**：回归框架只看退出码，而 vsim
        无论跑出多少 UVM_ERROR / UVM_FATAL，只要最后 `quit -f` 了就是 exit 0 ——
        实测 `+UVM_TESTNAME=不存在的测试` 这种 UVM_FATAL(INVTST) 也是 0，
        于是"一条都没跑"被记成 PASS。**只匹配计数非 0 的那行**
        （`UVM_ERROR :    3`）；匹配裸 `UVM_ERROR :` 会连 `UVM_ERROR :    0` 一起命中。
        日志走 `-l sim_vsim.log`，避免和框架那句收尾重定向抢同一个文件。

        **为什么还要匹配 `FATAL ERROR` / `Errors: *[1-9]`**：UVM 那两条计数管不到
        "仿真根本没起来"——实测 8 条用例挂在 `vsim-3772 Failed to load DPI auto
        compile shared library`，vsim 直接 `FATAL ERROR while loading design` 退出，
        日志里一条 `UVM_ERROR :` 都没有，于是**全部记成 PASS**（波形、覆盖率自然
        也没有）。末尾那行 `# Errors: 2, Warnings: 0` 是 vsim 自己的结算，按它判
        才盖得住这一类。

        `{{ MODE_OPTS }}` 是**仿真业务的落点**（波形 / 覆盖率 / 调试…）：里面装的是
        本次启用的那几门业务的选项串，由回归框架的 `apply_modes()` 按 `modes:` 表
        拼好（表见 `src/tools/regression_tools/common_base.yaml`，取值见 `sim_modes.py`）。
        没启用任何业务时它是未定义的，所以必须 `| default("")` —— 渲染走的是
        `StrictUndefined`，裸 `{{ MODE_OPTS }}` 会在"什么都不开"的那次直接报错。
        """
        # `[ -s sim_vsim.log ] &&` **不能省**：日志**不存在或为空**时，`grep` 自己
        # 报错退出（非零），而 `!` 一取反就成了**通过** —— 于是"vsim 压根没起来"
        # 被记成 pass。实测踩过：环境里 vsim 崩了（连 `sim_vsim.log` 都没生成），
        # 一整轮回归全绿、覆盖率 0%，而各用例的 status.env 都是 pass。
        # 先要求日志非空，再谈里面有没有错。
        #
        # ── 第三段：**"没报错"不等于"验过了"** ──
        #
        # 用户定的口径：**真 pass = SCB 报 `mismatched=0`（真有比对） + 断言不报错**。
        # 前两段只查了"没有错"，那对一条**压根没有判据**的用例同样成立 —— 实测：
        # p0/p1 的 env 测试既没例化 scoreboard、也没断言，20 条照样全绿，而
        # `test_npu_basic_test` 覆盖率 0.0%/0.0% 也是 pass。
        #
        # 所以再要求一条**比对结论**：日志里得有 `mismatched=0`（SCB 的结算行）。
        # 没有 → 判失败并**写明原因**（`NO_CHECKER_EVIDENCE`），而不是冒充通过。
        # 断言那半不需要额外条件：断言违规走 `$error` → Questa 打 `** Error:` →
        # 第二段的 `Errors: *[1-9]` 已经拦住（实测：把 RTL 的 RAW 守卫删掉，
        # 断言立刻报错、退出码非零）。
        return (
            # `+ntb_random_seed={{ SEED }}`：**每条 test 的种子落点**。`count`
            # 展开时回归框架给每条塞 `local_vars.SEED = base + i - 1`，不给这个
            # plusarg 的话展开出来的 N 条**跑的是同一组随机数** —— 名字变了、
            # 跑的东西没变（那正是 `_seed_base` 的注释里记着的坑）。
            "vsim -c -sv_lib {{ UVM_DPI }} -onfinish stop -work {{ WORK }} "
            f"{top} +UVM_TESTNAME={uvm_test} +ntb_random_seed={{{{ SEED }}}} "
            "-l sim_vsim.log "
            '-do "log -r /*; run -all; quit -f" {{ MODE_OPTS | default("") }} ; '
            "[ -s sim_vsim.log ] && "
            '! grep -qE "UVM_ERROR : *[1-9]|UVM_FATAL : *[1-9]|FATAL ERROR|Errors: *[1-9]"'
            ' sim_vsim.log && { '
            'grep -qE "mismatched=0" sim_vsim.log '
            '|| { echo "NO_CHECKER_EVIDENCE: 没有比对结论（真 pass 要求 SCB 报 mismatched=0）"; '
            'exit 1; }; }'
        )

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
            test_lines.extend(_seed_lines(cname, seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, f"{env_name}_directed_test")
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
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
            test_lines.extend(_seed_lines(tname, seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, f"{env_name}_base_test")
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
            test_lines.append(f"    tags: [\"{priority.lower()}\", \"{tid}\"]")
            if desc:
                test_lines.append(f"    desc: \"{desc[:80]}\"")
            test_lines.append("")
    else:
        # 回退：环境级测试（base/directed/random）—— env/tests 里真正生成的 test 类
        # 同上：这三个都真实存在（`_random_test` 不在其列，删掉）。
        for _tname in (f"{env_name}_base_test", f"{env_name}_directed_test"):
            test_lines.append(f"  - name: test_{_tname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(f"test_{_tname}", seed_plan, seed_offset))
            # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
            # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
            _run_cmd = _sim_run_cmd(dut_top, _tname)
            test_lines.append(f"    run_cmd: '{_run_cmd}'")
            test_lines.append(f"    tags: [\"smoke\"]")
            test_lines.append("")

    # ── 生成测试（随机 + 覆盖率缺口定向激励）──
    #
    # 上面每条 case 跑的都是**定向测试**。定向测试按剧本发固定几笔事务，多一笔
    # scoreboard 就对不上账（实测：往定向测试里注入额外激励，24 个 case 挂 21 个）。
    # 而覆盖率缺口补出来的定向激励**正是额外激励** —— 它只该落在能容忍它的
    # `*_gen_test` 上。
    #
    # 没有这条 case 会怎样：补出来的序列生成、注册、编译全过，但**没有任何 case
    # 执行它** —— 表现为"补了测试但覆盖率一动不动"（实测 5 轮 88.0%，一分没涨）。
    # 这条 case 就是让那段激励真正跑起来的地方（顺带每次回归都多一份随机激励，
    # 那本来就是随机测试该干的事）。
    #
    # 名字不取自 case 库（它是环境自带的测试，不是某个验证用例）：case 库回写
    # 状态时对不在册的名字会直接跳过（`TestcaseRegistry.update_status` 查不到就 return），
    # 不会污染用例库。
    test_lines.append(f"  - name: {module_name}_gen_stimulus")
    test_lines.append(f"    build: build_{module_name}_dut")
    test_lines.extend(_seed_lines(f"{module_name}_gen_stimulus", seed_plan, seed_offset))
    test_lines.append(f"    run_cmd: '{_sim_run_cmd(dut_top, f'{env_name}_gen_test')}'")
    # `p3` = 错误 + 随机。原先只有 `smoke/random/gap` —— **没有任何 pN tag**，
    # 于是这条随机用例哪个分级都进不去（分级回归按 p0..p3 筛，见 REGRESSION_STAGES）。
    test_lines.append('    tags: ["p3", "smoke", "random", "gap"]')
    test_lines.append("")

    # ── 批次测试（**一条 = 一个 UVM_TEST = 一个批次/专题**）──
    #
    # 与用例库那一批**并存**：那边一条一个属性取值（粒度细，追状态与用例库），
    # 这边一条一个批次（粒度粗，挂**种子管理**）。两侧的名字不同、用途不同，
    # 合并不了 —— 合并了"这一批一共跑了多少次"就又说不清了。
    #
    # `+UVM_TESTNAME` 用**批次名**，对应 `test_batch.sv.j2` 生成的类
    # （`environment.batches` → `{env}_batch_test.sv`）。类不存在的话 UVM 报
    # INVTST 而 vsim 仍然 exit 0 —— **跑不起来反而看不出来**。
    if seed_plan:
        for bname, meta in seed_plan.items():
            test_lines.append(f"  - name: {bname}")
            test_lines.append(f"    build: build_{module_name}_dut")
            test_lines.extend(_seed_lines(bname, seed_plan, seed_offset))
            test_lines.append(f"    run_cmd: '{_sim_run_cmd(dut_top, bname)}'")
            prio = (meta.get("priority") or "P1").lower()
            theme = meta.get("theme") or ""
            # tag 用**分级回归那四级**（p0..p3）—— 分级就是按它筛的
            test_lines.append(f'    tags: ["{prio}", "batch", "{theme}"]')
            if meta.get("dimensions"):
                test_lines.append(f'    desc: "批次 {theme}：打 {meta["dimensions"]}"')
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
        test_lines.extend(_seed_lines(f"test_{ag}_loopback", seed_plan, seed_offset))
        # 完整仿真命令（demo.yaml 的 `run_cmd` 写法）：顶层模块名、日志路径、
        # 跑完的成败判定都写在这一条里，不再往 `run_opts` 里挤。
        _run_cmd = _sim_run_cmd(f"{ag}_loopback_tb", f"{ag}_loopback_test")
        test_lines.append(f"    run_cmd: '{_run_cmd}'")
        test_lines.append(f"    tags: [\"smoke\", \"loopback\"]")
        test_lines.append("")

    # ── 去掉重名 test ──
    #
    # case 库里也有叫 `apb_loopback` / `uart_loopback` 的用例，而上面 loopback 那一轮
    # 又会注册 `test_<ag>_loopback` —— 两条同名 test 会让 ShellGenerator 生成**同名
    # 目录**（`test_test_apb_loopback`），其中一个被排到另一个的 build 上跑：
    # 那目录里是给别的 top 用的脚本，一跑就是 "Error loading design"，记成 `unknown`，
    # 而且 `is_elab_failure_line` 会据此把每一格 sim 日志都读一遍 → 闭环绕开覆盖率阶段。
    # 保留后面那条（带独立 loopback build 和正确的 top），前面的整块删掉。
    _lb_names = {f"test_{ag}_loopback" for ag in agents if _is_agent_active(output_dir, ag)}
    test_lines = _dedupe_loopback_tests(test_lines, _lb_names)

    tests_section = "\n".join(test_lines)

    # ── builds 段：每个 build 一条**完整编译命令**（run_cmd）──
    #
    # 与 demo.yaml 同一套契约：`run_cmd` 里可以用 `{{ VAR }}` 取 `variables`，
    # 也可以直接写 shell 的 `${VAR}`。比旧的 `compile_opts` + `files` 表达力强，
    # 也不必再迁就 `settings.simulators.<sim>.compile` 模板的 `{opts}` / `{files}`。
    #
    # filelist 名是 `filelist_<agent 目录名>_lb.f`（`build_loopback_filelist` 由
    # L1.run_regression 拿 `agents/` 下的**目录名**生成，即 `{ag}_agent`）——
    # 写成协议名会 "Failed to open -f file .../filelist_uart_lb.f"。
    # 覆盖率是**编译期**使能的（vlog +cover），仿真期那句 `-coverage` 只是"允许保留
    # 已使能的统计"。所以"默认开覆盖率"这件事必须落在**编译命令**上，否则 vsim 那边
    # 挂了一串覆盖率开关，却没有任何被插桩的代码可采。
    #
    # 用 `cov_enabled`（`apply_modes` 给启用中的 mode 设的标记）而不是每次编译都加：
    # 不选覆盖率业务时命令与从前**逐字节一致**，不去动已经跑通的那条路。
    # `| default(false)` 不能省 —— 渲染走 StrictUndefined，裸 `{% if cov_enabled %}`
    # 在"没启用"的那次直接抛 UndefinedError。
    _cov_build_flag = " {% if cov_enabled | default(false) %}+cover{% endif %}"

    builds_lines = [
        f"  - name: build_{module_name}_dut",
        f"    top: {top_module}_bench_tb_top",
        f"    run_cmd: 'vlog -work {{{{ WORK }}}} -sv -mfcu +incdir+{{{{ UVM_SRC }}}}"
        f" {{{{ UVM_SRC }}}}/uvm_pkg.sv -f {filelist_ref}{_cov_build_flag}'",
    ]
    for ag in agents:
        if not _is_agent_active(output_dir, ag):
            continue
        lb_ref = str((fl_dir / f"filelist_{ag}_agent_lb.f").resolve()).replace("\\", "/")
        builds_lines.append(f"  - name: build_{module_name}_{ag}_loopback")
        builds_lines.append(f"    top: {ag}_loopback_tb")
        builds_lines.append(
            f"    run_cmd: 'vlog -work {{{{ WORK }}}} -sv -mfcu +incdir+{{{{ UVM_SRC }}}}"
            f" {{{{ UVM_SRC }}}}/uvm_pkg.sv -f {lb_ref}{_cov_build_flag}'")
    builds_section = "\n".join(builds_lines)

    from config.settings import questa_home
    _questa_root = questa_home().replace("\\", "/")

    # ── 仿真业务模式：include common_base.yaml（`modes:` 表的来源）+ 本后端取值 ──
    #
    # `include:` 把 `common_base.yaml` 当**基底**合并（框架 `_merge_config`：本地优先）。
    # 要的是它那张 `modes:` 表 —— 业务词条（wave/cov/upf…）→ 选项变量 的映射是**一份
    # 语义来源**，另起一套名字迟早两边对不上。
    #
    # **但它的值是 VCS 语义**（`-cm line+cond+…`、`+DUMP_FILE=…fsdb`），而本文件的
    # builds/tests 是 Questa（vlog/vsim）：把 VCS 参数原样拼进 vsim，vsim 判"未知选项"、
    # 整轮回归全崩。所以下面把同名变量**就地覆盖**成 Questa 取值（见 `sim_modes.py`，
    # 每条都在本机 `vsim -help` 里核过）。合并规则是本地优先，覆盖是有效的。
    #
    # 另一处要注意的：common_base 自己的 4 个 build（multi_step_build 等）会一起被
    # 合并进来，它们跑的是 `VCS …`。它们**没有任何 test 挂在上面**，而 L1 调度只跑
    # "yaml 里声明给该 build 的 test"（见 InfrastructureManager.run_regression 的
    # `tests_by_build`），所以永远不会被排进去。这条不变量有测试钉着
    # （tests/test_sim_modes.py::test_common_base_builds_are_never_scheduled）。
    from src.tools.regression_tools.sim_modes import (common_base_path,
                                                     yaml_variables)
    _mode_vars = "\n".join(f"  {k}: '{v}'" for k, v in yaml_variables().items())
    _common_base = common_base_path().as_posix()

    yaml_content = f"""# 回归测试配置 — 由 find_spec_yaml 自动生成
# 用法: python regression.py --config {reg_path.as_posix()} --action all --mode local
#
# ── 用的是 demo.yaml 那套契约（variables + 每 build/test 自带 run_cmd）──
# 旧写法（`global_vars` + `settings.simulators.<sim>.compile/run` 模板）留给
# 回归框架的模板只有 `{{files}}` / `{{run_opts}}` 两个占位符，想表达"顶层模块名"
# "日志路径""跑完怎么判成败"都只能往 run_opts 里硬塞，还得记住框架会在命令尾巴上
# 追加 `> sim.log 2>&1`。写成完整 `run_cmd` 就都不用绕了。
#
# ── 仿真业务模式（波形 / 覆盖率 / 调试…）──
# `modes:` 表与聚合变量机制来自 include 的 common_base.yaml；下面同名变量按本后端
# （Questa）**覆盖**了它的 VCS 取值。启用哪几门业务由上层给（CLI `--enable` /
# 工作台工具栏下拉，默认 cov+wave），框架的 apply_modes() 把它们拼进 MODE_OPTS，
# 仿真命令里写 `{{{{ MODE_OPTS | default("") }}}}` 取用。
# 值给空串的那些（xprop/tprop/upf）是本后端**没有对应开关**的：选中会被告警忽略，
# 不会把一个不存在的参数塞进命令行。

include:
  - {_common_base}

variables:
  # 闭环"扩种"动作的偏移加在基准上（见 `_seed_offset`）—— 加到**每一条**上，
  # 否则没有批次计划的那些 test（loopback / 手写用例）永远跑同一批随机流。
  SEED: {12345 + int(seed_offset or 0)}
  QUESTA: {_questa_root}
  UVM_SRC: {_questa_root}/verilog_src/uvm-1.2/src
  UVM_DPI: {_questa_root}/uvm-1.2/win64/uvm_dpi
  WORK: {str((output_dir / 'build' / 'work').resolve()).replace(chr(92), '/')}
  BENCH_TOP: {top_module}_bench_tb_top
{_mode_vars}

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


def _generate_models_yaml(output_dir: Path, yaml_dir: Path, module_name: str,
                          agents: list) -> Path | None:
    """把**选中的参考模型**写成 `models.yaml`（`util_components:` 一节）。

    **SQL 是库，yaml 是这一轮的装配单** —— 库在 `.signoffai/model_registry.db`
    （`ModelRegistry`），这里从库里读出**已验证**的那一版，落成 `tool_uvm` 吃得下
    的形状（见 `examples/apb/apb_util_comp.yaml`）。

    为什么不是"生成一份 TLM 组件的 .sv 塞进目录"：组件本体由**模板**从
    `util_components` 渲染（`util_comp.sv.j2` 的 `body` 分支），这里只出装配单。
    库里没有可用的模型（或都还没 verified）→ **不生成**，让下游按"没有参考模型"
    走（诚实降级），而不是拿 `draft` 硬凑一个必然假失败的。

    返回写出的路径；没有可用模型时返回 `None`。
    """
    import yaml as _yaml
    from src.layers.l4_memory.model_registry import ModelRegistry

    reg = ModelRegistry()
    try:
        # 设计里第一个非 slave 的 agent 的事务类型 —— 参考模型挂在它上面
        item = ""
        for a in agents or []:
            n = a if isinstance(a, str) else (a or {}).get("name", "")
            if n and not str(n).endswith("_slave"):
                item = f"{n}_master_seq_item"
                break
        chosen = reg.select(trans_in=item) if item else None
        if chosen is None and item:
            # 没有 `verified` 的 → 退一步用最新一版，但**把状态如实写进文件**
            #（`source.status`），并在下面标警示。**不冒充已验证** —— 那是伪造
            # 证据；把"这一版还没验过"写在装配单上，人才看得见。
            for m in reg.all():
                if m["trans_in"] == item:
                    chosen = m
                    break
        if chosen is None:
            return None
        uc = reg.to_util_component(chosen["name"], version=chosen["version"])
        doc = {"util_components": [uc],
               # 出处：审计要能回答"这一份模型是哪一版、验证过没有"
               "source": {"registry": str(reg.db_path),
                          "name": chosen["name"], "version": chosen["version"],
                          "status": chosen["status"]}}
    finally:
        reg.close()

    yaml_dir.mkdir(parents=True, exist_ok=True)
    path = yaml_dir / "models.yaml"
    path.write_text(
        "# 参考模型组件注册 —— 由 ModelRegistry 按本轮 agents 选出（TLM 1.0 事务级）\n"
        "# 库：.signoffai/model_registry.db；本文件是**装配单**，不是库。\n"
        + _yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    return path


def _registry_model(module_name: str, agent_names: list, agents_spec=None):
    """从 **SQL 模型库**（`ModelRegistry`）选这个 DUT 的参考模型；没有返回 None。

    这是"**SQL 是库，yaml 是装配单**"的落点 —— 库里是什么，env.yaml 就写什么。
    取代的是 `_ref_mirror_gate` 那条老路：从 spec 的 `registers` 表推"写什么读什么"
    的寄存器镜像（`registers` 为空就推不出，`apb_uart` 正是这种）。

    选法（按优先级）：
      1. **DUT 名精确命中**（库里 name == module_name）—— 最准；
      2. 按第一个 master agent 的事务类型选（`<iface>_master_seq_item`）。
    只挑 `verified`（`ModelRegistry.select()` 的口径）；没有 verified 的不自动接
    —— 拿没验证过的当 expected 就是自造假失败。
    """
    try:
        from src.layers.l4_memory.model_registry import ModelRegistry
        reg = ModelRegistry()
        try:
            hit = reg.get(module_name)                 # 1) DUT 名
            if hit and hit.get("status") != "verified":
                hit = None
            if hit is None and agent_names:            # 2) 按事务类型
                for ag in agent_names:
                    n = ag if isinstance(ag, str) else (ag or {}).get("name", "")
                    if not n or str(n).endswith("_slave"):
                        continue
                    m = reg.select(trans_in=f"{n}_master_seq_item")
                    if m:
                        hit = m
                        break
            return reg.to_util_component(hit["name"], hit["version"]) if hit else None
        finally:
            reg.close()
    except Exception as e:                             # noqa: BLE001 库坏了不该拖垮生成
        print(f"  [find_yaml] 模型库不可用（按无参考模型处理）: {e}", flush=True)
        return None


def _util_component_yaml(uc: dict) -> str:
    """`util_components` 一节 —— 直接喂 `util_comp.sv.j2` 的形状。

    `body` 由模板渲染进 `process_<port>`（TLM 1.0 事务级，**无 clk、无引脚**）；
    `source_version` 会作为出处注释落进生成的 SV。
    """
    def _ports(items):
        return "\n".join(f"      - {{ name: {p['name']}, type: {p['type']} }}"
                         for p in (items or []))

    out = ["util_components:", f"  - name: {uc['name']}",
           f"    type: {uc.get('type', 'tlm10_component')}"]
    if uc.get("description"):
        out.append(f"    description: \"{str(uc['description']).replace(chr(34), chr(39))}\"")
    out.append("    analysis_exports:")
    out.append(_ports(uc.get("analysis_exports")))
    out.append("    analysis_ports:")
    out.append(_ports(uc.get("analysis_ports")))
    if uc.get("source_version"):
        out.append(f"    source_version: {uc['source_version']}")
    body = uc.get("body")
    if body:
        ind = "\n".join("      " + ln for ln in str(body).split("\n"))
        out.append("    body: |")
        out.append(ind)
    return "\n".join(out)


def _casemodel_test_lines(output_dir) -> List[str]:
    """`casemodel.yaml` → `environment.tests:` 那几行；没有就给空。

    没有就**空着**（不编、不猜）—— 这份 yaml 是 front 从 spec 跑出来的，
    spec 里没料时它本来就不该存在。

    **路径走 `layout.find_case_model`，不许自己拼、也不许只认 `casemodel_path`**：

      · 以前找 `inputs/yaml/uvm/casemodel.yaml`（front 当时也写那儿），而那个目录
        是本工具的私有产物目录、**每次跑先被清空** —— "删它的和读它的是同一趟运行
        的同一个工具"，`tests:` 永远注入不进去（实测：`env/tests` 里没有属性 test）。
      · 后来改成只认 `casemodel_path()`（= front 的草稿落点）—— 又错在**人写的
        模型被绕过**：`specs/<模块>/casemodel.yaml` 优先级更高，而这里拿到的是草稿。
        实测：NPU 那份 12 维度的手写模型被跳过，注入的是草稿的 4 条，而日志只说
        "注入 5 行"，**看不出少了什么**。
    """
    try:
        # **走统一判据**，别自己认 `casemodel_path()`：那是 front 的草稿落点，
        # 而人写的模型（`specs/<模块>/casemodel.yaml`）优先级更高。
        # 直接读草稿的后果实测过：NPU 那份 12 维度的手写模型被绕过，
        # 注入进来的是草稿的 4 条 —— 而**日志只说"注入 5 行"，看不出少了什么**。
        from src.layers.l1_infrastructure.layout import find_case_model
        cm = find_case_model(_load_spec(output_dir) or {}, output_dir)
        if cm is None or not cm.exists():
            return []
        from src.tools.casemodel_tools.api import run_uvm_tests
        t = run_uvm_tests(cm.read_text(encoding="utf-8"), max_tests=200)
        tests = t.get("tests") or []
        if not tests:
            return []
        out = ["  tests:"]
        for x in tests:
            out.append("    - { dimension: %s, value: '%s', key: %s, int_value: %s }"
                       % (x.get("dimension"), x.get("value"), x.get("key"),
                          x.get("int_value")))

        # 批次 test 类（**一条 = 一个批次/专题**）—— 与属性 test 平行的另一条路。
        # 没有它，回归里 `+UVM_TESTNAME=<批次名>` 会撞 UVM_FATAL(INVTST)，
        # 而那条路径被记成 pass（vsim 遇到未知 testname 仍然 exit 0）。
        from src.tools.casemodel_tools.api import run_uvm_batches
        batches = run_uvm_batches(cm.read_text(encoding="utf-8")).get("batches") or []
        if batches:
            out.append("  batches:")
            for b in batches:
                # `policy` = **模型给的约束策略类名** —— 批次 test 类把它 set 进
                # config_db（`batch_policy`），协调序列据此建策略。**这一行漏了它，
                # 上面整条改动就白做**（`run_uvm_batches` 算出来了、这里不写，
                # 模板拿到空串 → 退回默认组合器 → 约束静默不生效）。手拼 YAML 的
                # 坏处就在这里：加一个字段要在两个地方各改一次。
                out.append("    - { name: %s, theme: %s, dimensions: '%s',"
                           " method: %s, policy: %s, priority: %s, checks: '%s' }"
                           % (b["name"], b["theme"], b["dimensions"],
                              b["method"] or "''", b.get("policy") or "''",
                              b["priority"] or "''", b["checks"]))
        return out
    except Exception as e:
        print(f"  [find_yaml] casemodel tests 未注入: {e}", flush=True)
        return []