# ALU 算术运算模块规格

## 功能描述
执行 ADD/SUB/MUL/DIV 四种算术运算，32bit 数据通路。
MUL 可选择单周期乘法器或 Booth 乘法器（面积/时序权衡）。

## 模块级需求 (BT)
- **REQ_ALU_BT_001**: 算术运算模块功能验证 (ADD/SUB/MUL/DIV)
- **REQ_ALU_BT_002**: 乘法器配置验证 (单周期 vs Booth)
- **REQ_ALU_BT_003**: 除法器验证 (恢复余数法)

## 单元级需求 (UT)
- **REQ_ALU_UT_001**: ADD 加法器验证 (carry-lookahead, 32bit)
- **REQ_ALU_UT_002**: SUB 减法器验证 (2's complement)
- **REQ_ALU_UT_003**: MUL Booth 乘法器验证 (Booth-2 编码 + Wallace tree)
- **REQ_ALU_UT_004**: DIV 恢复余数除法器验证
- **REQ_ALU_UT_005**: 溢出检测逻辑验证

## 运算表
| ALU_OP[3:0] | 运算 | 公式 | 标志 |
|-------------|------|------|------|
| 4'b0000 | ADD  | RESULT = A + B | N,Z,C,V |
| 4'b0001 | SUB  | RESULT = A - B | N,Z,C,V |
| 4'b0010 | MUL  | RESULT = A * B | N,Z |
| 4'b0011 | DIV  | RESULT = A / B | N,Z |
| 4'b0100 | DIVU | RESULT = A / B (unsigned) | N,Z |

## 测试点
1. ADD: 正+正, 正+负, 负+负, 溢出
2. SUB: 正-正, 正-负, 负-负, 借位
3. MUL: 0×N, -1×N, 最大×最大, 溢出
4. DIV: N/1, N/N, 0/N, 除零异常

## 关联
- 父文档: alu_chip_spec.md
- 子文档: alu_logic_spec.md, alu_shift_spec.md, alu_flags_spec.md
