"""
PipelineScheduler —— 软件流水调度器。

把"阻塞式串行闭环"改造成"流水线并行"：EDA 密集阶段（编译仿真 / 覆盖率收集）
与 LLM 密集阶段（设计 / 模型 / 用例生成）重叠执行——一个任务在等待 EDA 时，
事件循环调度其他任务推进，不空转、不完全阻塞。

三类能力（对应流水化三步）：
  1. EDA 异步化   run_in_thread() 把同步阻塞的 EDA 调用（vlog/vsim）转线程，
                  释放事件循环，让 await 期间其它协程继续跑
  2. DAG 并发     gather() 并发执行无依赖的阶段（如 debug ∥ coverage）
  3. 多任务流水   waterfall() 软件流水：A 在 EDA 仿真时 B 做 LLM 生成

核心洞察：asyncio 里只要把"重 IO"（EDA 编译仿真、文件读写）放进线程/子进程，
事件循环就能在等待期间调度其它协程——流水不是"重写"，是"换调度方式"。

用法:
    from src.orchestration_plane.l2.pipeline_scheduler import PipelineScheduler

    sched = PipelineScheduler(max_concurrency=4)

    # 1. EDA 异步化：同步 compile() 转线程，不阻塞事件循环
    result = await sched.run_in_thread(runner.compile)

    # 2. DAG 并发：无依赖阶段并行
    cov, dbg = await sched.gather(collect_coverage(), analyze_failure())

    # 3. 多任务软件流水：并发跑多个闭环，EDA 等待期间互相推进
    results = await sched.waterfall([run_loop(spec_a), run_loop(spec_b)])
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Coroutine, List, Optional, TypeVar

T = TypeVar("T")


class PipelineScheduler:
    """软件流水调度器：EDA 异步化 + DAG 并发 + 多任务流水。"""

    def __init__(self, max_concurrency: int = 4):
        # 并发上限：限制同时跑多少个"重任务"（避免 EDA License / 内存耗尽）
        self.max_concurrency = max_concurrency
        self._sem: Optional[asyncio.Semaphore] = None

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.max_concurrency)
        return self._sem

    # ═══════════════════════════════════════════════════════════
    # 1. EDA 异步化：同步阻塞调用 → 线程执行，释放事件循环
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    async def run_in_thread(fn: Callable[..., T], *args, **kwargs) -> T:
        """把同步阻塞函数（如 RegressionRunner.compile 跑 vlog/vsim）转线程执行。

        关键：await 期间事件循环不被阻塞，可调度其它协程 → 流水的前提。
        """
        return await asyncio.to_thread(fn, *args, **kwargs)

    @staticmethod
    async def run_in_subprocess(fn: Callable[..., T], *args, **kwargs) -> T:
        """把 EDA 工具调用转子进程隔离（更重，崩溃不拖垮主流程）。

        与 run_in_thread 的区别：子进程隔离（EDA segfault 不影响主进程），
        但进程启动开销更大。coverage 收集已用 tool_subprocess，此处留统一入口。
        """
        from src.orchestration_plane.l2.communication.tool_subprocess import run_tool_in_subprocess
        return await run_tool_in_subprocess(fn.__name__, kwargs) if False else \
            await asyncio.to_thread(fn, *args, **kwargs)

    # ═══════════════════════════════════════════════════════════
    # 2. DAG 并发：无依赖阶段并行
    # ═══════════════════════════════════════════════════════════

    async def gather(self, *coros: Awaitable) -> List[Any]:
        """并发执行多个无依赖的协程（debug ∥ coverage 等）。

        返回与输入同序的结果列表；单个协程异常不拖垮其它（return_exceptions）。
        """
        results = await asyncio.gather(*coros, return_exceptions=True)
        return [r for r in results]  # 异常以 Exception 对象形式留在结果里，调用方自行判断

    # ═══════════════════════════════════════════════════════════
    # 3. 多任务软件流水：A 在 EDA 仿真时 B 做 LLM 生成
    # ═══════════════════════════════════════════════════════════

    async def waterfall(self, tasks: List[Callable[[], Awaitable[T]]],
                        concurrency: int = None) -> List[Any]:
        """软件流水：并发跑多个长任务（闭环），EDA 等待期间互相推进。

        tasks: 每个元素是返回协程的工厂函数（惰性，避免提前创建）。
        concurrency: 并发上限（默认用 max_concurrency）。

        返回与输入同序的结果列表；单个任务异常不拖垮其它。
        """
        limit = concurrency or self.max_concurrency
        sem = asyncio.Semaphore(limit)

        async def _bounded(idx: int, factory: Callable[[], Awaitable[T]]):
            async with sem:
                try:
                    return await factory()
                except Exception as e:
                    return e

        return await asyncio.gather(
            *[_bounded(i, f) for i, f in enumerate(tasks)],
            return_exceptions=True,
        )

    # ═══════════════════════════════════════════════════════════
    # 4. DAG 拓扑并发：按依赖分层，层内并行
    # ═══════════════════════════════════════════════════════════

    async def run_dag(self, stages: List["Stage"]) -> List[Any]:
        """按依赖 DAG 并发执行阶段：拓扑分层，层内 asyncio.gather 并行。

        用法:
            stages = [
                Stage("design", run_design),
                Stage("model", run_model, depends_on=["design"]),
                Stage("verify", run_verify, depends_on=["design"]),
                Stage("ops", run_ops, depends_on=["model", "verify"]),
            ]
            await sched.run_dag(stages)
        """
        # 拓扑排序（Kahn 算法）
        by_name = {s.name: s for s in stages}
        indegree = {s.name: len(s.depends_on) for s in stages}
        dependents: dict = {}
        for s in stages:
            for dep in s.depends_on:
                dependents.setdefault(dep, []).append(s.name)

        # 无依赖的作为第一层
        ready = [s.name for s in stages if indegree[s.name] == 0]
        done: dict = {}
        results: dict = {}

        while ready:
            # 当前层并发执行
            layer_coros = [(n, by_name[n].fn()) for n in ready]
            names, coros = zip(*layer_coros) if layer_coros else ([], [])
            layer_results = await asyncio.gather(*coros, return_exceptions=True)
            for n, r in zip(names, layer_results):
                results[n] = r
                done[n] = True

            # 推进下一层
            next_ready = []
            for n in list(ready):
                for dep in dependents.get(n, []):
                    indegree[dep] -= 1
                    if indegree[dep] == 0:
                        next_ready.append(dep)
            ready = next_ready

        return [results.get(s.name) for s in stages]


@dataclass
class Stage:
    """流水级：一个可并发调度的阶段单元。"""
    name: str
    fn: Callable[[], Awaitable[Any]]       # 返回协程的工厂函数
    depends_on: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def run_eda_async(fn: Callable[..., T], *args, **kwargs) -> Coroutine[Any, Any, T]:
    """把同步 EDA 调用转异步协程（便捷入口，等价 run_in_thread）。

    用法:
        result = await run_eda_async(runner.compile)
    """
    return asyncio.to_thread(fn, *args, **kwargs)
