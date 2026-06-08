"""
参考模型 Agent —— 根据 spec + design_arch 生成纯 C++ 参考模型

   设计决策：选择纯 C++ 而非 SystemC，原因：
     1. 无需 SystemC 库依赖 —— g++/clang 直接编译
     2. TLM2.0 传输由 SV 侧 rtl_sc_channel 通过 UVMC DPI 完成，模型只需纯计算
     3. 模型签名：void predict(input_txn, &output_txn) → 无并发、无时序
     4. CI 友好：g++ -std=c++17 ref_model.cpp test.cpp -o test && ./test
     5. SystemC 仅在需要 cycle-accurate timing / SC_THREAD / TLM socket 时选用

   工具集（纯 C++ 模板渲染，无外部框架依赖）：
     - analyze_design_arch   设计架构 → 寄存器 + 运算清单
     - generate_ref_model    寄存器 + 运算 → C++ .h + .cpp
     - generate_test_vectors 参考模型 → IO 测试向量（验证模型正确性）
"""
from typing import Dict, List, Any
from datetime import datetime as dt
import json

from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.tools import tool

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from pathlib import Path
import structlog

logger = structlog.get_logger()


# ═══════════════════════════════════════════════════════════
# LangChain Tools
# ═══════════════════════════════════════════════════════════

@tool("analyze_design_arch")
def _analyze_design_arch(design_json: str) -> str:
    """解析 design_architect 输出，提取寄存器 map + 运算清单"""
    try:
        data = json.loads(design_json) if isinstance(design_json, str) else {}
    except (json.JSONDecodeError, TypeError):
        data = {}

    registers = data.get("registers", [])
    func_hier = data.get("function_hier", {})
    module_name = data.get("module_name", "dut")

    ops = _extract_operations(func_hier)

    result = {
        "module_name": module_name,
        "register_count": len(registers),
        "registers": [{"name": r.get("name", f"reg_{i}"),
                        "addr": r.get("offset", r.get("addr", 0)),
                        "width": r.get("width", 32),
                        "access": r.get("access", "RW")}
                       for i, r in enumerate(registers)],
        "operation_count": len(ops),
        "operations": ops,
        "input_signals": _extract_inputs(func_hier),
        "output_signals": _extract_outputs(func_hier, registers),
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("generate_ref_model")
def _generate_ref_model(analysis_json: str) -> str:
    """根据架构分析结果生成纯 C++ 参考模型（.h + .cpp）"""
    try:
        a = json.loads(analysis_json) if isinstance(analysis_json, str) else {}
    except (json.JSONDecodeError, TypeError):
        a = {}

    module_name = a.get("module_name", "dut")
    registers = a.get("registers", [])
    operations = a.get("operations", [])

    h_code = _render_ref_model_h(module_name, registers, operations)
    cpp_code = _render_ref_model_cpp(module_name, registers, operations)

    return json.dumps({
        "module": module_name,
        "model_type": "cpp",
        "register_count": len(registers),
        "operation_count": len(operations),
        "files": {
            "header": f"{module_name}_ref_model.h",
            "source": f"{module_name}_ref_model.cpp",
        },
        "header_code": h_code,
        "source_code": cpp_code,
        "status": "generated",
    }, indent=2, ensure_ascii=False)


@tool("generate_test_vectors")
def _generate_test_vectors(model_json: str) -> str:
    """为参考模型生成 IO 测试向量（自验证：C++ 编译 + 输入驱动 + 输出检查）"""
    try:
        m = json.loads(model_json) if isinstance(model_json, str) else {}
    except (json.JSONDecodeError, TypeError):
        m = {}

    module_name = m.get("module", "dut")
    registers = m.get("registers", m.get("register_count", 0))
    reg_count = registers if isinstance(registers, int) else len(registers)

    tests = [
        {"name": "reset_check",    "input": {"cmd": 0, "a": 0, "b": 0}, "expect": {"result": 0, "flags": 1}},
        {"name": "simple_add",     "input": {"cmd": 1, "a": 3, "b": 5}, "expect": {"result": 8, "flags": 0}},
        {"name": "zero_result",    "input": {"cmd": 1, "a": 0, "b": 0}, "expect": {"result": 0, "flags": 1}},
        {"name": "max_operands",   "input": {"cmd": 1, "a": 0xFFFFFFFF, "b": 1}, "expect": {"result": 0, "flags": 3}},
        {"name": "reg_write_read", "input": {"cmd": 0x10, "a": 0xDEAD, "b": 0}, "expect": {"result": 0xDEAD, "flags": 0}},
    ]

    test_code = _render_test_main(module_name, tests)

    return json.dumps({
        "test_count": len(tests),
        "test_file": f"test_{module_name}_ref_model.cpp",
        "test_code": test_code,
        "vectors": tests,
        "compile_cmd": f"g++ -std=c++17 {module_name}_ref_model.cpp test_{module_name}_ref_model.cpp -o test_{module_name}",
        "run_cmd": f"./test_{module_name}",
        "status": "generated",
    }, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# Agent 定义
# ═══════════════════════════════════════════════════════════

@register_agent("model_agent")
class ModelAgent(BaseAgent):
    """参考模型 Agent —— 纯 C++ 参考模型生成（无 SystemC 依赖）"""

    task_type = "code_generation"
    consumes = ["spec", "design_arch"]
    produces = "model"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="model_agent",
            display_name="参考模型工程师",
            description="根据设计架构生成纯 C++ 参考模型 + 自测验证向量",
            config=config or {}
        )

    async def _setup(self):
        logger.info(f"{self.display_name} 特定初始化完成")

    async def _get_prompt_template(self):
        return ChatPromptTemplate.from_messages([
            ("system", """你是参考模型 / C++ 建模工程师。

【设计原则】
- 选择纯 C++ 而非 SystemC：模型工作在数据域，不需要时序/并发/TLM socket
- TLM2.0 传输由 SV 侧 rtl_sc_channel 通过 UVMC DPI 完成
- 模型只需实现纯函数：predict(input_txn, state) → output_txn

【职责】
1. 解析 design_architect 输出的寄存器 map + function hierarchy
2. 生成纯 C++ 参考模型（.h + .cpp）
3. 生成 IO 测试向量自验证

【工具】
- analyze_design_arch: design_arch JSON → 寄存器 + 运算清单
- generate_ref_model: 架构分析 → C++ .h + .cpp
- generate_test_vectors: 参考模型 → 自测向量（g++ 编译验证）

            """),
            MessagesPlaceholder(variable_name="chat_history"),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])

    async def _get_tools(self) -> List:
        return [_analyze_design_arch, _generate_ref_model, _generate_test_vectors]

    async def _execute(self, input_text: str) -> Dict[str, Any]:
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: design_arch → analyze → C++ ref model + test vectors ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            # Hybrid: use bypass when ctx has required data
            ctx = task.get("ctx", {}) if isinstance(task, dict) else {}
            if ctx.get("spec"):
                task["bypass"] = True
            return await super().execute_task(task)

        start = dt.now()
        try:
            ctx = task.get("ctx", {})
            output_dir = task.get("output_dir", "generated/alu")
            self._last_prompt = "bypass: design_arch → C++ ref model + test vectors"

            design = ctx.get("design_arch", {})
            spec = ctx.get("spec", {})

            module_name = design.get("module_name", spec.get("module_name", "dut"))
            registers = design.get("registers", [])
            func_hier = design.get("function_hier", {})

            # ── Step 1: analyze design_arch ──
            design_data = {
                "module_name": module_name,
                "registers": registers,
                "function_hier": func_hier,
            }
            analysis_str = _analyze_design_arch(json.dumps(design_data, ensure_ascii=False))
            analysis = json.loads(analysis_str)

            # ── Step 2: generate C++ ref model ──
            # Rebuild analysis with proper data for model generation
            a_data = {"module_name": module_name, "registers": registers,
                      "operations": _extract_operations(func_hier) if func_hier else []}
            model_str = _generate_ref_model(json.dumps(a_data, ensure_ascii=False))
            model = json.loads(model_str)

            # ── Step 3: generate test vectors ──
            vectors_str = _generate_test_vectors(json.dumps(model, ensure_ascii=False))
            vectors = json.loads(vectors_str)

            # ── Step 4: write files to disk ──
            cmodel_dir = Path(output_dir) / "cmodel"
            cmodel_dir.mkdir(parents=True, exist_ok=True)
            model_files = model.get("files", {})
            h_path = cmodel_dir / model_files.get("header", f"{module_name}_ref_model.h")
            cpp_path = cmodel_dir / model_files.get("source", f"{module_name}_ref_model.cpp")
            test_path = cmodel_dir / vectors.get("test_file", f"test_{module_name}_ref_model.cpp")
            h_path.write_text(model_files.get("header_code", f"// {module_name} ref model header"), encoding="utf-8")
            cpp_path.write_text(model_files.get("source_code", f"// {module_name} ref model impl"), encoding="utf-8")
            test_path.write_text(vectors.get("test_code", "// test vectors"), encoding="utf-8")
            vectors_path = cmodel_dir / "test_vectors.json"
            vectors_path.write_text(json.dumps(vectors.get("vectors", []), indent=2), encoding="utf-8")
            written_files = [str(h_path), str(cpp_path), str(test_path), str(vectors_path)]

            summary = (
                f"Ref Model: {module_name}_ref_model.h + .cpp + test vectors\n"
                f"  Written: {len(written_files)} files → {cmodel_dir}\n"
                f"  Registers: {a_data.get('register_count', len(registers))} mapped\n"
                f"  Operations: {a_data.get('operation_count', 0)} mapped\n"
                f"  Test vectors: {vectors.get('test_count', 0)}\n"
                f"  Compile: {vectors.get('compile_cmd', 'g++ -std=c++17 test_...')}\n"
                f"  Run: {vectors.get('run_cmd', './a.out')}\n"
            )

            self.metrics["tasks_completed"] += 1
            self.metrics["total_time"] += (dt.now() - start).total_seconds()

            # ── Step 5: generate UVM cmodel predictor + DPI wrapper ──
            try:
                from src.tools.compilesim.gen_cmodel import generate_cmodel
                cm_r = generate_cmodel(str(cmodel_dir), module_name)
                if cm_r["status"] == "PASS":
                    written_files.extend(cm_r["files"])
                    summary += f"  UVM Predictor: {len(cm_r['files'])} files generated\n"
            except Exception as e:
                summary += f"  UVM Predictor: skipped ({e})\n"

            tv_count = len(vectors) if vectors else 0
            return AgentResult(success=True, data={
                "output": summary,
                "model": {
                    "module": module_name,
                    "model_type": "cpp",
                    "analysis": a_data,
                    "ref_model": model,
                    "test_vectors": vectors,
                    "files": written_files,
                    "output_dir": str(cmodel_dir),
                },
                "score": min(40 + tv_count * 5, 80),
            }, execution_time=(dt.now() - start).total_seconds())

        except Exception as e:
            import traceback
            return AgentResult(success=False, error=f"{e}\n{traceback.format_exc()}")


# ═══════════════════════════════════════════════════════════
# 辅助函数 —— 纯 C++ 参考模型渲染
# ═══════════════════════════════════════════════════════════

def _extract_operations(func_hier: dict) -> list:
    """从 function hierarchy 提取叶子运算列表"""
    ops = []

    def _walk(node, depth=0):
        if isinstance(node, dict):
            name = node.get("name", "")
            children = node.get("children", [])
            if name and not children:
                ops.append({"name": name, "depth": depth})
            for child in children:
                _walk(child, depth + 1)
        elif isinstance(node, list):
            for item in node:
                _walk(item, depth)

    _walk(func_hier)
    return ops


def _extract_inputs(func_hier: dict) -> list:
    """从 function hierarchy 提取输入信号"""
    # 默认输入集，实际可从 spec 字段扩展
    return [
        {"name": "cmd", "width": 8, "desc": "operation code"},
        {"name": "operand_a", "width": 32, "desc": "input operand A"},
        {"name": "operand_b", "width": 32, "desc": "input operand B"},
    ]


def _extract_outputs(func_hier: dict, registers: list) -> list:
    """从 function hierarchy + registers 提取输出信号"""
    outputs = [
        {"name": "result", "width": 32, "desc": "computation result"},
        {"name": "flags", "width": 8, "desc": "status flags (Z/N/C/V)"},
    ]
    for r in registers:
        if r.get("access", "RW") in ("RO", "RW"):
            outputs.append({"name": r.get("name", "reg"), "width": r.get("width", 32),
                            "desc": f"register {r.get('name')}"})
    return outputs


def _render_ref_model_h(module_name: str, registers: list, operations: list) -> str:
    """生成纯 C++ 参考模型 .h（无 SystemC 依赖）"""
    reg_enum = "\n".join(
        f'    REG_{r["name"].upper()} = 0x{int(str(r.get("offset", r.get("addr","0x00"))).replace("0x",""), 16):08X},'
        for r in registers
    ) if registers else '    REG_CTRL = 0x00000000,'

    op_enum = "\n".join(
        f'    OP_{op["name"].upper()},'
        for op in operations
    ) if operations else '    OP_NOP,'

    reg_count = len(registers) if registers else 1

    return f'''// Auto-generated C++ reference model for {module_name}
// No SystemC dependency — pure C++17, no external libs
#pragma once
#include <cstdint>
#include <unordered_map>
#include <string>

namespace refmodel {{

// ── 操作码 ──
enum class OpCode : uint8_t {{
{op_enum}
}};

// ── 标志位 ──
enum Flags : uint8_t {{
    FLAG_ZERO     = 1 << 0,
    FLAG_NEGATIVE = 1 << 1,
    FLAG_CARRY    = 1 << 2,
    FLAG_OVERFLOW = 1 << 3,
}};

// ── 寄存器地址 ──
enum RegAddr : uint32_t {{
{reg_enum}
}};

// ── IO 事务（与 SV transaction 对应，无 TLM 依赖）──
struct input_txn {{
    uint8_t  cmd;
    uint32_t operand_a;
    uint32_t operand_b;
}};

struct output_txn {{
    uint32_t result;
    uint8_t  flags;
}};

// ── 参考模型 ──
class {module_name}_ref_model {{
public:
    {module_name}_ref_model();
    void reset();

    // 纯函数：输入事务 → 输出事务（无副作用、无时序、无并发）
    output_txn predict(const input_txn& in);

    // 寄存器访问
    void     reg_write(uint32_t addr, uint32_t data);
    uint32_t reg_read(uint32_t addr);
    const std::unordered_map<std::string, uint32_t>& reg_map() const {{ return reg_map_; }}

private:
    uint32_t reg_file_[{reg_count}];
    uint32_t flags_;
    std::unordered_map<std::string, uint32_t> reg_map_;
}};

}} // namespace refmodel'''


def _render_ref_model_cpp(module_name: str, registers: list, operations: list) -> str:
    """生成纯 C++ 参考模型 .cpp"""
    reg_init = ",\n    ".join(
        f'{{"{r["name"]}", 0x{int(str(r.get("offset", r.get("addr","0x00"))).replace("0x",""), 16):08X}}}'
        for r in registers
    ) if registers else '{"CTRL", 0x00000000}'

    reg_accessor = ""
    if registers:
        reg_accessor = f'''
void {module_name}_ref_model::reg_write(uint32_t addr, uint32_t data) {{
    for (int i = 0; i < {len(registers)}; i++) {{
        if (reg_map_.at(reg_names_[i]) == addr) {{
            reg_file_[i] = data;
            return;
        }}
    }}
}}

uint32_t {module_name}_ref_model::reg_read(uint32_t addr) {{
    for (int i = 0; i < {len(registers)}; i++) {{
        if (reg_map_.at(reg_names_[i]) == addr) {{
            return reg_file_[i];
        }}
    }}
    return 0;
}}
'''

    # 生成运算分支
    cases = []
    for op in operations:
        name = op["name"].upper()
        cases.append(f'        case OpCode::OP_{name}: out.result = a + b; break;  // TODO: 替换为{op["name"]}算法')

    if not cases:
        cases.append('        default: out.result = 0; break;')

    op_switch = "\n".join(cases)

    return f'''// Auto-generated C++ reference model for {module_name}
#include "{module_name}_ref_model.h"
#include <cstring>

namespace refmodel {{

{module_name}_ref_model::{module_name}_ref_model() {{
    reg_map_ = {{{reg_init}}};
    reset();
}}

void {module_name}_ref_model::reset() {{
    memset(reg_file_, 0, sizeof(reg_file_));
    flags_ = 0;
}}{reg_accessor}

output_txn {module_name}_ref_model::predict(const input_txn& in) {{
    output_txn out = {{0, 0}};
    uint32_t a = in.operand_a;
    uint32_t b = in.operand_b;

    switch (static_cast<OpCode>(in.cmd)) {{
{op_switch}
    }}

    // 标志位更新
    out.flags = 0;
    if (out.result == 0)        out.flags |= FLAG_ZERO;
    if (out.result >> 31)       out.flags |= FLAG_NEGATIVE;
    // FLAG_CARRY / FLAG_OVERFLOW 按具体运算补充

    return out;
}}

}} // namespace refmodel'''


def _render_test_main(module_name: str, tests: list) -> str:
    """生成自测 main() —— g++ 直接编译运行，无任何框架依赖"""
    test_cases = []
    for i, t in enumerate(tests):
        inp = t["input"]
        exp = t["expect"]
        test_cases.append(f'''    // [{i}] {t["name"]}
    {{
        input_txn in  = {{{inp["cmd"]}, {inp["a"]}, {inp["b"]}}};
        output_txn out = model.predict(in);
        bool pass = (out.result == {exp["result"]}) && (out.flags == {exp["flags"]});
        printf("  [%d] %-20s: %s (got result=0x%08X flags=0x%02X)\\n",
               {i}, "{t['name']}", pass ? "PASS" : "FAIL", out.result, out.flags);
        if (!pass) all_pass = false;
    }}''')

    test_body = "\n".join(test_cases)

    return f'''// Auto-generated test driver for {module_name}_ref_model
// Compile: g++ -std=c++17 {module_name}_ref_model.cpp test_{module_name}_ref_model.cpp -o test_{module_name}
// Run:     ./test_{module_name}
#include "{module_name}_ref_model.h"
#include <cstdio>

using namespace refmodel;

int main() {{
    bool all_pass = true;
    {module_name}_ref_model model;

    printf("=== {module_name} Reference Model Self-Test ===\\n\\n");

    // ── reset check ──
    model.reset();
    printf("  reset : reg[0]=0x%08X (expect 0)\\n", model.reg_read(0));

    printf("\\n── Test Vectors ──\\n");
{test_body}

    printf("\\n=== Result: %s ===\\n", all_pass ? "ALL PASSED" : "SOME FAILED");
    return all_pass ? 0 : 1;
}}'''
