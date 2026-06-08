# ALU APB 寄存器接口规格

## 功能描述
APB 从接口，提供 ALU 操作数和运算类型的配置寄存器，以及结果和标志位的状态寄存器。

## 模块级需求 (BT)
- **REQ_ALU_BT_007**: APB 寄存器接口验证 (读写/地址译码/错误响应)

## 寄存器 Map

| 寄存器 | 偏移 | 位宽 | 访问 | 复位值 | 描述 |
|--------|------|------|------|--------|------|
| ALU_CTRL | 0x00 | 8 | RW | 8'h00 | 控制寄存器 |
| ALU_OPA | 0x04 | 32 | RW | 32'h0 | 操作数 A |
| ALU_OPB | 0x08 | 32 | RW | 32'h0 | 操作数 B |
| ALU_RESULT | 0x0C | 32 | RO | 32'h0 | 运算结果 |
| ALU_FLAGS | 0x10 | 4 | RO | 4'h0 | 标志位 [3:0] = {N,Z,C,V} |
| ALU_STATUS | 0x14 | 8 | RO | 8'h01 | 状态 (bit0=ready) |
| ALU_CFG | 0x18 | 8 | RW | 8'h00 | 配置 (bit0=单周期, bit1=流水线) |
| ALU_VERSION | 0x1C | 8 | RO | 8'h01 | IP 版本 v0.1 |

## ALU_CTRL 字段
| 位段 | 名称 | 访问 | 复位 | 描述 |
|------|------|------|------|------|
| [3:0] | ALU_OP | RW | 4'h0 | 运算选择: 0=ADD,1=SUB,2=MUL,3=DIV,4=DIVU,5=AND,6=OR,7=XOR,8=NOR,9=NOT,10=SLL,11=SRL,12=SRA |
| [4] | START | RW | 1'b0 | 写1启动运算 (多周期模式), 单周期模式自动启动 |
| [5] | IRQ_EN | RW | 1'b0 | 运算完成中断使能 |
| [7:6] | RSVD | RO | 2'b0 | 保留 |

## 使用流程
```
单周期模式:
  1. 写 ALU_OPA = A
  2. 写 ALU_OPB = B
  3. 写 ALU_CTRL = {RSVD, IRQ_EN, START, ALU_OP}
  4. 读 ALU_RESULT (组合逻辑, 立即有效)
  5. 读 ALU_FLAGS

多周期模式:
  1. 写 ALU_OPA, ALU_OPB
  2. 写 ALU_CTRL (START=1) → 触发运算
  3. 轮询 ALU_STATUS[0] (ready)
  4. ready=1 时读 ALU_RESULT, ALU_FLAGS
```

## 测试点
1. APB 读写所有寄存器
2. 未映射地址返回 pslverr
3. 单周期模式下连续运算
4. 多周期模式下 START→ready 握手
5. 读写冲突 (运算中写新操作数)

## 关联
- 父文档: alu_chip_spec.md
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
# ALU IP 芯片级规格

## 概述
ALU (Arithmetic Logic Unit) IP 支持 16 种算术/逻辑运算，32bit 数据通路，APB 配置接口。
面向 RISC-V RV32I 指令集，可配置为单周期或多周期模式。

## 芯片级需求
- **REQ_ALU_CHIP_001**: ALU IP 完整验证，覆盖所有 16 种运算和标志位
- 时序: 单周期 (combinational) 或 2-cycle (pipelined)
- 工艺: 28nm, 目标频率 500MHz

## 关键指标
| 参数 | 规格 |
|------|------|
| 数据宽度 | 32 bit |
| 运算类型 | 16 种 (ALU_OP[3:0]) |
| 输入 | A[31:0], B[31:0], ALU_OP[3:0] |
| 输出 | RESULT[31:0], FLAGS[3:0] (N/Z/C/V) |
| 接口 | APB (配置) + Native (数据) |

## 子系统
1. 算术运算通路 (ADD/SUB/MUL/DIV)
2. 逻辑运算通路 (AND/OR/XOR/NOT)
3. 移位运算通路 (SLL/SRL/SRA)
4. 比较运算通路 (SLT/SLTU)
5. 标志位生成 (N/Z/C/V)
6. APB 寄存器接口
# ALU 标志位生成模块规格

## 功能描述
根据运算结果生成 4 个标志位: N (Negative), Z (Zero), C (Carry/Borrow), V (Overflow)。

## 模块级需求 (BT)
- **REQ_ALU_BT_006**: 标志位生成验证 (N/Z/C/V 全部场景)

## 单元级需求 (UT)
- **REQ_ALU_UT_014**: N 标志位验证 (RESULT[31])
- **REQ_ALU_UT_015**: Z 标志位验证 (RESULT == 0)
- **REQ_ALU_UT_016**: C 标志位验证 (ADD carry / SUB borrow)
- **REQ_ALU_UT_017**: V 标志位验证 (signed overflow: 正+正→负, 负+负→正)

## 标志位定义
| 标志 | 名称 | 条件 |
|------|------|------|
| N | Negative | RESULT[31] == 1 |
| Z | Zero | RESULT == 0 |
| C | Carry | ADD: cout[32]; SUB: ~cout[32] |
| V | Overflow | (A[31]==B[31]) && (RESULT[31]!=A[31]) |

## 测试点
1. N=1: 0 - 1 = -1 → N=1, Z=0, C=1, V=0
2. Z=1: 5 - 5 = 0 → N=0, Z=1, C=0, V=0
3. C=1: 0xFFFFFFFF + 1 → N=0, Z=1, C=1, V=0
4. V=1: 0x7FFFFFFF + 1 → N=1, Z=0, C=0, V=1
5. 逻辑运算后 C=0, V=0

## 关联
- 父文档: alu_chip_spec.md
# ALU 逻辑运算模块规格

## 功能描述
执行 AND/OR/XOR/NOR/NOT 五种按位逻辑运算，32bit 数据通路，纯组合逻辑。

## 模块级需求 (BT)
- **REQ_ALU_BT_004**: 逻辑运算模块功能验证 (AND/OR/XOR/NOR/NOT)

## 单元级需求 (UT)
- **REQ_ALU_UT_006**: AND 按位与验证
- **REQ_ALU_UT_007**: OR 按位或验证
- **REQ_ALU_UT_008**: XOR 按位异或验证
- **REQ_ALU_UT_009**: NOT 按位取反验证

## 运算表
| ALU_OP[3:0] | 运算 | 公式 | 标志 |
|-------------|------|------|------|
| 4'b0101 | AND  | RESULT = A & B | N,Z |
| 4'b0110 | OR   | RESULT = A | B | N,Z |
| 4'b0111 | XOR  | RESULT = A ^ B | N,Z |
| 4'b1000 | NOR  | RESULT = ~(A | B) | N,Z |
| 4'b1001 | NOT  | RESULT = ~A | N,Z |

## 测试点
1. 全 0 输入
2. 全 1 输入 (0xFFFFFFFF)
3. 交替位模式 (0xAAAAAAAA & 0x55555555)
4. 随机 1000 组

## 关联
- 父文档: alu_chip_spec.md
# ALU 移位运算模块规格

## 功能描述
执行 SLL/SRL/SRA 三种移位运算，32bit 数据通路。移位量由 B[4:0] 指定 (0-31)。

## 模块级需求 (BT)
- **REQ_ALU_BT_005**: 移位运算模块功能验证 (SLL/SRL/SRA)

## 单元级需求 (UT)
- **REQ_ALU_UT_010**: SLL 逻辑左移验证 (shift 0/1/16/31)
- **REQ_ALU_UT_011**: SRL 逻辑右移验证
- **REQ_ALU_UT_012**: SRA 算术右移验证 (符号扩展)
- **REQ_ALU_UT_013**: 桶形移位器验证 (单周期全移位)

## 运算表
| ALU_OP[3:0] | 运算 | 公式 | 标志 |
|-------------|------|------|------|
| 4'b1010 | SLL  | RESULT = A << B[4:0] | N,Z |
| 4'b1011 | SRL  | RESULT = A >> B[4:0] (逻辑) | N,Z |
| 4'b1100 | SRA  | RESULT = A >>> B[4:0] (算术) | N,Z |

## 测试点
1. 移位量 0 (直接透传)
2. 移位量 1 (边界)
3. 移位量 31 (最大)
4. SRA 负数值符号扩展
5. SRA 正数值填 0

## 关联
- 父文档: alu_chip_spec.md
