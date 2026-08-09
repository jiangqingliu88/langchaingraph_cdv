"""
资源调度与并发控制

- ResourceScheduler: Agent 并发池管理、任务队列、License 管理
- DependencyGraph: 任务依赖图解析和可视化数据
"""
from __future__ import annotations

import asyncio, json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════
# 资源调度器
# ═══════════════════════════════════════════════════════════

@dataclass
class ResourcePool:
    """资源池"""
    max_agents: int = 8
    max_regressions: int = 2
    max_simulations: int = 3
    available_licenses: dict = field(default_factory=lambda: {
        "questa": 4, "vcs": 0, "xcelium": 0,
        "design_compiler": 0, "primetime": 0, "innovus": 0,
    })
    active_agents: int = 0
    active_regressions: int = 0
    active_simulations: int = 0


class ResourceScheduler:
    """资源调度器 — 管理 Agent/回归/仿真并发，避免资源抢占"""

    def __init__(self):
        self._pool = ResourcePool()
        self._queue: list[dict] = []       # 等待队列
        self._locks: dict[str, asyncio.Lock] = {}
        self._semaphore = asyncio.Semaphore(self._pool.max_agents)

    def configure(self, max_agents: int = None, max_regressions: int = None,
                  licenses: dict = None):
        """动态配置资源池"""
        if max_agents is not None:
            self._pool.max_agents = max_agents
            self._semaphore = asyncio.Semaphore(max_agents)
        if max_regressions is not None:
            self._pool.max_regressions = max_regressions
        if licenses:
            self._pool.available_licenses.update(licenses)

    async def acquire_agent(self, agent_role: str) -> bool:
        """获取 agent 执行槽位"""
        if self._pool.active_agents >= self._pool.max_agents:
            self._queue.append({
                "type": "agent", "role": agent_role,
                "queued_at": datetime.now().isoformat(),
            })
            return False

        await self._semaphore.acquire()
        self._pool.active_agents += 1
        return True

    def release_agent(self, agent_role: str):
        """释放 agent 槽位"""
        self._pool.active_agents = max(0, self._pool.active_agents - 1)
        self._semaphore.release()
        self._process_queue()

    async def acquire_license(self, tool: str) -> bool:
        """获取 EDA 工具 license"""
        if tool not in self._pool.available_licenses:
            return True  # 未管理的工具不受限

        if self._pool.available_licenses[tool] <= 0:
            self._queue.append({
                "type": "license", "tool": tool,
                "queued_at": datetime.now().isoformat(),
            })
            return False

        lock_key = f"license_{tool}"
        if lock_key not in self._locks:
            self._locks[lock_key] = asyncio.Lock()

        async with self._locks[lock_key]:
            if self._pool.available_licenses[tool] > 0:
                self._pool.available_licenses[tool] -= 1
                return True
        return False

    def release_license(self, tool: str):
        """释放 license"""
        if tool in self._pool.available_licenses:
            self._pool.available_licenses[tool] += 1
        self._process_queue()

    def _process_queue(self):
        """处理等待队列"""
        # 简化：队列中的任务需要外部重新提交
        pass

    def get_status(self) -> dict:
        """获取资源池状态"""
        return {
            "pool": {
                "max_agents": self._pool.max_agents,
                "active_agents": self._pool.active_agents,
                "active_regressions": self._pool.active_regressions,
                "active_simulations": self._pool.active_simulations,
                "utilization_pct": round(
                    self._pool.active_agents / max(self._pool.max_agents, 1) * 100, 1),
            },
            "licenses": dict(self._pool.available_licenses),
            "queue_size": len(self._queue),
            "queue": self._queue[:10],
        }


# ═══════════════════════════════════════════════════════════
# 任务依赖图
# ═══════════════════════════════════════════════════════════

@dataclass
class TaskNode:
    """依赖图中的任务节点"""
    role: str
    display_name: str = ""
    consumes: list = field(default_factory=list)
    produces: str = ""
    dependencies: list = field(default_factory=list)     # 依赖的 role 列表
    dependents: list = field(default_factory=list)       # 被哪些 role 依赖
    status: str = "pending"


class DependencyGraph:
    """任务依赖图引擎"""

    # Agent 依赖关系（基于 consumes/produces 推断）
    AGENT_GRAPH = {
        "spec_and_test_planner": {"produces": "vplan", "consumes": ["spec"], "deps": []},
        "design_architect": {"produces": "design_arch", "consumes": ["spec"], "deps": ["spec_and_test_planner"]},
        "verification_architect": {"produces": "verify_arch", "consumes": ["design_arch", "vplan"], "deps": ["design_architect"]},
        "model_agent": {"produces": "cmodel", "consumes": ["spec", "design_arch"], "deps": ["design_architect"]},
        "test_engineer": {"produces": "tests", "consumes": ["vplan", "verify_arch"], "deps": ["verification_architect"]},
        "assertion_engineer": {"produces": "assertions", "consumes": ["design_arch", "spec"], "deps": ["design_architect"]},
        "coverage_manager": {"produces": "coverage", "consumes": ["tests", "regression"], "deps": ["test_engineer", "regression_manager"]},
        "regression_manager": {"produces": "regression", "consumes": ["tests", "env"], "deps": ["test_engineer"]},
        "debug_engineer": {"produces": "debug_report", "consumes": ["regression", "tests"], "deps": ["regression_manager"]},
        "quality_assurance": {"produces": "qa_report", "consumes": ["coverage", "regression", "debug_report"], "deps": ["coverage_manager", "regression_manager"]},
        "report_generator": {"produces": "final_report", "consumes": ["qa_report", "coverage", "regression"], "deps": ["quality_assurance"]},
    }

    def build_graph(self, workflow: str = "full_verification") -> dict:
        """构建依赖图数据结构（供前端渲染）"""
        nodes = []
        edges = []

        for role, info in self.AGENT_GRAPH.items():
            nodes.append({
                "id": role,
                "label": role.replace("_", " ").title(),
                "produces": info["produces"],
                "consumes": info["consumes"],
                "deps_count": len(info["deps"]),
            })
            for dep in info["deps"]:
                edges.append({
                    "from": dep,
                    "to": role,
                    "label": "",
                })

        # 拓扑排序层级
        levels = self._topo_sort()

        return {
            "workflow": workflow,
            "nodes": nodes,
            "edges": edges,
            "total_nodes": len(nodes),
            "total_edges": len(edges),
            "levels": levels,
            "critical_path": self._find_critical_path(),
        }

    def _topo_sort(self) -> list[list[str]]:
        """拓扑排序，返回分层结构"""
        in_degree = defaultdict(int)
        for role, info in self.AGENT_GRAPH.items():
            for dep in info["deps"]:
                in_degree[role] += 1
            in_degree.setdefault(role, 0)

        levels = []
        processed = set()

        while len(processed) < len(self.AGENT_GRAPH):
            current = [r for r in self.AGENT_GRAPH
                       if r not in processed and in_degree[r] == 0]
            if not current:
                break
            levels.append(current)
            for r in current:
                processed.add(r)
                # 减少依赖此节点的节点入度
                for other, info in self.AGENT_GRAPH.items():
                    if r in info["deps"]:
                        in_degree[other] -= 1

        return levels

    def _find_critical_path(self) -> list[str]:
        """找关键路径（最长依赖链）"""
        levels = self._topo_sort()
        if not levels:
            return []
        # 简化：取每层第一个节点串联
        return [level[0] for level in levels]

    def get_agent_deps(self, role: str) -> dict:
        """获取单个 agent 的上下游依赖"""
        info = self.AGENT_GRAPH.get(role, {})
        return {
            "role": role,
            "produces": info.get("produces", ""),
            "consumes": info.get("consumes", []),
            "upstream": info.get("deps", []),
            "downstream": [
                r for r, i in self.AGENT_GRAPH.items()
                if role in i.get("deps", [])
            ],
        }

    def check_runnable(self, role: str, completed: list[str]) -> bool:
        """检查某个 agent 是否可以执行（依赖是否满足）"""
        info = self.AGENT_GRAPH.get(role, {})
        deps = info.get("deps", [])
        return all(d in completed for d in deps)


# ── 全局 ──
_scheduler: Optional[ResourceScheduler] = None
_dep_graph: Optional[DependencyGraph] = None

def get_scheduler() -> ResourceScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = ResourceScheduler()
    return _scheduler

def get_dep_graph() -> DependencyGraph:
    global _dep_graph
    if _dep_graph is None:
        _dep_graph = DependencyGraph()
    return _dep_graph
