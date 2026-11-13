"""跨层异常 —— 身份/编排/账本的错误类型收口。

放 `core.runtime` 的原因：这些异常会被 repository、analysis、verify、ledger
共同捕获；如果各自定义一份，调用方就得 import 具体实现层，依赖方向会反过来。
"""
from __future__ import annotations


class CaseModelError(ValueError):
    """模型无法构建 —— 结构性错误（缺 object/dimensions、顶层不是 mapping）。"""


class CaseListError(ValueError):
    """外部真实 case 列表无法解析。"""


class StepOrderError(RuntimeError):
    """流水线步骤顺序 / 依赖不满足。"""


class ContractAnchorMismatch(RuntimeError):
    """事实/契约与账本锚点不一致 —— 拒绝写入（deny-first）。"""


class PipelineError(RuntimeError):
    """编排层的通用失败（步骤失败、请求无效等）。"""


__all__ = [
    "CaseListError", "CaseModelError", "ContractAnchorMismatch",
    "PipelineError", "StepOrderError",
]
