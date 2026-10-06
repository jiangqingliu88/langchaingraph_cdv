"""重写 _gen_apb_register_model：state/body 带 4 空格缩进（模板内插需要）。"""
import re
from pathlib import Path

p = Path(r"D:\SignOffAI\src\tools\uvm_tools\tool_find_spec_yaml\main.py")
src = p.read_text(encoding="utf-8")

start_marker = "def _gen_apb_register_model(registers: list) -> tuple:"
start = src.index(start_marker)
rest = src[start:]
m = re.search(r"\n(?=\ndef )", rest)
end = start + m.start() + 1 if m else len(src)

IND = " " * 4  # 函数体内
IND2 = " " * 8  # 内层

new_fn = '''def _gen_apb_register_model(registers: list) -> tuple:
    """从 spec.registers 动态生成 APB 寄存器参考模型（state 变量声明, process_in 函数体）。

    按 spec 寄存器表生成（对齐 DUT 映射，避免硬编码偏移错位）。输出带 4 空格缩进，
    供 predictor.sv.j2 模板 `{{ pred.model_body }}` 直接内插（模板无二次缩进）。
      - 每个寄存器一个 `reg_<name>` 状态变量
      - RW/WO 偏移写回（psel&&penable&&pwrite），RW 读回 prdata
      - RO 只读回（prdata = reg_<name>，不写回）
      - 偏移统一用 4 位十六进制常量 `4'hX`（地址 0x00-0x0F 内）
    """
    def _ind(block: list, base: str = "    ") -> list:
        return [base + ln if ln.strip() else ln for ln in block]

    if not registers:
        # 无寄存器表：退化为请求字段透传（至少 paddr/pwdata/pwrite 对齐，避免全 0）
        body = _ind([
            "// 无寄存器表：透传请求字段（prdata 无法预测，置 0）",
            "pred.paddr   = t.paddr;",
            "pred.pwdata  = t.pwdata;",
            "pred.pwrite  = t.pwrite;",
            "pred.psel    = t.psel;",
            "pred.penable = t.penable;",
            "pred.prdata  = 8'h00;",
            "pred.req_id  = t.req_id;",
        ])
        return "", "\\n".join(body)

    state_lines = _ind(["// ── APB 寄存器模型状态（按 spec 寄存器表动态生成）──"])
    write_cases = []
    read_cases = []
    for reg in registers:
        name = reg.get("name", "reg")
        offset = reg.get("offset", "0x00")
        access = reg.get("access", "RW").upper()
        width = int(reg.get("width", 8))
        hexw = "4'h" + format(int(offset, 16), "x")
        var = f"reg_{name}"
        state_lines.append(f"{IND}logic [{width-1}:0] {var} = {width}'h0;")
        if access in ("RW", "WO"):
            write_cases.append(f"{IND2}{hexw}: {var} = t.pwdata;")
        if access in ("RW", "RO"):
            read_cases.append(f"{IND2}{hexw}: pred.prdata = {var};")

    body_lines = _ind([
        "// 复制请求字段，预测 prdata",
        "pred.paddr   = t.paddr;",
        "pred.pwdata  = t.pwdata;",
        "pred.pwrite  = t.pwrite;",
        "pred.psel    = t.psel;",
        "pred.penable = t.penable;",
        "pred.prdata  = 8'h00;",
        "pred.req_id  = t.req_id;",
        "",
        "if (t.pwrite) begin",
        "  // 写：APB 写时序 psel && penable && pwrite",
        "  if (t.psel && t.penable) begin",
        "    case (t.paddr[3:0])",
    ])
    body_lines += write_cases
    body_lines += _ind([
        "      default: ;",
        "    endcase",
        "  end",
        "end else if (t.psel) begin",
        "  // 读：APB 读时序 psel && !pwrite（组合逻辑），预测 prdata",
        "  case (t.paddr[3:0])",
    ])
    body_lines += read_cases
    body_lines += _ind([
        "      default: pred.prdata = 8'h00;",
        "    endcase",
        "  end",
        "end",
    ])
    return "\\n".join(state_lines), "\\n".join(body_lines)


'''
src = src[:start] + new_fn + src[end:]
p.write_text(src, encoding="utf-8")
print("replaced with indented version")
