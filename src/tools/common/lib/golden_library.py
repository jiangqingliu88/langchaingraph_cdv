"""
黄金参考模型库加载器 —— model agent 的"真实模型"来源。

设计原则（见 docs/design/golden_model_library.md）：
  1. 入库必须验证（scripts/model_library_verify.py 定向仿真 matched==N && mismatched==0）
  2. LLM 只做"选模型 + 参数化"，不现场写功能逻辑
  3. 无匹配 → 诚实占位（audit 拒绝签核），禁止静默降级为模板

用法:
    from src.tools.common.lib.golden_library import match_golden, load_golden
    hit = match_golden(design_arch)          # → {"ip","version","path","sha256","params"} 或 None
    sv = load_golden(hit["ip"], hit["version"])
    sv = parameterize(sv, module_name, hit["params"])
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

# 库根目录（仓库内，git 版本化）
LIBRARY_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent / "model_library"

# ═══════════════════════════════════════════════════════════════
# 内置黄金模型（**兼容层，不是新的真相源**）
# ═══════════════════════════════════════════════════════════════
#
# `model_library/` 已删除，但 `match_golden` / `build_ref_model_config`
# 仍是 bench 接线与历史测试的入口。真值源正在迁到 SQL `ModelRegistry`
# （TLM 1.0），在这之前这些内置模板保证：
#   · 没有磁盘库时**行为可核**（返回值、sha256、manifest 都是确定的）；
#   · **不是 verified** —— 内置只代表"签名一致"，不代表"EDA 验过"。
# 磁盘上若有 `model_library/<ip>/v1/`，永远优先（它可以被验证脚本改状态）。
_BUNDLED_MODELS: Dict[str, Dict[str, Any]] = {
    "apb_slave": {
        "model_sv": """\
// Bundled APB slave golden model (signal level, compatibility only)
module apb_slave_golden #(
    parameter int NREGS = 16,
    parameter int ADDR_W = 8,
    parameter int DATA_W = 8
) (
    input  logic                 clk,
    input  logic                 rst_n,
    input  logic [ADDR_W-1:0]    paddr,
    input  logic [DATA_W-1:0]    pwdata,
    input  logic                 pwrite,
    input  logic                 psel,
    input  logic                 penable,
    output logic [DATA_W-1:0]    prdata
);
    logic [DATA_W-1:0] regs [0:NREGS-1];

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            for (int i = 0; i < NREGS; i++) regs[i] <= '0;
        end else if (psel && penable && pwrite) begin
            if (int'(paddr) < NREGS) regs[paddr] <= pwdata;
        end
    end

    always_comb begin
        prdata = '0;
        if (psel && !pwrite && int'(paddr) < NREGS) prdata = regs[paddr];
    end
endmodule
""",
    },
    "uart_tx": {
        "model_sv": """\
// Bundled UART TX golden model (compatibility only)
module uart_tx_golden #(
    parameter int DATA_BITS = 8,
    parameter int BAUD_DIV = 10416
) (
    input  logic clk,
    input  logic rst_n,
    input  logic tx_start,
    input  logic [DATA_BITS-1:0] tx_data,
    output logic tx,
    output logic tx_busy
);
    assign tx = 1'b1;
    assign tx_busy = 1'b0;
endmodule
""",
    },
    "uart_rx": {
        "model_sv": """\
// Bundled UART RX golden model (compatibility only)
module uart_rx_golden #(
    parameter int DATA_BITS = 8,
    parameter int BAUD_DIV = 10416
) (
    input  logic clk,
    input  logic rst_n,
    input  logic rx,
    output logic [DATA_BITS-1:0] rx_data,
    output logic rx_valid
);
    assign rx_data = '0;
    assign rx_valid = 1'b0;
endmodule
""",
    },
    "fifo16": {
        "model_sv": """\
// Bundled FIFO golden model (compatibility only)
module fifo16_golden #(parameter int DATA_W = 8, parameter int DEPTH = 16) (
    input  logic clk,
    input  logic rst_n,
    input  logic wr_en,
    input  logic rd_en,
    input  logic [DATA_W-1:0] wdata,
    output logic [DATA_W-1:0] rdata,
    output logic full,
    output logic empty
);
    assign rdata = '0;
    assign full  = 1'b0;
    assign empty = 1'b1;
endmodule
""",
    },
    "irq_gen": {
        "model_sv": """\
// Bundled interrupt generator golden model (compatibility only)
module irq_gen_golden #(parameter int N = 4) (
    input  logic clk,
    input  logic rst_n,
    input  logic [N-1:0] irq_src,
    input  logic [N-1:0] irq_en,
    output logic irq
);
    assign irq = |(irq_src & irq_en);
endmodule
""",
    },
}


def _bundled_model(ip: str) -> Optional[Dict[str, Any]]:
    return _BUNDLED_MODELS.get(ip)

# 各黄金模型的 spec 匹配规则（协议关键词 → 需要出现在 interfaces 协议/名字中）
_MATCH_RULES: Dict[str, Dict[str, Any]] = {
    "apb_slave": {
        "protocol_keywords": ("apb",),
        "name_keywords": ("paddr", "pwdata", "prdata", "psel", "penable", "pwrite"),
        "require_registers": False,   # APB 从机语义与寄存器表无关（通用读写回读）
    },
    "uart_tx": {
        "protocol_keywords": ("uart", "serial"),
        "name_keywords": ("tx", "txd", "sout"),
        "require_registers": False,
    },
    "uart_rx": {
        "protocol_keywords": ("uart", "serial"),
        "name_keywords": ("rx", "rxd", "sin"),
        "require_registers": False,
    },
    "fifo16": {
        "protocol_keywords": (),
        "name_keywords": ("fifo", "wr_en", "rd_en", "wdata", "rdata"),
        "require_registers": False,
    },
    "irq_gen": {
        "protocol_keywords": ("intr", "irq", "interrupt"),
        "name_keywords": ("irq", "intr", "irq_src", "irq_en", "irq_pending"),
        "require_registers": False,
    },
}


def _lib_path(ip: str, version: str) -> Optional[Path]:
    p = LIBRARY_ROOT / ip / version / "model.sv"
    return p if p.exists() else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _bundled_sha256(ip: str) -> str:
    m = _bundled_model(ip)
    return (hashlib.sha256(m["model_sv"].encode("utf-8")).hexdigest()
            if m else "")


def match_golden(design_arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按 design_arch（interfaces/registers）匹配黄金模型库。

    返回 {"ip", "version", "path", "sha256", "params"}；无匹配返回 None（诚实占位）。
    """
    interfaces = design_arch.get("interfaces", []) or []
    protos = {str(i.get("protocol", "")).lower() for i in interfaces if isinstance(i, dict)}
    names = {str(i.get("name", "")).lower() for i in interfaces if isinstance(i, dict)}

    for ip, rule in _MATCH_RULES.items():
        # 协议匹配：任一协议关键词命中
        proto_hit = bool(protos & set(rule["protocol_keywords"]))
        # 名字匹配：任一信号名关键词命中
        name_hit = any(any(k in n for k in rule["name_keywords"]) for n in names)
        if not (proto_hit or name_hit):
            continue
        # 找 active 版本：磁盘库优先，没有就走内置兼容层。
        active = _active_version(ip)
        if not active:
            continue
        path = _lib_path(ip, active)
        params = _params_from_spec(ip, design_arch)
        if path:
            return {"ip": ip, "version": active, "path": str(path),
                    "sha256": _sha256(path), "params": params,
                    "verified": bool(verify_manifest(ip, active).get("verified", False)),
                    "source": "disk"}
        if _bundled_model(ip):
            return {"ip": ip, "version": "v1", "path": "",
                    "sha256": _bundled_sha256(ip), "params": params,
                    "verified": bool(verify_manifest(ip, "v1").get("verified", False)),
                    "source": "bundled"}
    return None


def _active_version(ip: str) -> Optional[str]:
    """active 版本：磁盘 `INDEX.yaml`/`v*` 优先；没有磁盘库时内置层给 `v1`。

    **内置层不冒充 verified**：`verify_manifest` 对它恒返回
    `verified=False`，直到有人把它写进 SQL `ModelRegistry` 并跑过 EDA 验证。
    """
    idx = LIBRARY_ROOT / "INDEX.yaml"
    if idx.exists():
        try:
            import yaml
            data = yaml.safe_load(idx.read_text(encoding="utf-8"))
            active = (data.get(ip) or {}).get("active")
            if active:
                return active
        except Exception:
            pass
    if (LIBRARY_ROOT / ip).exists():
        vers = sorted(d.name for d in (LIBRARY_ROOT / ip).glob("v*"))
        if vers:
            return vers[-1]
    return "v1" if _bundled_model(ip) else None


def _params_from_spec(ip: str, design_arch: Dict[str, Any]) -> Dict[str, Any]:
    """从 spec 接口表提取参数（ADDR_W/DATA_W/NREGS）。"""
    if ip != "apb_slave":
        return {}
    interfaces = design_arch.get("interfaces", []) or []
    data_w = 8
    addr_w = 8
    nregs = 16
    for i in interfaces:
        if not isinstance(i, dict):
            continue
        name = str(i.get("name", "")).lower()
        try:
            w = int(i.get("data_width", 1) or 1)
        except (TypeError, ValueError):
            continue
        if "paddr" in name:
            addr_w = max(addr_w, w)
        elif "pwdata" in name or "prdata" in name:
            data_w = max(data_w, w)
    # NREGS：寄存器表行数（有则用之，无则按地址空间 2^ADDR_W 截断到 256）
    regs = design_arch.get("registers", []) or []
    if regs:
        nregs = max(1, min(256, len(regs)))
    else:
        nregs = max(1, min(256, 1 << addr_w))
    return {"NREGS": nregs, "ADDR_W": addr_w, "DATA_W": data_w}


def load_golden(ip: str, version: str) -> str:
    """读取黄金模型 SV 源码（磁盘库优先，其次内置兼容层）。

    两处都找不到才抛 —— 不返回空串：一份空模型会让下游渲染出空壳，
    而"没有模型"与"模型是空的"必须能分辨。
    """
    path = _lib_path(ip, version)
    if path:
        return path.read_text(encoding="utf-8")
    m = _bundled_model(ip)
    if m:
        return m["model_sv"]
    raise FileNotFoundError(f"黄金模型不存在: model_library/{ip}/{version}/model.sv")


def parameterize(sv_code: str, module_name: str, params: Dict[str, Any]) -> str:
    """黄金模型 → {module}_ref_model：替换模块名 + 更新 parameter 默认值。

    实际参数绑定发生在 bench 实例化处（golden_ref.params 记录应绑定的值）；
    这里只把 definition 的 parameter 默认值设为 spec 推导值（合法 SV，实例化仍可覆盖）。
    """
    text = re.sub(r"module\s+\w+", f"module {module_name}_ref_model", sv_code, count=1)
    for k, v in (params or {}).items():
        text = re.sub(rf"(parameter\s+int\s+{re.escape(k)}\s*=\s*)\d+",
                      lambda m, _v=v: f"{m.group(1)}{_v}", text, count=1)
    return text


def verify_manifest(ip: str, version: str) -> Dict[str, Any]:
    """读取黄金模型 manifest（含 sha256 / verified 标记）。

    没有磁盘 manifest 时返回内置层的**未验证**声明 —— 内置模板只说明
    "签名字典里有它"，不说明"EDA 验过它"。`verified` 永远 False，
    除非磁盘库或 SQL `ModelRegistry` 明确把它升为 verified。
    """
    mp = LIBRARY_ROOT / ip / version / "manifest.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            return {}
    m = _bundled_model(ip)
    if not m:
        return {}
    return {
        "ip": ip,
        "version": version,
        "sha256": _bundled_sha256(ip),
        "verified": False,
        "source": "bundled",
        "note": "内置兼容层；要作为签核比对依据，必须先写进 ModelRegistry 并完成 EDA 验证",
    }


# ═══════════════════════════════════════════════════════════
# bench 接入（tb_top 真实实例化比对）——参考模型端口 → DUT 信号解析
# ═══════════════════════════════════════════════════════════

# ref_port → 解析规则（先按信号名关键词，再按协议；clock/reset 用协议）
_GOLDEN_PORT_MAP: Dict[str, Dict[str, Dict[str, Any]]] = {
    "apb_slave": {
        "clk":     {"names": ("clk", "pclk"), "protocol": ("clock", "clk")},
        "rst_n":   {"names": ("rst_n", "preset_n", "rst"), "protocol": ("reset", "rst")},
        "paddr":   {"names": ("paddr",), "protocol": ()},
        "pwdata":  {"names": ("pwdata",), "protocol": ()},
        "prdata":  {"names": ("prdata",), "protocol": ()},
        "pwrite":  {"names": ("pwrite",), "protocol": ()},
        "psel":    {"names": ("psel",), "protocol": ()},
        "penable": {"names": ("penable",), "protocol": ()},
    },
    "uart_tx": {
        "clk":     {"names": ("clk",), "protocol": ("clock", "clk")},
        "rst_n":   {"names": ("rst_n", "preset_n", "rst"), "protocol": ("reset", "rst")},
        "tx":      {"names": ("tx", "txd", "sout"), "protocol": ()},
    },
    "uart_rx": {
        "clk":     {"names": ("clk",), "protocol": ("clock", "clk")},
        "rst_n":   {"names": ("rst_n", "preset_n", "rst"), "protocol": ("reset", "rst")},
        "rx":      {"names": ("rx", "rxd", "sin"), "protocol": ()},
    },
    "fifo16": {
        "clk":     {"names": ("clk",), "protocol": ("clock", "clk")},
        "rst_n":   {"names": ("rst_n", "preset_n", "rst"), "protocol": ("reset", "rst")},
        "wdata":   {"names": ("wdata", "tx_data", "din"), "protocol": ()},
        "rdata":   {"names": ("rdata", "rx_data", "dout"), "protocol": ()},
    },
    "irq_gen": {
        "clk":     {"names": ("clk",), "protocol": ("clock", "clk")},
        "rst_n":   {"names": ("rst_n", "preset_n", "rst"), "protocol": ("reset", "rst")},
        "irq":     {"names": ("irq", "intr"), "protocol": ()},
    },
}

# 每个黄金模型可逐拍比对的 DUT 输出端口（参考模型输出 vs DUT 输出）
_GOLDEN_COMPARE_OUTPUTS: Dict[str, list] = {
    "apb_slave": ["prdata"],
    "uart_tx": [],
    "uart_rx": [],
    "fifo16": ["rdata"],
    "irq_gen": ["irq"],
}


def _resolve_dut_port(interfaces: list, rule: Dict[str, Any]) -> Optional[str]:
    """按规则从规范接口列表解析 DUT 信号名：名字关键词优先，其次协议（clock/reset）。

    返回去位宽后缀的信号名（paddr[7:0] → paddr），保证 tb_top 端口连接是合法 SV。
    """
    def _base(name: str) -> str:
        return str(name).split("[")[0]

    # 1. 名字关键词
    for i in interfaces:
        nm = str(i.get("name", "")).lower()
        if any(k in nm for k in rule.get("names", ())):
            return _base(i.get("name", ""))
    # 2. 协议（仅当该协议在接口中唯一时使用——避免多个 APB 信号全部匹配到第一个）
    proto_hits = [i for i in interfaces
                  if str(i.get("protocol", "")).lower() in rule.get("protocol", ())]
    if len(proto_hits) == 1:
        return _base(proto_hits[0].get("name", ""))
    return None


def build_ref_model_config(module_name: str, interfaces: list,
                           registers: list = None) -> Optional[Dict[str, Any]]:
    """为 bench.yaml 生成 ref_model 接入配置（黄金模型命中时）。

    interfaces: 规范列表 [{name, direction, protocol}]。
    返回 {"enabled", "module", "golden", "port_map", "compare_outputs"} 或 None（无命中）。
    复合参考模型（APB+UART 多黄金 IP 实例化）可接线时优先，否则单黄金模型。
    """
    design_arch = {"module_name": module_name, "interfaces": interfaces,
                   "registers": registers or []}
    hit = match_golden(design_arch)
    if not hit:
        return None
    meta = _GOLDEN_PORT_MAP.get(hit["ip"])
    if not meta:
        return None
    port_map = []
    for ref_port, rule in meta.items():
        dut_port = _resolve_dut_port(interfaces, rule)
        if dut_port:
            port_map.append({"ref_port": ref_port, "dut_port": dut_port})
    if not port_map:
        return None
    compare_outputs = list(_GOLDEN_COMPARE_OUTPUTS.get(hit["ip"], []))

    # ── 复合参考模型：APB+UART 设计且寄存器表可接线 → 扩展端口映射与比对输出 ──
    plan = _composite_plan(interfaces, registers)
    if plan:
        extra_map = {
            "tx":  _resolve_dut_port(interfaces, {"names": ("tx", "txd", "sout"), "protocol": ()}),
            "rx":  _resolve_dut_port(interfaces, {"names": ("rx", "rxd", "sin"), "protocol": ()}),
            "irq": _resolve_dut_port(interfaces, {"names": ("irq", "intr"), "protocol": ()}),
        }
        for ref_port, dut_port in extra_map.items():
            if dut_port and not any(m["ref_port"] == ref_port for m in port_map):
                port_map.append({"ref_port": ref_port, "dut_port": dut_port})
        for out in ("tx", "irq"):
            if extra_map.get(out) and out not in compare_outputs:
                compare_outputs.append(out)
        return {
            "enabled": True,
            "module": f"{module_name}_ref_model",
            "golden": {"ip": "composite",
                       "parts": ["apb_slave", "uart_tx", "uart_rx"]
                                + (["irq_gen"] if plan.get("irq_reg") else [])},
            "port_map": port_map,
            "compare_outputs": compare_outputs,
        }
    return {
        "enabled": True,
        "module": f"{module_name}_ref_model",
        "golden": {"ip": hit["ip"], "version": hit["version"]},
        "port_map": port_map,
        "compare_outputs": compare_outputs,
    }


# ═══════════════════════════════════════════════════════════
# 复合参考模型：APB 寄存器 + uart_tx + uart_rx（寄存器名驱动接线）
# ═══════════════════════════════════════════════════════════

def _classify_register(reg: dict) -> str:
    """按寄存器名分类角色：tx_data/rx_data/irq_en/baud/status/other。"""
    name = str(reg.get("name", "")).lower()
    if "irq" in name or "intr" in name:
        return "irq_en" if any(k in name for k in ("en", "enable", "mask")) else "irq_status"
    if "baud" in name:
        return "baud"
    if "status" in name or "state" in name:
        return "status"
    if "tx" in name or "tdata" in name:
        return "tx_data"
    if "rx" in name or "rdata" in name:
        return "rx_data"
    return "other"


def _composite_plan(interfaces: list, registers: list) -> Optional[Dict[str, Any]]:
    """判断能否生成复合参考模型（诚实接线前提：寄存器表 + tx_data/rx_data 寄存器）。"""
    regs = [r for r in (registers or []) if isinstance(r, dict) and r.get("name")]
    if not regs:
        return None
    roles = {}
    for r in regs:
        roles.setdefault(_classify_register(r), r)
    tx_reg, rx_reg = roles.get("tx_data"), roles.get("rx_data")
    if not (tx_reg and rx_reg):
        return None  # 无 tx/rx 数据寄存器 → 无法接线 uart，回退单模型
    data_w, addr_w = 8, 8
    for i in (interfaces or []):
        if not isinstance(i, dict):
            continue
        nm = str(i.get("name", "")).lower()
        try:
            w = int(i.get("data_width", i.get("width", 1)) or 1)
        except (TypeError, ValueError):
            continue
        if "paddr" in nm:
            addr_w = max(addr_w, w)
        elif "pwdata" in nm or "prdata" in nm:
            data_w = max(data_w, w)
    return {"regs": regs, "roles": roles, "tx_reg": tx_reg, "rx_reg": rx_reg,
            "irq_reg": roles.get("irq_en"), "data_w": data_w, "addr_w": addr_w}


def build_composite_ref_model(module_name: str, interfaces: list,
                              registers: list) -> Optional[str]:
    """生成复合参考模型 SV（APB 寄存器 + uart_tx + uart_rx + 可选 irq_gen 接线）。

    端口使用黄金风格名（clk/rst_n/paddr/.../tx/rx/irq），与 bench ref_model 端口映射兼容。
    仅当 _composite_plan 可诚实接线时返回 SV；否则 None（回退单黄金模型）。
    """
    plan = _composite_plan(interfaces, registers)
    if not plan:
        return None
    regs, roles = plan["regs"], plan["roles"]
    tx_reg, rx_reg = plan["tx_reg"], plan["rx_reg"]
    irq_reg = plan["irq_reg"]
    data_w, addr_w = plan["data_w"], plan["addr_w"]

    def _reg_name(r: dict) -> str:
        return str(r["name"]).replace(" ", "_").lower()

    # 寄存器状态声明 + 读写 case（RO 寄存器不生成写分支）
    state_lines, write_case, read_case = [], [], []
    for r in regs:
        rn = _reg_name(r)
        try:
            w = int(r.get("width", data_w) or data_w)
        except (TypeError, ValueError):
            w = data_w
        offset = str(r.get("offset", "0x00"))
        access = str(r.get("access", "RW")).upper()
        state_lines.append(f"    logic [{w - 1}:0] reg_{rn} = '0;  // {offset} {access}")
        if access != "RO":
            write_case.append(f"          {offset}: reg_{rn} <= pwdata;")
        read_case.append(f"          {offset}: prdata = reg_{rn};")

    tx_name = _reg_name(tx_reg)
    rx_name = _reg_name(rx_reg)
    tx_offset = str(tx_reg.get("offset", "0x00"))
    rx_offset = str(rx_reg.get("offset", "0x00"))

    # 预计算复位赋值（避免嵌套 f-string 转义，Python 3.11 限制）
    reset_assigns = "\n".join(
        f"            reg_{_reg_name(r)} <= '0;" for r in regs)

    # 可选：irq_en 寄存器门控
    irq_gate = ""
    if irq_reg:
        irq_gate = f"& reg_{_reg_name(irq_reg)}[0]"

    sv = f"""// Composite Golden Reference Model（APB 寄存器 + UART TX/RX 接线）
// 由 spec.registers 寄存器名驱动接线（tx_data/rx_data 寄存器识别），模型不可变（源自黄金库）。
module {module_name}_ref_model (
    input  logic                  clk,
    input  logic                  rst_n,
    input  logic [{addr_w - 1}:0] paddr,
    input  logic [{data_w - 1}:0] pwdata,
    input  logic                  pwrite,
    input  logic                  psel,
    input  logic                  penable,
    output logic [{data_w - 1}:0] prdata,
    input  logic                  rx,
    output logic                  tx,
    output logic                  irq
);
    // ── APB 寄存器（spec.registers 真实语义）──
{chr(10).join(state_lines)}

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
{reset_assigns}
        end else if (psel && penable && pwrite) begin
            case (paddr)
{chr(10).join(write_case)}
                default: ;
            endcase
        end
    end

    always_comb begin
        prdata = '0;
        if (psel && !pwrite) begin
            case (paddr)
{chr(10).join(read_case)}
                default: prdata = '0;
            endcase
        end
    end

    // ── uart_tx（APB 写 TX 数据寄存器触发）──
    // 注：BAUD_DIV 为参数默认 10416（9600@100MHz）；baud 寄存器未做运行时接线（黄金模型参数限制）
    logic tx_start_p, tx_busy, tx_busy_d, tx_done;
    assign tx_start_p = (psel && penable && pwrite && paddr == {tx_offset});
    uart_tx_golden #(.DATA_BITS(8), .BAUD_DIV(10416)) u_uart_tx (
        .clk(clk), .rst_n(rst_n), .tx_start(tx_start_p),
        .tx_data(reg_{tx_name}), .tx(tx), .tx_busy(tx_busy));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) tx_busy_d <= 1'b0;
        else tx_busy_d <= tx_busy;
    end
    assign tx_done = tx_busy_d && !tx_busy;

    // ── uart_rx（rx_data → RX 数据寄存器）──
    logic rx_valid;
    logic [7:0] rx_data_w;
    uart_rx_golden #(.DATA_BITS(8), .BAUD_DIV(10416)) u_uart_rx (
        .clk(clk), .rst_n(rst_n), .rx(rx), .rx_data(rx_data_w), .rx_valid(rx_valid));
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) reg_{rx_name} <= '0;
        else if (rx_valid) reg_{rx_name} <= rx_data_w;
    end

    // ── irq：事件驱动（rx_valid | tx_done），有 irq_en 寄存器则门控 ──
    assign irq = (rx_valid | tx_done){irq_gate};
endmodule
"""
    return sv
