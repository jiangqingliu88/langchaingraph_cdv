"""应用服务层 —— CLI 与 Workbench 共用的业务编排入口。

边界：`src/app` 可以 import CLI 时代码之外的层（L1/L2/L3/core），但**不反向**
被 core/layers 依赖。CLI 只做参数解析与输出，真正的编排放这里。
"""
