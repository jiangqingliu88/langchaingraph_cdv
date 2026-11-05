"""ISA 激励 —— 归属「验证构建」业务线。

场景 DSL → ISA 事务层 IR。工具在 `src/tools/generation/isa_gen_tools/`，
本模块只负责把它的产物摆成能看的四张表 —— 界面经 bridge 绑定访问工具，
**不 import 工具包**。
"""
from .module import IsaGenModule

__all__ = ["IsaGenModule"]
