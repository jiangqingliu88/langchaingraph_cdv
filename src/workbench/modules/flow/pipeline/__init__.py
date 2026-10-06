"""验证流程 —— 归属「验证管理系统」业务线。

中窗格：启动一次闭环，然后看着它跑。进度来自磁盘上的运行日志，
所以「在终端里启动、在界面里看」天然成立，关掉窗口再打开也还能接着看。
"""
from .module import PipelineModule

__all__ = ["PipelineModule"]
