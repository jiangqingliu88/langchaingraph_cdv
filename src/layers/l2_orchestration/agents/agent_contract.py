"""
Agent 标准契约 —— 让各智能体成为"可反复调用的微服务"

核心目标: Agent 无状态、标准接口、决策层可驱动

  AgentRequest  决策层/编排层 → Agent 的标准化输入
  AgentResponse Agent → 编排层 的标准化输出
  AgentContext  execute_task 内部的状态传递（替代 self._xxx 残留）

用法:
    request = AgentRequest(input="...", output_dir="...", params={"target_bins": [...]})
    response = await agent.execute(request)
    # → AgentResponse(output=..., data=..., score=..., status=...)
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 标准输入: AgentRequest
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentRequest:
    """决策层/编排层下发给 Agent 的标准化输入。

    无状态: 所有上下文都在这里，Agent 不依赖 self._xxx 残留。
    """
    input: str = ""                        # 主要输入（spec 文本 / 指令）
    ctx: Dict[str, Any] = field(default_factory=dict)   # 上游数据（spec/design_arch/env...）
    output_dir: str = ""                   # 输出目录
    params: Dict[str, Any] = field(default_factory=dict)  # 决策层下发的动作参数
    fix: Optional[Dict[str, Any]] = None   # 修复请求 {suggestion, errors}

    def to_task(self) -> Dict[str, Any]:
        """转成现有的 task dict（向后兼容）。"""
        task = {"ctx": self.ctx, "output_dir": self.output_dir}
        if self.fix:
            task["input"] = _json_dumps({"fix": self.fix})
        else:
            task["input"] = self.input
        if self.params:
            task["params"] = self.params
        return task


# ═══════════════════════════════════════════════════════════════
# 标准输出: AgentResponse
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentResponse:
    """Agent 返回给编排层的标准化输出。"""
    output: str = ""                       # 人类可读输出
    data: Dict[str, Any] = field(default_factory=dict)   # 结构化数据（写回 ctx）
    score: int = 0
    status: str = "unknown"                # passed | degraded | failed | skipped | error
    errors: List[str] = field(default_factory=list)

    @classmethod
    def from_agent_result(cls, result) -> "AgentResponse":
        """从现有 AgentResult 构造。"""
        data = result.data if hasattr(result, 'data') else {}
        if isinstance(data, dict):
            score = data.get("score", 0)
            output = data.get("output", "")
        else:
            score = 0
            output = ""
        return cls(
            output=output,
            data=data if isinstance(data, dict) else {},
            score=score,
            status="passed" if result.success else "failed",
        )

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════
# 内部状态传递: AgentContext（替代 self._xxx）
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentContext:
    """execute_task 内部需要跨方法传递的状态。

    之前用 self._last_output_dir / self._module_name 等实例变量，
    并发或重复调用时会互相污染。现在改为显式传递。
    """
    output_dir: str = ""
    module_name: str = ""
    ctx_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        # 从 ctx_data 自动提取模块名
        if not self.module_name:
            for key in ("spec", "design_arch", "rtl"):
                v = self.ctx_data.get(key)
                if isinstance(v, dict):
                    nm = v.get("design_name") or v.get("module_name")
                    if nm and nm.lower() not in ("dut", "dut_top", "dut_env", ""):
                        self.module_name = nm
                        break


# ═══════════════════════════════════════════════════════════════
# 工具
# ═══════════════════════════════════════════════════════════════

def _json_dumps(obj) -> str:
    import json
    return json.dumps(obj, ensure_ascii=False, default=str)
