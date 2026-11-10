"""
Skills 包 —— 七 Agent 最终架构（真实功能，无 Mock）

  design    设计智能体   = spec + design + rtl
  model     模型智能体   = 多语言参考模型
  verify    验证开发智能体 = uvm + test + assert
  ops       运维调度智能体 = 编译仿真
  coverage  覆盖率智能体  = 收集分析
  debug     调试智能体    = 失败分析
  audit     审计智能体    = 质量审查 + 签核
"""
from src.skills.design import DesignExecutor
from src.skills.model import ModelExecutor
from src.skills.verify import VerifyExecutor
from src.skills.ops import OpsExecutor
from src.skills.coverage import CoverageExecutor
from src.skills.debug import DebugExecutor
from src.skills.audit import AuditExecutor

__all__ = [
    "DesignExecutor", "ModelExecutor", "VerifyExecutor",
    "OpsExecutor", "CoverageExecutor", "DebugExecutor", "AuditExecutor",
]
