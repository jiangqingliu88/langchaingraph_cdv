# UART 集成级规格

## 功能描述
UART 与 DMA、中断控制器等模块的集成验证。

## 集成级需求 (IT)
- **REQ_IT_001**: UART TX + DMA 联合数据传输验证
- **REQ_IT_002**: UART RX + DMA 接收缓冲管理验证
- **REQ_IT_003**: 多 UART 通道仲裁验证

## 系统级需求 (ST)
- **REQ_ST_001**: UART 子系统与 AXI4 总线正确交互
- **REQ_ST_002**: 中断控制器与 UART 联动验证
- **REQ_ST_003**: 功耗模式切换验证 (Active/Sleep)

## 测试场景
1. DMA 连续发送 1KB 数据
2. DMA 环形缓冲接收
3. 双 UART 通道交替发送
4. Sleep 唤醒后数据完整性

## 关联
- 父文档: uart_chip_spec.md
