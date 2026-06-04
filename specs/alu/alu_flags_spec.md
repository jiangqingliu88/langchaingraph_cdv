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
