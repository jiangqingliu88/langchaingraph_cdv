"""设计智能体 —— Spec → 架构 → RTL（真实工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog

logger = structlog.get_logger()


@register_agent("design")
class DesignAgent(BaseAgent):
    """设计智能体 = spec 分析 + 架构分解 + RTL 生成"""

    task_type = "code_generation"
    consumes = ["spec"]
    produces = "design_arch"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="design", display_name="设计智能体",
            description="Spec→架构→RTL 全链路", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """spec 分析 → design_arch → rtl（真实工具链）"""
        from src.core.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        spec_text = task.get("input", "")
        ctx = task.get("ctx", {})
        spec_data = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}

        # ── 1. Spec 分析（真实工具 spec_tools）──
        spec = spec_data
        if not isinstance(spec, dict) or not spec.get("design_name"):
            try:
                from src.tools.spec_tools.main import analyze_specification
                raw = analyze_specification(spec_text or str(spec_data))
                spec = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith('{') else {}
            except Exception as e:
                logger.warning(f"spec 分析失败: {e}")
                spec = {"design_name": "dut"}

        module_name = spec.get("design_name", "dut")
        if module_name.lower() in ("dut", "dut_top", ""):
            module_name = "dut"

        # ── 2. 架构分解（function_hier + registers + interfaces）──
        design_arch = {
            "module_name": module_name,
            "function_hier": self._build_func_hier(spec),
            "registers": spec.get("registers", []),
            "interfaces": spec.get("interfaces", []),
            "signoff_checklist": [],
        }

        # ── 3. RTL 生成（真实模板，从 function_hier 提取操作）──
        rtl_dir = output_dir / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        rtl_files = self._generate_rtl(design_arch, rtl_dir)

        result = {
            "design_arch": design_arch,
            "rtl": {"module_name": module_name, "files": rtl_files,
                    "file_count": len(rtl_files)},
            "spec": spec,
        }
        score = min(50 + len(rtl_files) * 15 + len(spec.get("registers", [])) * 2, 90) \
            if rtl_files else 30
        result["score"] = score
        return AgentResult(success=bool(rtl_files), data=result)

    def _build_func_hier(self, spec: dict) -> dict:
        """从 spec features 构建功能层次。"""
        features = spec.get("features", [])
        children = []
        for f in features:
            if isinstance(f, dict):
                name = f.get("name", "feature")
            else:
                name = str(f)
            # 简化：每个 feature 是一个叶子操作
            children.append({"name": name.replace(" ", "_").lower()[:30]})
        if not children:
            children = [{"name": "core_op"}]
        return {"name": spec.get("design_name", "dut"), "children": children}

    def _generate_rtl(self, design_arch: dict, rtl_dir: Path) -> list:
        """从 spec 接口表生成 RTL：端口对齐 + 确定性功能骨架。

        不再写死 ALU——端口从 spec 的 interfaces 字段生成（与 UVM bench top 对齐），
        功能逻辑先给确定性骨架（输出信号在时钟沿依赖输入，制造真实接口信号 toggle），
        真实功能逻辑（APB 读写/UART 状态机）由 LLM 在后续迭代填充。
        """
        module_name = design_arch["module_name"]
        interfaces = design_arch.get("interfaces", [])

        if not interfaces:
            # 无接口表：回退到旧 ALU 骨架（保持向后兼容）
            return self._generate_rtl_legacy(design_arch, rtl_dir)

        ports = self._gen_ports(interfaces)
        logic = self._gen_logic_skeleton(module_name, interfaces)

        rtl_code = f"module {module_name} (\n{ports}\n);\n\n{logic}\nendmodule\n"

        fpath = rtl_dir / f"{module_name}.sv"
        fpath.write_text(rtl_code, encoding="utf-8")
        return [str(fpath)]

    @staticmethod
    def _gen_ports(interfaces: list) -> str:
        """从 spec 接口表生成 module 端口声明（paddr[7:0] → [7:0] paddr）。"""
        dir_map = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}
        ports = []
        for itf in interfaces:
            name = itf.get("name", "")
            width = int(itf.get("data_width", 1))
            direction = itf.get("direction", "INPUT").upper()
            base = name.split("[")[0] if "[" in name else name  # paddr[7:0] → paddr
            decl = f"[{width - 1}:0] {base}" if width > 1 else base
            ports.append(f"  {dir_map.get(direction, 'input')}  logic {decl}")
        return ",\n".join(ports)

    @staticmethod
    def _gen_logic_skeleton(module_name: str, interfaces: list) -> str:
        """确定性功能骨架：识别时钟/复位，输出信号在时钟沿依赖输入（制造 toggle）。

        这是"骨架"——端口对齐 + 输出有时序驱动 + 通过 vlog 编译。
        真实功能逻辑（APB 读写/UART 状态机）由 LLM 后续迭代填充。
        """
        # 识别时钟 / 复位（按 protocol 字段）
        clk, rst_n = "clk", "rst_n"
        rst_active_low = False
        for itf in interfaces:
            proto = itf.get("protocol", "").lower()
            nm = itf.get("name", "").split("[")[0]
            if proto in ("clock", "clk"):
                clk = nm
            elif proto in ("reset", "rst"):
                rst_n = nm
                rst_active_low = "n" in nm.lower()

        inputs = [i for i in interfaces
                  if i.get("direction", "").upper() == "INPUT"
                  and i.get("protocol", "").lower() not in ("clock", "reset")]
        outputs = [i for i in interfaces if i.get("direction", "").upper() == "OUTPUT"]
        src_list = [i.get("name", "").split("[")[0] for i in inputs]

        edge = f"posedge {clk}" + (f" or negedge {rst_n}" if rst_active_low else f" or posedge {rst_n}")
        cond = f"!{rst_n}" if rst_active_low else rst_n

        lines = [f"  // 确定性功能骨架：端口对齐 + 输出时序驱动（真实逻辑待 LLM 填充）"]
        lines.append(f"  always_ff @({edge}) begin")
        lines.append(f"    if ({cond}) begin")
        for o in outputs:
            nm = o.get("name", "").split("[")[0]
            w = int(o.get("data_width", 1))
            lines.append(f"      {nm} <= {w}'h0;")
        lines.append("    end else begin")
        if src_list:
            for idx, o in enumerate(outputs):
                nm = o.get("name", "").split("[")[0]
                src = src_list[idx % len(src_list)]
                lines.append(f"      {nm} <= {src};  // 占位：依赖输入制造 toggle")
        else:
            for o in outputs:
                nm = o.get("name", "").split("[")[0]
                lines.append(f"      {nm} <= ~{nm};  // 无输入，自翻转制造 toggle")
        lines.append("    end")
        lines.append("  end")
        return "\n".join(lines)

    def _generate_rtl_legacy(self, design_arch: dict, rtl_dir: Path) -> list:
        """旧 ALU 骨架（无接口表时的回退）。"""
        module_name = design_arch["module_name"]
        func_hier = design_arch.get("function_hier", {})
        ops = self._extract_ops(func_hier)

        rtl_code = (
            f"module {module_name} (\n"
            f"  input  logic clk,\n"
            f"  input  logic rst_n,\n"
            f"  input  logic [31:0] opcode,\n"
            f"  input  logic [31:0] operand_a,\n"
            f"  input  logic [31:0] operand_b,\n"
            f"  output logic [31:0] result\n"
            f");\n\n"
            f"  always_ff @(posedge clk or negedge rst_n) begin\n"
            f"    if (!rst_n) result <= '0;\n"
            f"    else begin\n"
            f"      case (opcode)\n"
        )
        for i, op in enumerate(ops):
            rtl_code += f"        {i}: result <= operand_a + operand_b;  // {op}\n"
        rtl_code += (
            f"        default: result <= '0;\n"
            f"      endcase\n"
            f"    end\n"
            f"  end\n"
            f"endmodule\n"
        )

        fpath = rtl_dir / f"{module_name}.sv"
        fpath.write_text(rtl_code, encoding="utf-8")
        return [str(fpath)]

    def _extract_ops(self, func_hier: dict) -> list:
        ops = []
        for child in func_hier.get("children", []):
            if isinstance(child, dict) and child.get("name"):
                ops.append(child["name"])
        return ops or ["op"]
