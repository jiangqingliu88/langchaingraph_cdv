"""
统一通信层 —— A2A 风格（Agent-to-Agent Protocol）

基于 JSON-RPC 2.0 传输层，method 采用 A2A 标准语义:

  agents/discover  → 发现所有 Agent 的能力卡片
  tasks/send       → 派任务给指定 Agent（修改 Env/Model/RTL 统一走这个）
  tasks/get        → 查询任务状态
  tasks/cancel     → 取消任务

请求示例（决策层下发"更新模型"指令）:
  {"jsonrpc":"2.0","method":"tasks/send",
   "params":{"task":{"agent":"model","action":"update",
                     "reason":"比对失败，模型过时",
                     "params":{"model_type":"cpp"}}},
   "id":1}

关键设计:
  - 无论"修改 Env"还是"修改 Model"，都走 tasks/send，只是 task.agent 不同
  - task.reason 记录修改理由（供证据链追溯）
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# A2A 核心概念: AgentCard + Task
# ═══════════════════════════════════════════════════════════════

class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentCard:
    """Agent 能力卡片（agents/discover 返回）"""
    name: str
    description: str
    capabilities: List[str] = field(default_factory=list)  # 支持的 action

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Task:
    """可委派的任务单元（tasks/send 的载荷）"""
    agent: str                          # 目标 Agent: design/model/verify/ops/coverage/debug/audit
    action: str = "execute"             # 动作: generate/update/refactor/analyze/...
    reason: str = ""                    # 修改理由（供证据链追溯）
    params: Dict[str, Any] = field(default_factory=dict)

    @property
    def task_id(self) -> str:
        return f"{self.agent}.{self.action}"


# ═══════════════════════════════════════════════════════════════
# JSON-RPC 2.0 信封
# ═══════════════════════════════════════════════════════════════

@dataclass
class JsonRpcRequest:
    """JSON-RPC 2.0 请求"""
    method: str                 # "tasks/send" | "agents/discover" | "tasks/get"
    params: Dict[str, Any] = field(default_factory=dict)
    id: Any = None
    jsonrpc: str = "2.0"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)

    @classmethod
    def from_json(cls, text: str) -> "JsonRpcRequest":
        d = json.loads(text)
        return cls(method=d.get("method", ""), params=d.get("params", {}),
                   id=d.get("id"), jsonrpc=d.get("jsonrpc", "2.0"))


@dataclass
class JsonRpcResponse:
    """JSON-RPC 2.0 响应"""
    result: Any = None
    id: Any = None
    jsonrpc: str = "2.0"
    error: Dict[str, Any] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, default=str)


# ═══════════════════════════════════════════════════════════════
# A2A 调度器
# ═══════════════════════════════════════════════════════════════

class A2ADispatcher:
    """A2A 协议调度器：处理 agents/discover + tasks/send + tasks/get。

    用法:
        dispatcher = A2ADispatcher()
        resp = await dispatcher.handle_json(
            '{"jsonrpc":"2.0","method":"tasks/send","params":{"task":{...}},"id":1}')
    """

    def __init__(self, registry=None):
        from src.layers.l2_orchestration.executors.registry import ExecutorRegistry
        self.registry = registry or ExecutorRegistry.get_instance()
        self._task_status: Dict[str, TaskStatus] = {}

    # ── Agent 能力卡片注册表 ──

    AGENT_CARDS = {
        "design":   AgentCard("design",   "设计智能体：Spec→架构→RTL",  ["generate", "refactor"]),
        "model":    AgentCard("model",    "模型智能体：多语言参考模型", ["generate", "update"]),
        "verify":   AgentCard("verify",   "验证开发智能体：UVM+用例+断言", ["generate", "add_directed"]),
        "ops":      AgentCard("ops",      "运维调度智能体：编译仿真",   ["run_sim", "retry"]),
        "coverage": AgentCard("coverage", "覆盖率智能体：收集分析",     ["analyze"]),
        "debug":    AgentCard("debug",    "调试智能体：失败分析",       ["analyze"]),
        "audit":    AgentCard("audit",    "审计智能体：签核证据链",     ["signoff"]),
    }

    async def handle(self, request: JsonRpcRequest, ctx: dict = None,
                     output_dir: str = "output") -> JsonRpcResponse:
        """分发 A2A method。"""
        method = request.method
        if method == "agents/discover":
            return self._discover(request)
        elif method == "tasks/send":
            return await self._send_task(request, ctx, output_dir)
        elif method == "tasks/get":
            return self._get_task(request)
        elif method == "tasks/cancel":
            return self._cancel_task(request)
        else:
            return JsonRpcResponse(
                error={"code": -32601, "message": f"Method not found: {method}"},
                id=request.id)

    # ── method 实现 ──

    def _discover(self, request) -> JsonRpcResponse:
        """返回所有 Agent 的能力卡片。"""
        cards = [card.to_dict() for card in self.AGENT_CARDS.values()]
        return JsonRpcResponse(result={"agents": cards}, id=request.id)

    async def _send_task(self, request, ctx, output_dir) -> JsonRpcResponse:
        """派任务给指定 Agent。task = {agent, action, reason, params}"""
        task_dict = request.params.get("task", {})
        task = Task(
            agent=task_dict.get("agent", ""),
            action=task_dict.get("action", "execute"),
            reason=task_dict.get("reason", ""),
            params=task_dict.get("params", {}),
        )

        agent = self.registry.get_agent_instance(task.agent)
        if not agent:
            return JsonRpcResponse(
                error={"code": -32002, "message": f"Unknown agent: {task.agent}"},
                id=request.id)

        self._task_status[task.task_id] = TaskStatus.RUNNING
        try:
            # 统一派活：task → execute_task
            agent_task = {
                "ctx": ctx or {},
                "input": task.reason or task.params.get("input", ""),
                "output_dir": output_dir,
                "params": {**task.params, "action": task.action, "reason": task.reason},
            }
            result = await agent.execute_task(agent_task)
            data = result.data if result.success and isinstance(result.data, dict) else {}
            self._task_status[task.task_id] = TaskStatus.COMPLETED
            return JsonRpcResponse(result={
                "task_id": task.task_id,
                "status": TaskStatus.COMPLETED.value,
                "data": data,
                "reason": task.reason,
            }, id=request.id)
        except Exception as e:
            self._task_status[task.task_id] = TaskStatus.FAILED
            return JsonRpcResponse(
                error={"code": -32000, "message": str(e)[:200]},
                id=request.id)

    def _get_task(self, request) -> JsonRpcResponse:
        """查询任务状态。"""
        task_id = request.params.get("task_id", "")
        status = self._task_status.get(task_id, TaskStatus.PENDING)
        return JsonRpcResponse(result={"task_id": task_id, "status": status.value},
                               id=request.id)

    def _cancel_task(self, request) -> JsonRpcResponse:
        task_id = request.params.get("task_id", "")
        self._task_status[task_id] = TaskStatus.CANCELLED
        return JsonRpcResponse(result={"task_id": task_id, "status": "cancelled"},
                               id=request.id)

    async def handle_json(self, json_text: str, ctx: dict = None,
                          output_dir: str = "output") -> str:
        """处理 JSON-RPC 字符串，返回 JSON 响应字符串。"""
        req = JsonRpcRequest.from_json(json_text)
        resp = await self.handle(req, ctx, output_dir)
        return resp.to_json()
