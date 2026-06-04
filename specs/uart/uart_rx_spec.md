# UART RX 模块规格

## 功能描述
UART 接收模块负责将串行数据接收并转换为并行数据。

## 架构
```
RX Pin → Sampling (3x/8x/16x) → Shift Register → RX FIFO (16x8) → APB Bus
             ↑
        Baud Gen (16x)
```

## 模块级需求 (BT)
- **REQ_BT_002**: RX 接收模块功能验证
- **REQ_BT_004**: FIFO 缓冲区管理验证（overflow/underflow）

## 单元级需求 (UT)
- **REQ_UT_004**: RX 采样计数器验证 (3x/8x/16x 过采样)
- **REQ_UT_005**: RX 奇偶校验逻辑验证 (N/E/O)
- **REQ_UT_007**: FIFO overflow/underflow 检测

## 测试点
1. 正常接收: 8N1, 9600bps
2. 错误注入: 奇偶校验错误, 帧错误, 溢出错误

## 关联
- 父文档: uart_chip_spec.md
