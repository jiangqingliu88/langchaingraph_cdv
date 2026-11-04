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
    """检测是否为时钟端口 —— **判定口径在 `src/tools/common/lib/ports.py`**（共用）。"""
    from src.tools.common.lib.ports import is_clock_port
    return is_clock_port(name)


def _is_reset_port(name: str) -> bool:
    """检测是否为复位端口 —— 同上，别在这里另写一份（两份会漂）。"""
    from src.tools.common.lib.ports import is_reset_port
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
    # AXI 通道信号 = 通道前缀 + **字段名**（awaddr / wdata / bresp / rready）。
    # 旧规则 `^(aw|w|b|ar|r)[a-z]` 把任何以这几个字母开头的词都当 AXI ——
    # 实测 `barrier_type` 被判成 axi，生成只含 1 个端口的 `axi_agent`，
    # 其余端口挤进"方向兜底"，整轮 p0 全挂。
    if re.match(
            r'^(aw|ar|w|b|r)'
            r'(addr|data|valid|ready|resp|last|len|size|burst|id|user|strb|'
            r'lock|cache|prot|qos|region)', n):
        return "axi"
    return "generic"


def _llm_classify_protocols(names: list) -> dict:
    """LLM 按信号名分类 protocol，返回 {name: protocol}；失败返回 {}。"""
    if not names:
        return {}
    try:
        from src.tools.common.lib.llm_call import JSON_OBJECT_SCHEMA, call_llm
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
        raw = (call_llm(prompt, "", "", output_schema=JSON_OBJECT_SCHEMA,
                            output_format="json",
                            prompt_version="protocol-classify-v1") or "").strip()
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
            # 规格里**显式**写了协议：单端口组也可信（人工给的边界）。
            p["_explicit_protocol"] = bool(p["protocol"]
                                           and p["protocol"] != "generic")
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

    # **单端口“协议组”不可信**：LLM 常把个别端口猜成 axi/apb，而同一份
    # spec 里绝大多数端口仍是 generic。放行会生成一个只含 1 个信号的
    # `axi_agent`，把真正的 DUT 端口赶进“方向兜底”——实测导致整轮回归
    # DUT_CHK 求值为 X。规则：非规格显式声明的单端口组，退回 generic。
    if generic_ports:
        demoted = []
        for proto, grp in list(groups.items()):
            if len(grp) != 1 or grp[0].get("_explicit_protocol"):
                continue
            # **不再拿名称分类器当"证据"**：它和 LLM 可能错得一样（`barrier_type`
            # → axi 就是这么漏过去的）。没有规格显式声明时，单端口组一律不可信。
            demoted.append((proto, grp[0]))
            generic_ports.extend(groups.pop(proto))
        for proto, port in demoted:
            print(f"  [find_yaml] 忽略单端口协议猜测 {port['name']}→{proto}"
                  f"（无规格依据，走方向兜底）", flush=True)

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
        from src.tools.common.lib.golden_library import build_ref_model_config

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
                  interfaces: list = None, uvm_yaml_dir: Path = None,
                  with_util: bool = False) -> Any:
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

    # ── pred / scoreboard 契约：**有双向 agent 就必须有 pred** ──
    #
    # in 方向 agent 的 monitor 事务 → pred.in_export
    # pred.out_port（expected）→ scb.expected_export
    # out 方向 agent 的 monitor 事务 → scb.actual_export
    #
    # 没有真实参考模型（verified ModelRegistry / 用户提供的 util_comp.yaml
    # pred）就**硬失败**：不写 env.yaml，避免生成一个"永远 expected=0"的假
    # scoreboard（历史上那会让每条用例假失败）。
    in_agent, out_agent = _io_agents(agent_names, active_by_name)
    reg_model = _registry_model(module_name, agent_names, agents_spec)
    mirror = _ref_mirror_gate(module_name, interfaces or [], registers or [])
    util_str = ""
    #: 只有**生产路径**（传了 uvm_yaml_dir）才强制 pred 契约；
    #: 纯字符串构造（老测试/工具函数）保持旧行为，不在这里硬失败。
    enforce_pred = uvm_yaml_dir is not None
    if in_agent and out_agent and enforce_pred:
        in_item = _seq_item_of_agents(agents_spec, in_agent)
        out_item = _seq_item_of_agents(agents_spec, out_agent)
        pred = _pred_spec(module_name, uvm_yaml_dir, reg_model, mirror,
                          in_item, out_item)
        pred_h = f"{module_name}_pred"
        scb_h = f"{module_name}_scb"
        lines += [
            "  analysis_components:",
            f"    - name: {pred_h}",
            f"      type: {pred['cls']}",
            "  scoreboards:",
            f"    - name: {scb_h}",
            "      sb_type: in_order_scoreboard",
            f"      trans_type: {out_item}",
            f"      params: [{out_item}, {out_item}]",
            "  tlm_connections:",
            f"    - {{ driver: {in_agent}_agent_ap, receiver: {pred_h}.{pred['in_port']} }}",
            f"    - {{ driver: {pred_h}.{pred['out_port']}, receiver: {scb_h}.expected_export }}",
            f"    - {{ driver: {out_agent}_agent_ap, receiver: {scb_h}.actual_export }}",
        ]
        util_str = pred["util_yaml"]
    else:
        lines += ["  scoreboards: []", "  analysis_components: []",
                  "  tlm_connections: []"]

    env_text = "\n".join(lines) + "\n"
    if enforce_pred:
        _validate_env_pred_wiring(env_text, util_str, in_agent, out_agent)
    return (env_text, util_str) if with_util else env_text


def _copy_project_util_comp(uvm_yaml_dir: Path, module_name: str) -> str:
    """把工程级 pred 装配单复制进本轮 run；返回来源路径（没有则空串）。

    查找顺序：`specs/<module>/util_comp.yaml` →
    `config/uvm/<module>_util_comp.yaml`。
    """
    for cand in (Path.cwd() / "specs" / module_name / "util_comp.yaml",
                 Path.cwd() / "config" / "uvm" / f"{module_name}_util_comp.yaml"):
        if cand.is_file():
            (Path(uvm_yaml_dir) / "util_comp.yaml").write_text(
                cand.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8")
            return str(cand)
    return ""


def _io_agents(agent_names, active_by_name):
    """识别进/出方向 agent：优先 `_in`/`_out` 后缀，其次 active/passive。"""
    ins = [n for n in agent_names if str(n).lower().endswith("_in")]
    outs = [n for n in agent_names if str(n).lower().endswith("_out")]
    if ins and outs:
        return ins[0], outs[0]
    active = [n for n in agent_names if active_by_name.get(n)]
    passive = [n for n in agent_names if not active_by_name.get(n)]
    if active and passive:
        return active[0], passive[0]
    return "", ""


def _seq_item_of_agents(agents_spec, agent_name: str) -> str:
    """agent → 事务类型名（用接口名，不用 agent 名：`apb_master` 的接口是 `apb`）。"""
    spec = _spec_agent_of(agents_spec, agent_name)
    iface = str(spec.get("interface") or "") or _iface_name_of(agent_name)
    return f"{iface}_master_seq_item"


def _load_util_pred(uvm_yaml_dir):
    """从 `<run>/inputs/yaml/uvm/util_comp.yaml` 找用户提供的 pred。"""
    if not uvm_yaml_dir:
        return None
    path = Path(uvm_yaml_dir) / "util_comp.yaml"
    try:
        doc = _yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    except (OSError, ValueError):
        return None
    for uc in doc.get("util_components") or []:
        if not isinstance(uc, dict):
            continue
        name = str(uc.get("name") or "").lower()
        typ = str(uc.get("type") or "").lower()
        if "pred" in name or "pred" in typ or "predictor" in typ:
            return uc
    return None


def _pred_ports(uc: dict):
    exps = [p for p in (uc.get("analysis_exports") or []) if isinstance(p, dict)]
    ports = [p for p in (uc.get("analysis_ports") or []) if isinstance(p, dict)]
    if not exps or not ports:
        return None
    return (str(exps[0].get("name") or "in_export"),
            str(exps[0].get("type") or ""),
            str(ports[0].get("name") or "out_port"),
            str(ports[0].get("type") or ""))


def _pred_required_message(module_name, in_item, out_item) -> str:
    return (
        f"双向 agent 需要 pred，但 {module_name} 没有可用参考模型。\n"
        f"  · 在 database/model_registry.db 注册 verified 模型（in={in_item}, "
        f"out={out_item}），或\n"
        f"  · 在 <run>/inputs/yaml/uvm/util_comp.yaml 提供 name/type 含 pred 的 "
        f"util_components，且 analysis_exports[0].type={in_item}、"
        f"analysis_ports[0].type={out_item}。\n"
        f"没有 pred 不生成 env —— 避免 expected 恒 0 的假 scoreboard。"
    )


def _pred_spec(module_name, uvm_yaml_dir, reg_model, mirror,
               in_item, out_item) -> dict:
    """解析/构造 pred 装配：类名 + 端口名 + util_components YAML 文本。"""
    uc = _load_util_pred(uvm_yaml_dir)
    if uc:
        ports = _pred_ports(uc)
        if ports is None:
            raise ValueError(f"util_comp.yaml 的 pred {uc.get('name')} 缺少 "
                             f"analysis_exports/analysis_ports")
        in_name, in_type, out_name, out_type = ports
        if in_type != in_item or out_type != out_item:
            raise ValueError(
                f"util_comp.yaml pred 端口类型不匹配："
                f"in={in_type}（期望 {in_item}）/ out={out_type}（期望 {out_item}）")
        return {"cls": str(uc.get("name")), "in_port": in_name,
                "out_port": out_name,
                "util_yaml": "util_components:\n" + _yaml.safe_dump(
                    [uc], allow_unicode=True, sort_keys=False)}

    if reg_model:
        if (reg_model.get("trans_in") != in_item
                or reg_model.get("trans_out") != out_item):
            raise ValueError(
                f"模型库 {reg_model.get('name')} 的事务类型不匹配："
                f"in={reg_model.get('trans_in')}（期望 {in_item}）/ "
                f"out={reg_model.get('trans_out')}（期望 {out_item}）")
        return {"cls": str(reg_model["name"]), "in_port": "in_export",
                "out_port": "out_port", "util_yaml": _util_component_yaml(reg_model)}

    if mirror:
        if in_item != out_item:
            raise ValueError(
                f"寄存器镜像 predictor 只支持同类型事务（in={in_item}, out={out_item}）")
        block = (
            "util_components:\n"
            f"  - name: {module_name}_pred\n"
            "    type: uvm_component\n"
            "    description: \"寄存器镜像 predictor（写/读同类型事务）\"\n"
            "    analysis_exports:\n"
            f"      - {{ name: in_export, type: {in_item} }}\n"
            "    analysis_ports:\n"
            f"      - {{ name: out_port, type: {out_item} }}\n"
            "    ref_model:\n"
            f"      nregs: {mirror['nregs']}\n"
            f"      addr_w: {mirror['addr_w']}\n"
            f"      data_w: {mirror['data_w']}\n"
            f"      source: '{mirror['source']}'\n")
        return {"cls": f"{module_name}_pred", "in_port": "in_export",
                "out_port": "out_port", "util_yaml": block}

    raise ValueError(_pred_required_message(module_name, in_item, out_item))


def _validate_env_pred_wiring(env_text: str, util_text: str,
                              in_agent: str, out_agent: str) -> None:
    """生成后自检：双向 agent 时 env 必须有 pred + scoreboard + 三条连接。"""
    if not (in_agent and out_agent):
        return
    if not util_text or "pred" not in util_text.lower():
        raise ValueError("env 生成自检失败：util_comp.yaml 缺少 pred")
    try:
        doc = _yaml.safe_load(env_text) or {}
    except ValueError as exc:
        raise ValueError(f"env YAML 自检失败（无法解析）: {exc}")
    env = doc.get("environment") or {}
    pred_h = None
    for item in env.get("analysis_components") or []:
        if isinstance(item, dict) and "pred" in str(item.get("name") or "").lower():
            pred_h = str(item.get("name"))
            break
    if not pred_h:
        raise ValueError("env 生成自检失败：analysis_components 里没有 pred")
    if not env.get("scoreboards"):
        raise ValueError("env 生成自检失败：没有 scoreboard")
    drivers = [str((c or {}).get("driver") or "")
               for c in (env.get("tlm_connections") or []) if isinstance(c, dict)]
    if not any(d == f"{in_agent}_agent_ap" for d in drivers):
        raise ValueError(f"env 生成自检失败：缺少输入连接 {in_agent}_agent_ap → pred")
    if not any(d.startswith(f"{pred_h}.") for d in drivers):
        raise ValueError("env 生成自检失败：缺少 pred.out_port → scoreboard.expected_export")
    if not any(d == f"{out_agent}_agent_ap" for d in drivers):
        raise ValueError(f"env 生成自检失败：缺少输出连接 {out_agent}_agent_ap → scoreboard.actual_export")



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

    **SQL 是库，yaml 是这一轮的装配单** —— 库在 `database/model_registry.db`
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
        "# 库：database/model_registry.db；本文件是**装配单**，不是库。\n"
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
        from src.tools.generation.casemodel_tools.api import run_uvm_tests
        t = run_uvm_tests(cm.read_text(encoding="utf-8"), max_tests=200)
        tests = t.get("tests") or []
        if not tests:
            return []
        out = ["  tests:"]
        for x in tests:
            # `field` = 模型声明的**激励绑定**（维度取值由哪个事务字段承载）。
            # 没声明就不写 —— 空串会被下游当成"已绑定但绑了个空名字"。
            line = ("    - { dimension: %s, value: '%s', key: %s, int_value: %s"
                    % (x.get("dimension"), x.get("value"), x.get("key"),
                       x.get("int_value")))
            if x.get("field"):
                line += ", field: %s" % x["field"]
            # 测试点主键：这条属性 test 对应模型里的哪一条 TP。
            # 回归报告、覆盖率矩阵、签核证据都靠它把三份产物对到一条线上。
            if x.get("tp_id"):
                line += ", tp_id: %s" % x["tp_id"]
            # 后门到达：属性 test 用 uvm_hdl_force 把内部状态摆到目标值。
            if x.get("backdoor_path"):
                line += ", backdoor_path: %s" % x["backdoor_path"]
            # sequence 场景：名字 + 逐笔取值。没有 values 的不写 ——
            # 一个只有名字的场景建立不了可核对的激励差异。
            if x.get("sequence"):
                line += ", sequence: %s" % x["sequence"]
            if x.get("sequence_values"):
                line += ", sequence_values: [%s]" % ", ".join(
                    str(int(v)) for v in x["sequence_values"])
            out.append(line + " }")

        # 批次 test 类（**一条 = 一个批次/专题**）—— 与属性 test 平行的另一条路。
        # 没有它，回归里 `+UVM_TESTNAME=<批次名>` 会撞 UVM_FATAL(INVTST)，
        # 而那条路径被记成 pass（vsim 遇到未知 testname 仍然 exit 0）。
        from src.tools.generation.casemodel_tools.api import run_uvm_batches
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