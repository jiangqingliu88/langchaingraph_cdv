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
