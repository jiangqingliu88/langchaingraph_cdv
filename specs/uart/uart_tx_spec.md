# UART TX 模块规格

## 功能描述
UART 发送模块负责将并行数据转换为串行数据输出。

## 架构
```
APB Bus → TX FIFO (16x8) → Shift Register → TX Pin
                              ↑
                         Baud Gen (16x)
```

## 模块级需求 (BT)
- **REQ_BT_001**: TX 发送模块功能验证，覆盖所有数据位配置 (5/6/7/8)
- **REQ_BT_003**: 波特率发生器精度验证 (9600-115200)

## 单元级需求 (UT)
- **REQ_UT_001**: TX 移位寄存器行为验证
- **REQ_UT_002**: TX FIFO 读写指针验证（空/满/半满）
- **REQ_UT_003**: TX 状态机状态转换验证（IDLE→START→DATA→PARITY→STOP）

## 测试点
1. 正常发送: 8N1, 9600bps
2. 边界: 5 数据位, 115200bps
3. 错误注入: FIFO 溢出

## 关联
- 父文档: uart_chip_spec.md
- 子文档: uart_baud_spec.md
