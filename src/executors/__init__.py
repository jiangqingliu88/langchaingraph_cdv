"""
Agents 包 —— 七 Agent 最终架构（真实功能，无 Mock）

  design    设计智能体   = spec + design + rtl
  model     模型智能体   = 多语言参考模型
  verify    验证开发智能体 = uvm + test + assert
  ops       运维调度智能体 = 编译仿真
  coverage  覆盖率智能体  = 收集分析
  debug     调试智能体    = 失败分析
  audit     审计智能体    = 质量审查 + 签核
"""
from src.executors.design import DesignExecutor
from src.executors.model import ModelExecutor
from src.executors.verify import VerifyExecutor
from src.executors.ops import OpsExecutor
from src.executors.coverage import CoverageExecutor
from src.executors.debug import DebugExecutor
from src.executors.audit import AuditExecutor

__all__ = [
    "DesignExecutor", "ModelExecutor", "VerifyExecutor",
    "OpsExecutor", "CoverageExecutor", "DebugExecutor", "AuditExecutor",
]
