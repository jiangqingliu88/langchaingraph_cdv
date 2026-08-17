"""模型智能体 —— 多语言参考模型（cpp/python/systemverilog/verilog）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
import structlog

logger = structlog.get_logger()


def _extract_ops(func_hier: dict) -> list:
    ops = []
    for child in func_hier.get("children", []):
        if isinstance(child, dict) and child.get("name"):
            ops.append(child["name"])
    return ops or ["default_op"]


def _render_sv(module: str, ops: list, regs: list, interfaces: list = None) -> dict:
    """SystemVerilog 参考模型：端口对齐 spec 接口 + 寄存器真实语义（非 a+b）。

    - 端口：从 spec.interfaces 确定性生成（方向/位宽/名字），无接口表才回退旧 ALU 端口
    - 寄存器：从 spec.registers 生成真实读写语义（写 → 状态更新；读 → prdata 回读）
    - placeholder：仅有真实寄存器语义时才算"真实模型"（False），否则占位（True）
    """
    interfaces = interfaces or []

    # ── 1. 端口（确定性，从 spec 接口表）──
    dir_map = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}
    port_lines = []
    for itf in interfaces:
        if not isinstance(itf, dict) or not itf.get("name"):
            continue
        name = str(itf["name"]).split("[")[0]
        try:
            w = int(itf.get("data_width", 1) or 1)
        except (TypeError, ValueError):
            w = 1
        d = dir_map.get(str(itf.get("direction", "INPUT")).upper(), "input")
        decl = f"[{w - 1}:0] {name}" if w > 1 else name
        port_lines.append(f"    {d} logic {decl}")
    has_spec_ports = bool(port_lines)
    if has_spec_ports:
        ports = ",\n".join(port_lines)
    else:
        # 无接口表：回退旧 ALU 端口（保持向后兼容，但标记占位）
        ports = ("    input logic clk, input logic rst_n,\n"
                 "    input logic [31:0] opcode, input logic [31:0] operand_a, "
                 "input logic [31:0] operand_b,\n"
                 "    output logic [31:0] result")

    # ── 2. 寄存器真实语义（spec.registers 有数据才算真实模型）──
    reg_state, write_case, read_case = [], [], []
    for r in regs:
        if not isinstance(r, dict) or not r.get("name"):
            continue
        rname = str(r["name"])
        try:
            w = int(r.get("width", 8) or 8)
        except (TypeError, ValueError):
            w = 8
        offset = str(r.get("offset", "0x00"))
        access = str(r.get("access", "RW")).upper()
        reg_state.append(f"    logic [{w - 1}:0] reg_{rname} = '0;  // {offset} {access} "
                         f"{str(r.get('description', ''))[:40]}")
        if access != "RO":
            write_case.append(f"          {offset}: reg_{rname} = pwdata;")
        read_case.append(f"          {offset}: prdata = reg_{rname};")
    has_real_registers = bool(reg_state)
    # 预计算复位赋值（避免嵌套 f-string 转义，Python 3.11 限制）
    reset_assigns = "\n".join(
        f"      reg_{str(r['name'])} <= '0;"
        for r in regs if isinstance(r, dict) and r.get("name"))

    if has_real_registers:
        body = f"""  // ── APB 寄存器参考模型（真实语义，从 spec.registers 生成）──
{chr(10).join(reg_state)}

  // 写：psel && penable && pwrite → 更新寄存器
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

  // 读：psel && !pwrite → prdata 回读（组合）
  always_comb begin
    prdata = '0;
    if (psel && !pwrite) begin
      case (paddr)
{chr(10).join(read_case)}
        default: prdata = '0;
      endcase
    end
  end
endmodule
"""
    else:
        # 无寄存器表：诚实占位（真实模型需寄存器映射 + 协议逻辑，见 README 路线）
        body = f"""  // ── 占位参考模型：spec 无寄存器表/接口表，无法生成真实语义 ──
  // 真实参考模型需 spec.registers（寄存器映射）+ 协议逻辑（UART TX/RX 等）定向验证。
  // 仅作编译占位；audit 门禁 model_real 会拒绝签核（见 report.json gates）。
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) result <= '0;
    else result <= '0;
  end
endmodule
"""
        if not has_spec_ports:
            # 无接口也无寄存器：完全无法建模
            body = "  // 占位：spec 无接口表也无寄存器表，无法生成参考模型。\nendmodule\n"

    code = f"module {module}_ref_model(\n{ports}\n);\n{body}"
    return {
        "model_type": "systemverilog",
        "source_code": code,
        "file": f"{module}_ref_model.sv",
        "placeholder": not has_real_registers,
        "has_spec_ports": has_spec_ports,
    }


def _render(model_type: str, module: str, ops: list, regs: list,
            interfaces: list = None) -> dict:
    """按语言渲染参考模型（真实模板）。"""
    if model_type == "python":
        methods = "\n".join(f"    def {op}(self, a, b):\n        return a + b" for op in ops)
        code = f"""class {module}_ref_model:
    def __init__(self):
        self.regs = [0] * {max(len(regs)*4, 16)}
    def reset(self):
        self.regs = [0] * {max(len(regs)*4, 16)}
    def read_register(self, addr):
        return self.regs[addr // 4] if addr < {len(regs)*4} else 0
    def write_register(self, addr, v):
        if addr < {len(regs)*4}: self.regs[addr // 4] = v
    def predict(self, op, a, b):
        return a + b
{methods}
"""
        return {"model_type": "python", "source_code": code, "file": f"{module}_ref_model.py",
                "placeholder": True}
    elif model_type == "systemverilog":
        return _render_sv(module, ops, regs, interfaces)
    elif model_type == "verilog":
        cases = "\n".join(f"      {i}: result = a + b;  // {op}" for i, op in enumerate(ops))
        code = f"""module {module}_ref_model(
    input wire clk, input wire rst_n,
    input wire [7:0] op, input wire [31:0] a, input wire [31:0] b,
    output reg [31:0] result);
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) result <= 32'd0;
    else case (op)
{cases}
      default: result <= 32'd0;
    endcase
  end
endmodule
"""
        return {"model_type": "verilog", "source_code": code, "file": f"{module}_ref_model.v",
                "placeholder": True}
    else:  # cpp
        cases = "\n".join(f"    case {i}: return a + b;  // {op}" for i, op in enumerate(ops))
        h = f"""#ifndef {module.upper()}_REF_MODEL_H
#define {module.upper()}_REF_MODEL_H
class {module}_ref_model {{
public:
  void reset();
  int predict(int op, int a, int b);
private:
  int regs[{max(len(regs)*4, 16)}] = {{0}};
}};
#endif
"""
        cpp = f"""#include "{module}_ref_model.h"
void {module}_ref_model::reset() {{ for (auto &r : regs) r = 0; }}
int {module}_ref_model::predict(int op, int a, int b) {{
  switch(op) {{
{cases}
    default: return 0;
  }}
}}
"""
        return {"model_type": "cpp", "header_code": h, "source_code": cpp,
                "file": f"{module}_ref_model.cpp", "placeholder": True}


@register_agent("model")
class ModelAgent(BaseAgent):
    """模型智能体：多语言参考模型生成"""

    task_type = "code_generation"
    consumes = ["spec", "design_arch"]
    produces = "model"

    SUPPORTED_TYPES = ["cpp", "python", "systemverilog", "verilog"]

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="model", display_name="模型智能体",
            description="多语言参考模型（cpp/python/sv/verilog）", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        ctx = task.get("ctx", {})
        design_arch = ctx.get("design_arch", {}) if hasattr(ctx, 'get') else {}
        if not isinstance(design_arch, dict):
            design_arch = {}

        params = task.get("params", {}) or {}
        action = params.get("action", "generate")
        model_type = params.get("model_type", "cpp")
        if model_type not in self.SUPPORTED_TYPES:
            model_type = "cpp"

        module = design_arch.get("module_name", "dut")
        func_hier = design_arch.get("function_hier", {})
        regs = design_arch.get("registers", [])
        ops = _extract_ops(func_hier)

        # ── 动作: rollback（回滚到上一个稳定版本）──
        if action == "rollback":
            return self._rollback(output_dir, module)

        # ── 动作: generate / update（生成新版本，旧版本并存）──
        interfaces = design_arch.get("interfaces", [])
        rendered = _render(model_type, module, ops, regs, interfaces)

        # 版本管理: 读取当前版本号，+1 生成新版本
        model_dir = output_dir / "model"
        model_dir.mkdir(parents=True, exist_ok=True)
        version = self._next_version(model_dir, module)
        ver_dir = model_dir / f"{module}_v{version}"
        ver_dir.mkdir(parents=True, exist_ok=True)

        # 写文件到版本目录（旧版本并存，不覆盖）
        fpath = ver_dir / rendered["file"]
        if model_type == "cpp":
            hpath = ver_dir / f"{module}_ref_model.h"
            hpath.write_text(rendered["header_code"], encoding="utf-8")
            fpath.write_text(rendered["source_code"], encoding="utf-8")
        else:
            fpath.write_text(rendered["source_code"], encoding="utf-8")

        # 更新稳定版本指针
        self._mark_stable(model_dir, module, version)

        model_data = {
            "module": module, "model_type": model_type,
            "version": f"v{version}", "files": [str(fpath)],
            "operation_count": len(ops), "register_count": len(regs),
            "status": "generated", "reason": params.get("reason", ""),
            "all_versions": self._list_versions(model_dir, module),
        }
        # ── 说真话：参考模型是否"真实"由渲染结果决定 ──
        # SV 模型含真实寄存器语义（spec.registers）→ placeholder=False；
        # 否则为结构占位（历史 a+b 模板已废弃）→ placeholder=True，audit 拒绝签核。
        model_data["placeholder"] = rendered.get("placeholder", True)
        if model_data["placeholder"]:
            model_data["placeholder_reason"] = (
                "占位参考模型：spec 无寄存器表（或非 SV 模型），无真实功能语义。"
                "仅作编译占位，禁止作为签核比对依据。真实参考模型需 spec.registers"
                " + 协议逻辑（UART TX/RX 等）经定向仿真验证。")
        else:
            model_data["placeholder_reason"] = ""
        model_data["spec_interfaces"] = len(interfaces)
        model_data["score"] = min(50 + len(ops) * 5, 85)
        return AgentResult(success=True, data={"model": model_data, "score": model_data["score"]})

    # ── 版本管理辅助 ──

    def _next_version(self, model_dir: Path, module: str) -> int:
        """读取现有版本号，返回下一个版本号。"""
        versions = self._list_versions(model_dir, module)
        return max(versions, default=0) + 1

    def _list_versions(self, model_dir: Path, module: str) -> list:
        """列出 module 的所有版本号。"""
        if not model_dir.exists():
            return []
        versions = []
        for d in model_dir.iterdir():
            if d.is_dir() and d.name.startswith(f"{module}_v"):
                try:
                    versions.append(int(d.name.split("_v")[-1]))
                except ValueError:
                    pass
        return sorted(versions)

    def _mark_stable(self, model_dir: Path, module: str, version: int):
        """标记稳定版本（写入 stable 指针文件）。"""
        stable_file = model_dir / f"{module}_stable.txt"
        stable_file.write_text(str(version), encoding="utf-8")

    def _rollback(self, output_dir: Path, module: str) -> AgentResult:
        """回滚到上一个稳定版本。"""
        model_dir = output_dir / "model"
        versions = self._list_versions(model_dir, module)
        if len(versions) < 2:
            return AgentResult(success=False,
                               data={"model": {"status": "rollback_failed",
                                               "reason": "无历史版本可回滚"}, "score": 10})
        # 回滚 = 稳定指针指向倒数第二个版本
        prev = versions[-2]
        self._mark_stable(model_dir, module, prev)
        return AgentResult(success=True, data={
            "model": {"status": "rolled_back", "version": f"v{prev}",
                      "from": f"v{versions[-1]}", "reason": "新模型导致失败，回滚"},
            "score": 60,
        })
