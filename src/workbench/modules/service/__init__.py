"""工程服务入口 —— 面向客户的三条业务工作流。

它们**不是新引擎**：只做导航与编排，数据来自 run 目录/文件契约，执行仍走
现有 `flow.pipeline` / `InfrastructureManager` / `PipelineExecutionService`。
"""
