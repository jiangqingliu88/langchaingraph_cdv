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
