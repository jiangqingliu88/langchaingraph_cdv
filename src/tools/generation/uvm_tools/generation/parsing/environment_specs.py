"""Normalize environment test and batch declarations from YAML.

These helpers perform shape/type cleanup only. They deliberately do not expand
case-model semantics; that remains the responsibility of the case-model layer.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..models import HarnessModel


def _opt_bool(value: Any) -> Optional[bool]:
    """YAML 布尔（bool 或 "True"/"False" 字符串）→ Optional[bool]；无法解析 → None。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    s = str(value).strip().lower()
    if s in ("true", "1", "yes", "on"):
        return True
    if s in ("false", "0", "no", "off"):
        return False
    return None


def _to_count(value: Any) -> Any:
    """interface 数组大小：数字 → int；否则保留字符串（参数名，如 NUM_CLIENTS）。"""
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return value if value not in (None, "") else 1


def _normalize_harness(data: Dict[str, Any]) -> Optional[HarnessModel]:
    """归一化 harness YAML → HarnessModel。"""
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    if not name:
        return None
    bind_to = data.get("bind_to", "")
    interfaces = []
    for raw in data.get("interfaces") or []:
        if not isinstance(raw, dict) or not raw.get("name") or not raw.get("type"):
            continue
        conns = raw.get("connections") or {}
        if not isinstance(conns, dict):
            conns = {}
        interfaces.append({
            "name": raw["name"],
            "type": raw["type"],
            "agent_path": raw.get("agent_path", raw["name"]),
            "connections": conns,
            "bind_to": raw.get("bind_to", ""),      # 缺省用 harness.bind_to
            "source_path": raw.get("source_path", ""),  # 多实例层级路径（如 cache.memory）
            "count": _to_count(raw.get("count", 1)),
        })
    return HarnessModel(
        name=name,
        bind_to=bind_to,
        parameter=data.get("parameter", ""),
        interfaces=interfaces,
        sub_harnesses=[
            {"path": s.get("path", ""), "env_path": s.get("env_path", "")}
            for s in (data.get("sub_harnesses") or [])
            if isinstance(s, dict) and s.get("path")
        ],
        connect_path=data.get("connect_path", data.get("connect", {}).get("path", "")
                              if isinstance(data.get("connect"), dict) else ""),
    )


def _normalize_tests(raw) -> List[Dict[str, Any]]:
    """归一化 `environment.tests` → `[{dimension, value, key, int_value, base}]`。

    **一条 = 一个 UVM_TEST = 一个属性取值**。这里只做「类型净化 + 丢坏条目」，
    不做取值展开 —— 展开（哪个维度有哪些取值）是 case 属性模型那边的事，
    由它导出成这份清单；渲染器不认识那些语义。

    必填 `dimension` / `value`，缺一个就丢掉（宁可不产这个 test，也不要产一个
    没有属性、名字还重复的类）。`key` / `int_value` / `base` 缺省时留给模板
    过滤器推导（见 `attr_key` / `attr_int_value` / `attr_class_slug`）。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        value = item.get("value")
        if not dimension or value is None or str(value).strip() == "":
            continue
        int_value = item.get("int_value")
        out.append({
            "dimension": dimension,
            "value": str(value),
            "key": str(item.get("key") or "").strip(),
            # 保持 None：「没给」和「给了 0」是两回事，模板过滤器区分处理
            "int_value": int_value if isinstance(int_value, int) else None,
            "base": str(item.get("base") or "").strip(),
            # 激励绑定：事务字段名。空串 = 观测型维度（test 只落 config_db 通道，
            # 不约束事务）。**必须原样透传** —— 下游 sequence 靠它找 `<field>_int`。
            "field": str(item.get("field") or "").strip(),
            # 测试点主键 —— 进生成类的注释，把 test 反查到 TP / 需求 / 覆盖仓。
            "tp_id": str(item.get("tp_id") or "").strip(),
            # 后门到达：层次路径（`uvm_hdl_force` 用）。空 = 普通属性 test。
            "backdoor_path": str(item.get("backdoor_path") or "").strip(),
            # sequence 场景：名字进注释，`sequence_values` 逐笔驱动事务。
            # **没有 values 就不是可执行场景** —— 模板会如实标注，不假装。
            "sequence": str(item.get("sequence") or "").strip(),
            "sequence_values": [int(v) for v in (item.get("sequence_values") or [])
                                if isinstance(v, (int, float))],
        })
    return out


def _normalize_batches(raw) -> List[Dict[str, Any]]:
    """`environment.batches` → `[{name, theme, dimensions, method, policy, priority, checks}]`。

    必填 `name`（= test 类名），缺了就丢掉 —— 一个没名字的 test 类生成不出来。
    其余键缺省给空串（模板按空串渲染，不炸）。

    `policy` 是**约束策略类名**（由 case 模型推出来的那个），批次 test 类把它
    set 进 config_db 给 sequence 用。缺省空串 = 这一批没有模型给的约束。

    与 `_normalize_tests` 同一套纪律：**只做类型净化，不做语义展开** ——
    "哪个批次打哪几个维度"是 case 模型那边的事，这里不认识。
    """
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "theme": str(item.get("theme") or "").strip(),
            "dimensions": str(item.get("dimensions") or "").strip(),
            "method": str(item.get("method") or "").strip(),
            "policy": str(item.get("policy") or "").strip(),
            "priority": str(item.get("priority") or "").strip(),
            "checks": str(item.get("checks") or "").strip(),
        })
    return out


def _normalize_scoreboards(scoreboards):
    """归一化 scoreboards → list[{name, sb_type, trans_type, params, handle_type, typedef_decl}]。

    scoreboards:
      - name: apb_scb
        sb_type: uvmf_in_order_scoreboard   # 工厂可注册的具名类
        trans_type: apb_master_seq_item
      # 参数化类（如 scb_pkg 的 in_order_scoreboard#(REQ_T, RSP_T, CMP_T)）：
      # 给 params 传实参，句柄走 typedef 出来的别名
      - name: apb_scb_param
        sb_type: in_order_scoreboard
        trans_type: apb_master_seq_item
        params: [apb_master_seq_item, apb_master_seq_item]

    注：生成式（mode/expected_from/actual_from 自造计分板）已下线 ——
    scb 文件不再由本工具生成，一律由 sb_type 指向外部类。
    """
    normalized = []
    for sb in scoreboards or []:
        if not isinstance(sb, dict) or not sb.get("name"):
            continue
        name = sb["name"]
        sb_type = sb.get("sb_type", "")
        params = [str(p) for p in (sb.get("params") or [])]
        # 参数化类不能直接当类型名用（`in_order_scoreboard apb_scb;` 编译不过），
        # 故先 `typedef <类>#(<实参>) <name>_t;` 出别名，再用别名声明/例化句柄。
        typedef_decl = (f"typedef {sb_type}#({', '.join(params)}) {name}_t;"
                        if params and sb_type else "")
        normalized.append({
            "name": name,
            "sb_type": sb_type,
            "trans_type": sb.get("trans_type", ""),
            "params": params,
            "handle_type": f"{name}_t" if params else sb_type,
            "typedef_decl": typedef_decl,
        })
    return normalized


def _normalize_typedefs(raw) -> Dict[str, str]:
    """typedefs → 保序 Dict[类型名, 类型表达式]。

    每项一个 object，两个字段：
        type_t    类型表达式（typedef 右边）
        type_name 新类型名  （typedef 左边）
        - { type_t: "bit [7:0]", type_name: "byte_t" }  →  typedef bit [7:0] byte_t;

    保序：写在前面的先声明，故后面的 typedef 可以引用它。
    """
    out: Dict[str, str] = {}
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        name = item.get("type_name")
        if name is None or str(name) == "":
            continue
        ty = item.get("type_t")
        out[str(name)] = "" if ty is None else str(ty)
    return out


def _normalize_agents_list(agents):
    """把 agents 归一化为 list[dict]，兼容 dict（旧）与 list（新）两种格式。

    dict 格式:  { name: {interface, clock, ...} }
    list 格式:  [ {name, type, interface, clock, ...} ]
    """
    if not agents:
        return []
    if isinstance(agents, dict):
        items = []
        for k, v in agents.items():
            if isinstance(v, dict):
                items.append({"name": k, **v})
            elif isinstance(v, str):
                items.append({"name": k, "interface": v})
            else:
                items.append({"name": k})
        return items
    if isinstance(agents, list):
        result = []
        for a in agents:
            if not isinstance(a, dict):
                continue
            a = dict(a)
            if not a.get("name"):
                # name 缺省从 type 推导："apb_master_agent" → "apb_master"
                t = a.get("type", "")
                a["name"] = t[:-len("_agent")] if t.endswith("_agent") else t
            # `interface` 缺省从 name 推导：**一个接口出 master/slave 两个 agent**
            #（见 interface yaml 的头注释），所以接口名 = agent 名去掉 `_master`/`_slave`。
            #
            # 这一步不做的话，env 模板里的 `import {{ agent.interface }}_pkg::*`
            # 会退化成 agent 自己的名字 —— 生成 `import apb_master_pkg::*`，
            # 而真实的包叫 `apb_pkg`。于是 env/cfg 里**每一个**跨包类型都变成
            # "Invalid type"，一屏连带错误，根因却只是这一处。
            if not a.get("interface"):
                _n = str(a.get("name", ""))
                for _suffix in ("_master", "_slave"):
                    if _n.endswith(_suffix):
                        _n = _n[: -len(_suffix)]
                        break
                a["interface"] = _n
            result.append(a)
        return result
    return []


def _normalize_analysis_ports(entries):
    """归一化 analysis_exports/analysis_ports → list[{name, type, connected_to}]。

    事务类型兼容 type 与 trans_type 两种键名；缺省 type = uvm_sequence_item。
    """
    result = []
    for e in entries or []:
        if not isinstance(e, dict) or not e.get("name"):
            continue
        result.append({
            "name": e["name"],
            "type": e.get("type") or e.get("trans_type", "") or "uvm_sequence_item",
            "connected_to": e.get("connected_to", ""),
        })
    return result


def _normalize_analysis_components(components):
    """归一化 analysis_components → list[{name, type}]。type 缺省 = name。"""
    result = []
    for c in components or []:
        if not isinstance(c, dict):
            continue
        name = c.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": c.get("type", name),
        })
    return result


def _normalize_vipenvs(vipenvs):
    """归一化 vipenvs → list[{name, type, vip_path}]（外部 VIP 环境集成）。"""
    result = []
    for ve in vipenvs or []:
        if not isinstance(ve, dict):
            continue
        name = ve.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": ve.get("type", name),
            "vip_path": ve.get("vip_path", ""),
        })
    return result


def _normalize_subenvs(subenvs):
    """归一化 subenvs → list[{name, type}]。

    subenvs:
      - name: "apb_sys_env"        # 实例名
        type: "apb_system_env"     # 环境类名（缺省 = name）
    """
    result = []
    for se in subenvs or []:
        if not isinstance(se, dict):
            continue
        name = se.get("name")
        if not name:
            continue
        result.append({
            "name": name,
            "type": se.get("type", name),
        })
    return result


def _ral_role(name: str, item: Dict[str, Any]) -> str:
    """旧列表风格：显式 role 字段优先，否则按 name 识别。"""
    if item.get("role"):
        r = str(item["role"]).lower()
        if "predictor" in r or r.startswith("pred"):
            return "predictor"
        if "adapter" in r:
            return "adapter"
        return "reg_block"
    n = str(name).lower()
    if "predictor" in n or n.startswith("pred"):
        return "predictor"
    if "adapter" in n:
        return "adapter"
    return "reg_block"


def _resolve_bus_agent(item: Dict[str, Any], agents: List[Any]) -> Tuple[str, bool]:
    """bus 条目 → (env agent 名, 是否匹配)。

    type 匹配 agent_type/name > bus_name 匹配 name > 回退第一个 agent。
    多个候选时优先 is_master=True 的实例（如 master/slave 同 type 时选 master）。
    """
    itype = item.get("type") or ""
    bus_name = item.get("bus_name") or ""
    if itype:
        candidates = [a for a in agents
                      if getattr(a, "agent_type", "") == itype
                      or getattr(a, "name", "") == itype]
        if candidates:
            for a in candidates:
                if getattr(a, "is_master", None) is True:
                    return a.name, True
            return candidates[0].name, True
    if bus_name:
        for a in agents:
            if getattr(a, "name", "") == bus_name:
                return a.name, True
    return (agents[0].name if agents else ""), False


def _finalize_ral(components: List[Dict[str, Any]], agents: List[Any],
                  bus_agent: str = "", bus_matched: bool = False,
                  bus_entry_seen: bool = False) -> Dict[str, Any]:
    rm = {
        "components": components,
        # 总线 agent（env 实例名，如 apb_master）：default_map.set_sequencer 与 predictor 连接使用
        "bus_agent": bus_agent or (agents[0].name if agents else ""),
        # 供 SemanticValidator 检测 bus 条目未匹配到任何 agent
        "bus_matched": bus_matched,
        "bus_entry_seen": bus_entry_seen,
    }
    for role in ("reg_block", "adapter", "predictor"):
        rm[role] = next((c for c in components if c["role"] == role), None)
    pkgs: List[str] = []
    for c in components:
        if c["pkg"] and c["pkg"] not in pkgs:
            pkgs.append(c["pkg"])
    rm["pkgs"] = pkgs
    return rm


def _normalize_register_model(raw: Any, agents: List[Any]) -> Dict[str, Any]:
    """归一化 register_model → RAL 组件列表（env 模板渲染用）。

    用户 key 字段风格（当前）:
      register_model:
        - bus_name: "apb"                  # 总线 agent（type 匹配 env agents）
          type: "apb_master_agent"
        - reg_block_name: "reg_block"      # uvm_reg_block（实例名 + 类名）
          type: "regblock_t"
        - reg_adpater_name: "adapter"      # uvm_reg_adapter（reg_adapter_name 亦兼容）
          type: "my_adapter"
        - predictor_name: "predictor"      # uvm_reg_predictor
          type: "my_bus_predictor"         #   预测器类（缺省 = uvm_reg_predictor）
          trans_type: "my_bus_trans"       #   总线事务类（缺省 = type）
      type 可为 "pkg::class" 或配 pkg 字段（env_pkg 自动 import）。

    兼容旧列表风格（name 识别角色）与旧 dict 格式（reg_block_class/...）。
    """
    # 解包嵌套: register_model: {reg_adapter: [...]}
    if isinstance(raw, dict):
        for nested_key in ("reg_adapter", "reg_adpater"):
            nested = raw.get(nested_key)
            if isinstance(nested, list):
                raw = nested
                break

    def _mk(name: str, itype: str, role: str, pkg: str = "",
            trans_type: str = "") -> Dict[str, Any]:
        entry = {"name": name, "type": itype, "role": role, "pkg": pkg}
        if role == "predictor":
            entry["trans_type"] = trans_type or itype or "uvm_sequence_item"
        return entry

    # 列表 → components
    if isinstance(raw, list):
        components = []
        bus_agent = ""
        bus_matched = False
        bus_entry_seen = False
        for item in raw:
            if not isinstance(item, dict):
                continue
            itype = item.get("type") or ""
            pkg = item.get("pkg", "")
            if not pkg and isinstance(itype, str) and "::" in itype:
                pkg = itype.split("::", 1)[0]
            # 用户 key 字段风格
            if item.get("bus_name") is not None:
                bus_entry_seen = True
                bus_agent, bus_matched = _resolve_bus_agent(item, agents)
            elif item.get("reg_block_name"):
                components.append(_mk(item["reg_block_name"], itype, "reg_block", pkg))
            elif item.get("reg_adpater_name") or item.get("reg_adapter_name"):
                components.append(_mk(item.get("reg_adpater_name") or item.get("reg_adapter_name"),
                                      itype, "adapter", pkg))
            elif item.get("predictor_name"):
                components.append(_mk(item["predictor_name"],
                                      itype or "uvm_reg_predictor", "predictor", pkg,
                                      item.get("trans_type", "")))
            elif item.get("name"):
                # 旧列表风格（name 识别角色）：predictor 的 type 即总线事务类
                role = _ral_role(item["name"], item)
                if role == "predictor":
                    components.append(_mk(item["name"], "uvm_reg_predictor", "predictor",
                                          pkg, item.get("trans_type", "") or itype))
                else:
                    components.append(_mk(item["name"], itype, role, pkg))
        return _finalize_ral(components, agents, bus_agent, bus_matched, bus_entry_seen)

    # 旧 dict 格式 → components
    if isinstance(raw, dict) and raw.get("reg_block_class"):
        def _bool(value: Any, default: bool) -> bool:
            if isinstance(value, bool):
                return value
            if value is None:
                return default
            return str(value).strip().lower() in ("true", "1", "yes", "on")

        default_agent = agents[0].name if agents else ""
        components = [{
            "name": "reg_model",
            "type": f"{raw['reg_model_package']}::{raw['reg_block_class']}"
                    if raw.get("reg_model_package") else raw["reg_block_class"],
            "role": "reg_block",
            "pkg": raw.get("reg_model_package", ""),
        }]
        if _bool(raw.get("use_adapter"), True) and raw.get("reg_adapter_class"):
            components.append({
                "name": "adapter",
                "type": raw["reg_adapter_class"],
                "role": "adapter",
                "pkg": "",
            })
        if _bool(raw.get("use_explicit_prediction"), False) and default_agent:
            components.append({
                "name": "predictor",
                "type": "uvm_reg_predictor",
                "trans_type": f"{default_agent}_seq_item",
                "role": "predictor",
                "pkg": "",
            })
        return _finalize_ral(components, agents)

    return {}


def _with_system_type_name(raw: Dict[str, Any]) -> Dict[str, Any]:
    """bench.interfaces[] 的一项 → 补齐 `system_type_name`。

    每个接口都有个配套的"系统接口" `<x>_system_if`（agent 包里的
    `interface_system.j2` 生成：里面是 `virtual <x>_if master_if[15:0]` 这类
    句柄数组，供 system env 把接口分发给多个 agent 实例）。

    **它必须被实例化**：agent 包的 `<x>_system_env.sv` / `<x>_system_monitor.sv`
    里写着 `uvm_config_db#(virtual <x>_system_if)::get(...)`。Questa 在
    **load 阶段**会对设计中出现过的 virtual interface 类型做解析，设计里找不到
    该接口的**任何实例**就报
      "(vsim-8451) Virtual interface resolution cannot find a matching instance"
    —— **整个设计加载不了**，哪怕那两个组件根本没被例化过。
    所以 tb_top 会实例化它并向 master_if/slave_if 数组挂上真实句柄。
    """
    entry = dict(raw)
    type_name = str(entry.get("type_name") or "")
    if type_name.endswith("_if") and not entry.get("system_type_name"):
        entry["system_type_name"] = type_name[: -len("_if")] + "_system_if"
    return entry
