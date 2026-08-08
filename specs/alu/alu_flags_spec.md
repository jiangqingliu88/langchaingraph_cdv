# alu_flags（模块级）
<!--
  module: alu_flags
  parent: ALU
  level: BT
  data_width: 32
  requirements: [REQ_ALU_FLAGS_001]
  flags: [N, Z, C, V]
-->

## 1. 概述
根据运算结果生成 4 个标志位: N (Negative), Z (Zero), C (Carry/Borrow), V (Overflow)。

## 2. 功能需求

### N 标志位
**级别**：P0
**类型**：FUNCTIONAL
**描述**：结果为负数时置位（result[31] == 1）
**验收标准**：所有 16 种运算的 N 标志正确

### Z 标志位
**级别**：P0
**类型**：FUNCTIONAL
**描述**：结果为零时置位（result == 0）
**验收标准**：所有 16 种运算的 Z 标志正确

### C 标志位
**级别**：P0
**类型**：FUNCTIONAL
**描述**：加法进位/减法借位标志
**验收标准**：ADD/SUB 运算的 C 标志正确

### V 标志位
**级别**：P1
**类型**：FUNCTIONAL
**描述**：有符号溢出标志
**验收标准**：正+正=负、负+负=正 时 V 置位

### 标志位时序
**级别**：P2
**类型**：TIMING
**描述**：标志位与运算结果同周期输出
**验收标准**：标志位延迟 ≤ 0.5ns (与 result 对齐)

## 3. 接口规范

| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| result[31:0] | 32 | INPUT | Native | 运算结果 |
| carry_out | 1 | INPUT | Native | 进位输入 |
| op_type[3:0] | 4 | INPUT | Native | 运算类型 |
| flags[3:0] | 4 | OUTPUT | Native | N/Z/C/V |

## 4. 时序约束

待补充

## 5. 功耗约束

| 模式 | 功耗 | 说明 |
|------|------|------|
| | Active | ≤ 0.5mW | 纯组合译码 |
