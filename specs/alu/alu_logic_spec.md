# ALU 逻辑运算模块
<!--
  module: alu_logic
  parent: ALU
  level: BT
  data_width: 32
  operations: [AND, OR, XOR, NOR, NOT]
  requirements: [REQ_ALU_LOGIC_001]
-->

## 1. 概述
执行 AND/OR/XOR/NOR/NOT 五种按位逻辑运算，32bit 数据通路，纯组合逻辑。

## 2. 功能需求

### 按位与运算
**级别**：P0
**类型**：FUNCTIONAL
**描述**：32bit 按位 AND，输出 result = A & B
**验收标准**：覆盖率 100%，随机测试 10000 次

### 按位或运算
**级别**：P0
**类型**：FUNCTIONAL
**描述**：32bit 按位 OR，输出 result = A | B
**验收标准**：覆盖率 100%

### 按位异或运算
**级别**：P0
**类型**：FUNCTIONAL
**描述**：32bit 按位 XOR，输出 result = A ^ B
**验收标准**：覆盖率 100%

### 按位或非/非运算
**级别**：P1
**类型**：FUNCTIONAL
**描述**：NOR 和 NOT 运算
**验收标准**：覆盖率 ≥ 95%

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| op_a[31:0] | 32 | INPUT | Native | 操作数 A |
| op_b[31:0] | 32 | INPUT | Native | 操作数 B |
| op_sel[2:0] | 3 | INPUT | Native | AND/OR/XOR/NOR/NOT |
| result[31:0] | 32 | OUTPUT | Native | 运算结果 |

## 4. 时序约束

| 路径 | 约束 | 说明 |
|------|------|------|
| op_a/op_b → result | ≤ 1ns | 纯组合逻辑 |

## 5. 功耗约束

| 模式 | 功耗 | 说明 |
|------|------|------|
| Active | ≤ 1mW | 纯组合，功耗极低 |
