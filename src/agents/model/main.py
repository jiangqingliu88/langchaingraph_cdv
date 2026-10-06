"""模型智能体 —— 多语言参考模型（cpp/python/systemverilog/verilog）"""
from typing import Dict, Any
import hashlib
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
        # 无寄存器表：诚实占位（真实模型需寄存器映射 + 协议逻辑，见 README 路线）。
        #
        # **输出按实际端口派生、统一驱动为 0** —— 别写死信号名。这里原来是一段
        # 写死 `clk/rst_n/result` 的 always_ff：那些是 ALU 回退端口的名字，一旦
        # 端口是从 spec 接口生成的（pclk/preset_n/…），就成了未定义变量、vlog 直接
        # 报错。占位模型的本意是"**编得过但不做事**"，写死名字会让它连编都编不过
        # （2026-10-04 编译门禁上线后才暴露出来）。
        out_names = [str(i["name"]).split("[")[0] for i in interfaces
                     if isinstance(i, dict) and i.get("name")
                     and str(i.get("direction", "")).upper() == "OUTPUT"]
        if not has_spec_ports:
            out_names = ["result"]              # 回退 ALU 端口的输出
        if out_names:
            drives = "\n".join(f"    {n} = '0;" for n in out_names)
            body = f"""  // ── 占位参考模型：spec 无寄存器表，无法生成真实语义 ──
  // 真实参考模型需 spec.registers（寄存器映射）+ 协议逻辑（UART TX/RX 等）定向验证。
  // 输出统一驱动为 0：编得过、但不做事；audit 门禁 model_real 会拒绝签核。
  always_comb begin
{drives}
  end
endmodule
"""
        else:
            # 无接口也无寄存器：完全无法建模，空模块（编得过，什么都不声明）
            body = ("  // 占位：spec 无接口表也无寄存器表，无法生成参考模型。\n"
                    "endmodule\n")

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
        regs_all = design_arch.get("registers", [])
        rendered = None
        golden_ref = {}
        unverified_golden = None  # 未验证黄金模型 (ip, version)，用于诚实占位原因
        # 优先黄金模型库（真实、可验证、可追溯）；LLM/模板只做选择与参数化
        if model_type == "systemverilog":
            try:
                from src.tools.lib.golden_library import (
                    match_golden, load_golden, parameterize,
                    build_composite_ref_model)
                # 1) 复合参考模型：APB+UART 且寄存器表可接线 → 多黄金 IP 实例化
                composite_sv = build_composite_ref_model(module, interfaces, regs_all)
                if composite_sv:
                    golden_ref = {"ip": "composite",
                                  "parts": ["apb_slave", "uart_tx", "uart_rx", "irq_gen"],
                                  "sha256": hashlib.sha256(
                                      composite_sv.encode("utf-8")).hexdigest()}
                    rendered = {"model_type": "systemverilog", "source_code": composite_sv,
                                "file": f"{module}_ref_model.sv",
                                "placeholder": False, "golden_ref": golden_ref}
                    logger.info(f"复合参考模型生成: {module}_ref_model.sv "
                                f"(apb_slave+uart_tx+uart_rx, sha256={golden_ref['sha256'][:12]})")
                else:
                    # 2) 单黄金模型：按 spec 接口匹配
                    hit = match_golden(design_arch)
                    if hit and hit.get("verified"):
                        sv = parameterize(load_golden(hit["ip"], hit["version"]),
                                          module, hit["params"])
                        golden_ref = {"ip": hit["ip"], "version": hit["version"],
                                      "sha256": hit["sha256"], "params": hit["params"],
                                      "verified": True}
                        rendered = {"model_type": "systemverilog", "source_code": sv,
                                    "file": f"{module}_ref_model.sv",
                                    "placeholder": False, "golden_ref": golden_ref}
                        logger.info(f"黄金模型命中: {hit['ip']} {hit['version']} "
                                    f"(sha256={hit['sha256'][:12]}) → {module}_ref_model.sv")
                    elif hit:
                        # 未验证黄金模型：诚实占位（audit 拒绝签核），不静默降级为"真实"
                        unverified_golden = (hit["ip"], hit["version"])
                        logger.warning(f"黄金模型 {hit['ip']} {hit['version']} 未验证"
                                       f"（verified=false），按占位处理；"
                                       f"待 scripts/model_library_verify.py 入库验证")
            except Exception as e:
                logger.warning(f"黄金模型匹配失败: {e}")
        if rendered is None:
            rendered = _render(model_type, module, ops, regs_all, interfaces)

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

        # ── 本地闭环：过 EDA 才写稳定指针（与 design 的 vlog 门禁对称）──
        # 说不行的产物**不进稳定指针** —— `{module}_stable.txt` 自然停在上一版，
        # scoreboard 就不会拿一份编不过的模型去比。没装 EDA 时判不了，
        # 如实标 BLOCKED 照常推进（不冒充通过，也不冤枉一份可能没问题的模型）。
        compile_info = self._verify_model(model_dir, module, model_type,
                                          rendered["source_code"])
        compile_failed = compile_info["status"] == "FAIL"
        if compile_failed:
            logger.warning(f"参考模型 {module} v{version} 未过编译门禁，不进稳定指针："
                           f"{compile_info['detail']}")
        else:
            self._mark_stable(model_dir, module, version)

        model_data = {
            "module": module, "model_type": model_type,
            "version": f"v{version}", "files": [str(fpath)],
            "operation_count": len(ops), "register_count": len(regs),
            "status": "generated", "reason": params.get("reason", ""),
            "all_versions": self._list_versions(model_dir, module),
        }
        # ── 说真话：参考模型是否"真实"由渲染结果决定 ──
        # 黄金模型库命中（apb_slave 等）→ placeholder=False + golden_ref（sha256 可追溯）；
        # 否则为结构占位（历史 a+b 模板已废弃）→ placeholder=True，audit 拒绝签核。
        model_data["placeholder"] = rendered.get("placeholder", True)
        model_data["golden_ref"] = rendered.get("golden_ref", None) or golden_ref or None
        if model_data["placeholder"]:
            if unverified_golden:
                model_data["placeholder_reason"] = (
                    f"未验证黄金模型 {unverified_golden[0]} {unverified_golden[1]}"
                    f"（verified=false），待 scripts/model_library_verify.py 入库验证后"
                    f"才能作为签核比对依据。")
            else:
                model_data["placeholder_reason"] = (
                    "占位参考模型：黄金模型库无匹配（或非 SV 模型），无验证过的功能语义。"
                    "仅作编译占位，禁止作为签核比对依据。真实参考模型需先入库验证"
                    "（见 docs/design/golden_model_library.md）。")
        else:
            model_data["placeholder_reason"] = ""
        model_data["spec_interfaces"] = len(interfaces)
        model_data["score"] = min(50 + len(ops) * 5, 85)
        # 编译门禁的结果**进 data** —— 界面（agent 产出总览）与 audit 都看得到
        model_data["compile"] = compile_info

        if compile_failed:
            # 编不过的模型不该拿"看起来还行"的分 —— 分数跟着门禁走
            model_data["status"] = "compile_failed"
            model_data["score"] = min(model_data["score"], 30)
            # 失败响亮：EDA 说这份模型用不了 → 这一步就是失败的（不许粉饰）。
            # data 照常带回去（含 placeholder_reason 与 compile 详情），audit 仍能看到。
            return AgentResult(success=False,
                               data={"model": model_data, "score": model_data["score"]},
                               error=f"参考模型未过编译门禁：{compile_info['detail']}")
        return AgentResult(success=True, data={"model": model_data, "score": model_data["score"]})

    # ── 本地闭环：编译门禁 ──

    @staticmethod
    def _verify_model(model_dir: Path, module: str, model_type: str,
                      source_code: str) -> Dict[str, Any]:
        """参考模型能不能真的被用上 —— 本地闭环（铁律一）。

        design 用 vlog 门禁决定"这份 RTL 留不留"；参考模型与之对称：**先过 EDA，
        过了才写稳定指针**。此前这一步是"生成完就走"，对不对要到 audit 的
        `model_real` 门禁才知道 —— 那是**延迟判定**，不是闭环。

        三种结果分得很清（混起来会误杀）：
            PASS                 编译通过 → 可以进稳定指针
            FAIL                 编译不过 → 这一步失败，产物不进稳定指针
            BLOCKED_EDA_MISSING  环境里没有 vlog → **判不了**：如实标注、照常推进。
                                 既不冒充通过，也不冤枉一份可能没问题的模型。
            SKIPPED              非 HDL 模型（cpp）没有可用的本地编译门禁

        非 SV/Verilog 的模型：python 用 stdlib `compile()` 做语法检查；cpp 只能标
        SKIPPED —— 环境里没有保证存在的 C++ 编译器，编不出来就不许说编过了。
        """
        if model_type == "python":
            try:
                compile(source_code, f"{module}_ref_model.py", "exec")
                return {"status": "PASS", "errors": 0, "detail": "Python 语法检查通过"}
            except SyntaxError as exc:
                return {"status": "FAIL", "errors": 1,
                        "detail": f"Python 语法错误（第 {exc.lineno} 行）：{exc.msg}"}

        if model_type not in ("systemverilog", "verilog"):
            return {"status": "SKIPPED", "errors": 0,
                    "detail": f"{model_type} 模型没有可用的本地编译门禁（不冒充通过）"}

        import shutil
        import tempfile

        if shutil.which("vlog") is None:
            return {"status": "BLOCKED_EDA_MISSING", "errors": 0,
                    "detail": "环境里没有 vlog（QuestaSim 未安装或不在 PATH）—— "
                              "无法判定这位参考模型，不冒充通过；装好后重跑这一步。"}
        try:
            from src.layers.l1_infrastructure.infrastructure import InfrastructureManager

            suffix = ".sv" if model_type == "systemverilog" else ".v"
            tmp_dir = Path(tempfile.mkdtemp(prefix="model_verify_"))
            target = tmp_dir / f"{module}_ref_model{suffix}"
            target.write_text(source_code, encoding="utf-8")
            fl = tmp_dir / "filelist.f"
            fl.write_text(str(target), encoding="utf-8")

            result = InfrastructureManager(tmp_dir).compile(str(fl), coverage=False)
            errors = int(result.get("errors", 0) or 0)
            passed = result.get("status") == "PASS" and errors == 0
            return {"status": "PASS" if passed else "FAIL", "errors": errors,
                    "detail": "vlog 编译通过" if passed else f"vlog 编译失败（{errors} 处错误）"}
        except Exception as exc:                      # noqa: BLE001
            return {"status": "FAIL", "errors": 1, "detail": f"编译校验异常：{exc}"}

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
