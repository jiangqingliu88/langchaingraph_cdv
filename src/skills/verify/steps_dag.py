"""verify 内部 7 步的**数据依赖 DAG** —— 顺序是声明出来的，不是注释约定。

`VerifyExecutor.execute_task()` 里那 7 步的顺序极敏感：

    coverage_plan → find_spec_yaml → dut_channel → env_cov_bins
                 → constraint_yaml → association_report → jinja_render

错一步不会报错，只会**静默少东西**（实测：`find_spec_yaml` 会清空
`inputs/yaml/uvm/`，把 bins 写在它前面 = env_cov 静默退回自动分箱）。原实现
靠大段注释提醒，人一换就忘。

本模块把「谁依赖谁」写成数据，并在两个时点检查：

1. **import 期**（`validate_steps()`）：依赖缺失 / 成环 → 立即失败；
2. **执行期**（`StepRecorder.mark()`）：某步的前置没跑 → `StepOrderError`。

注意：DAG 只约束**前置关系**，不强制唯一线性顺序（无依赖的步骤可以互换）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


from src.core.runtime.errors import StepOrderError  # noqa: F401


@dataclass(frozen=True)
class Step:
    """一个生成步骤。

    `inputs` / `outputs` 是**相对 run 目录的路径或逻辑产物名**，用于文档与
    测试；`why` 记录这条依赖的真实原因（不是“惯例”）。
    """

    name: str
    deps: Tuple[str, ...] = ()
    inputs: Tuple[str, ...] = ()
    outputs: Tuple[str, ...] = ()
    why: str = ""


#: 顺序即声明的拓扑顺序（测试会校验它与拓扑排序一致）。
STEPS: Tuple[Step, ...] = (
    Step(
        "coverage_plan", outputs=("coverage/coverage_plan.yaml",),
        why="回归的 count / SEED 由它铺开；晚于 find_spec_yaml 则回归已生成完",
    ),
    Step(
        "find_spec_yaml", deps=("coverage_plan",),
        inputs=("spec.json",), outputs=("inputs/yaml/",),
        why="它会清空 inputs/yaml/uvm/*.yaml，一切要进渲染的文件必须晚于它",
    ),
    Step(
        "testpoints_prebuild", deps=("find_spec_yaml",),
        why="测试点 IR **只算不写**：tp_seen 位图与 timing 信号要进覆盖率接口，"
            "而接口在 jinja_render 之前落盘 —— 算晚了这一轮就少这两样",
    ),
    Step(
        "dut_channel", deps=("testpoints_prebuild",),
        outputs=("coverage/<dut_if>.sv",),
        why="生成 bind 进 DUT 的覆盖率接口；bins 与 env/tb_top 共用它的身份，"
            "位图来自上一步的 tp_payload",
    ),
    Step(
        "env_cov_bins", deps=("dut_channel",),
        outputs=("inputs/yaml/uvm/env_cov_bins.yaml",),
        why="必须在清空之后、渲染之前落盘，否则 env_cov 静默退回自动分箱",
    ),
    Step(
        "constraint_yaml", deps=("env_cov_bins",),
        outputs=("inputs/yaml/uvm/constraint.yaml", "coverage/constraint_status.json"),
        why="约束模型是 env/cons/* 的输入，同样只能落在清空之后、渲染之前",
    ),
    Step(
        "association_report", deps=("constraint_yaml",),
        outputs=("coverage/association_report.json",),
        why="关联报告要读已落盘的 constraint，晚于渲染就错过这一轮",
    ),
    Step(
        "jinja_render", deps=("association_report",),
        inputs=("inputs/yaml/",), outputs=("env/", "agents/", "bench/"),
        why="唯一读取全部 YAML 的渲染步；前面缺一份，产物就静默少一块",
    ),
)

_BY_NAME: Dict[str, Step] = {s.name: s for s in STEPS}


def validate_steps(steps: Sequence[Step] = STEPS) -> Tuple[str, ...]:
    """校验依赖完整性并返回拓扑序；坏声明立即抛 `StepOrderError`。

    - 重名 / 未知依赖 / 成环 → 失败；
    - 返回的拓扑序与**声明顺序**一致（本 DAG 是线性的，保留了唯一写入顺序）。
    """
    names = [s.name for s in steps]
    if len(names) != len(set(names)):
        dup = sorted({n for n in names if names.count(n) > 1})
        raise StepOrderError(f"步骤重名: {dup}")
    known = set(names)
    for step in steps:
        missing = [d for d in step.deps if d not in known]
        if missing:
            raise StepOrderError(
                f"步骤 {step.name!r} 依赖了不存在的步骤: {missing}")

    # Kahn 拓扑排序；同时检测环
    indegree = {s.name: 0 for s in steps}
    downstream: Dict[str, List[str]] = {s.name: [] for s in steps}
    for step in steps:
        for dep in step.deps:
            indegree[step.name] += 1
            downstream[dep].append(step.name)
    ready = [s.name for s in steps if indegree[s.name] == 0]
    order: List[str] = []
    while ready:
        cur = ready.pop(0)
        order.append(cur)
        for nxt in downstream[cur]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                ready.append(nxt)
    if len(order) != len(steps):
        cyclic = sorted(n for n in indegree if indegree[n] > 0)
        raise StepOrderError(f"步骤依赖成环: {cyclic}")
    return tuple(order)


#: import 期自检 —— 声明写坏时**启动即炸**，而不是跑一半才少产物。
STEP_NAMES: Tuple[str, ...] = validate_steps()


class StepRecorder:
    """执行期记录器：缺前置 → 立刻报错；最后可校验是否跑全。"""

    def __init__(self, steps: Sequence[Step] = STEPS) -> None:
        self._steps = tuple(steps)
        self._by_name = {s.name: s for s in self._steps}
        self._done: List[str] = []

    @property
    def done(self) -> Tuple[str, ...]:
        return tuple(self._done)

    def mark(self, name: str) -> None:
        step = self._by_name.get(name)
        if step is None:
            raise StepOrderError(f"未声明的步骤: {name!r}（允许: {list(self._by_name)}）")
        missing = [d for d in step.deps if d not in self._done]
        if missing:
            raise StepOrderError(
                f"步骤 {name!r} 的前置未执行: {missing}；当前已完成 {self._done}")
        if name not in self._done:
            self._done.append(name)

    def finish(self, require: Iterable[str] = None) -> Tuple[str, ...]:
        """确认本轮该跑的步骤一个不少。"""
        required = list(require if require is not None else self._by_name)
        missing = [n for n in required if n not in self._done]
        if missing:
            raise StepOrderError(f"以下步骤未执行: {missing}；已完成 {self._done}")
        return self.done

    def assert_matches_declared_order(self) -> None:
        """可选：要求实际执行顺序与声明的线性顺序完全一致。"""
        if list(self._done) != list(self._by_name):
            raise StepOrderError(
                f"实际顺序 {self._done} 与声明顺序 {list(self._by_name)} 不一致")
