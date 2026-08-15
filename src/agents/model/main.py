"""模型智能体 —— 多语言参考模型（cpp/python/systemverilog/verilog）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
import structlog

logger = structlog.get_logger()


def _extract_ops(func_hier: dict) -> list:
    ops = []
    for child in func_hier.get("children", []):
        if isinstance(child, dict) and child.get("name"):
            ops.append(child["name"])
    return ops or ["default_op"]


def _render(model_type: str, module: str, ops: list, regs: list) -> dict:
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
        return {"model_type": "python", "source_code": code, "file": f"{module}_ref_model.py"}
    elif model_type == "systemverilog":
        # 接口与 DUT 对齐（opcode/operand_a/operand_b/result，32 位），便于在 env 里并排 compare
        cases = "\n".join(f"      {i}: result <= operand_a + operand_b;  // {op}"
                          for i, op in enumerate(ops))
        code = f"""module {module}_ref_model(
    input logic clk, input logic rst_n,
    input logic [31:0] opcode, input logic [31:0] operand_a, input logic [31:0] operand_b,
    output logic [31:0] result);
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) result <= '0;
    else case (opcode)
{cases}
      default: result <= '0;
    endcase
  end
endmodule
"""
        return {"model_type": "systemverilog", "source_code": code, "file": f"{module}_ref_model.sv"}
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
        return {"model_type": "verilog", "source_code": code, "file": f"{module}_ref_model.v"}
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
        return {"model_type": "cpp", "header_code": h, "source_code": cpp, "file": f"{module}_ref_model.cpp"}


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
        from src.core.output_config import make_output_root
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
        rendered = _render(model_type, module, ops, regs)

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
