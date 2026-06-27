# UART 模块规格 — verify_architect 单独测试输入

## 模块信息
- **模块名**: uart_top
- **时钟**: clk (100MHz)
- **复位**: rst_n (异步低有效)

## 接口信号

| 信号名 | 方向 | 位宽 | 描述 |
|--------|------|------|------|
| clk | input | 1 | 系统时钟 |
| rst_n | input | 1 | 异步复位，低有效 |
| apb_paddr | input | 8 | APB 地址 |
| apb_psel | input | 1 | APB 片选 |
| apb_penable | input | 1 | APB 使能 |
| apb_pwrite | input | 1 | APB 写使能 |
| apb_pwdata | input | 32 | APB 写数据 |
| apb_prdata | output | 32 | APB 读数据 |
| apb_pready | output | 1 | APB 就绪 |
| apb_pslverr | output | 1 | APB 错误 |
| uart_tx | output | 1 | UART 发送 |
| uart_rx | input | 1 | UART 接收 |
| uart_cts | input | 1 | 清除发送 (流控) |
| uart_rts | output | 1 | 请求发送 (流控) |
| interrupt | output | 1 | 中断输出 |
| baud_div | input | 16 | 波特率分频系数 |

## 寄存器

| 寄存器 | 偏移 | 位宽 | 访问 | 描述 |
|--------|------|------|------|------|
| UART_CTRL | 0x00 | 8 | RW | 控制: [0]TX_EN [1]RX_EN [2]IRQ_EN [4:3]PARITY |
| UART_STATUS | 0x04 | 8 | RO | 状态: [0]TX_BUSY [1]RX_READY [2]TX_FULL [3]RX_EMPTY |
| UART_BAUD | 0x08 | 16 | RW | 波特率分频值 |
| UART_TXDATA | 0x0C | 8 | WO | 发送数据 |
| UART_RXDATA | 0x10 | 8 | RO | 接收数据 |

## 功能描述
UART 顶层模块集成 APB 从接口和 UART 收发逻辑。
支持 5/6/7/8 数据位，1/1.5/2 停止位，奇偶校验可选。
硬件流控 CTS/RTS 可选使能。
