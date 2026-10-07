"""阶段表 —— 闭环图 23 个节点的**唯一**元数据来源。

为什么要有这个文件
    节点名在此之前只是 `graph.py` 里的字面量：`n_ops` 里 append 一句
    `{"name": f"ops_r{n}"}`，`n_coverage` 里再 append 一句。于是：

      · 没有人能回答「一共有几个阶段、分几组、谁属于谁」；
      · 界面要给阶段配一个中文名，只能自己再写一张表（第三份真相）；
      · 运行日志里只有 `"ops"` 这种 id，人读起来要靠猜。

    这个文件把「节点 → 显示名 / 分组 / 归属 agent / 写哪些状态字段」显式成一张表。
    **它不含任何逻辑**：谁读它谁负责渲染。

与另外两张表的关系（不要在这里重复定义）
    · `state.py:PHASE_OWNERS`  —— 状态字段 → 写的节点。**它是权威**，
      本模块的 `outputs` 字段在 import 时由它推导，不另写一份。
    · `graph.py:NODE_NAMES`    —— 图的节点名清单。**它是权威**，
      `tests/test_stages.py` 断言两张表一一对应（本模块刻意不 import graph，
      否则为了一个元数据表要把 langgraph / 决策引擎全拖进来）。

  「加一个节点」的正确做法因此是三处：graph.py 加节点 → NODE_NAMES 加名字 →
  这里加一行元数据。测试会钉住第三处有没有忘。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from src.layers.l2_orchestration.state import PHASE_OWNERS


# ═══════════════════════════════════════════════════════════════
# 分组
# ═══════════════════════════════════════════════════════════════

#: 分组 id → 中文标题。顺序即界面上的显示顺序（dict 保序）。
STAGE_GROUPS: Dict[str, str] = {
    "control": "流程控制",
    "design": "设计与建模",
    "verify": "验证构建",
    "exec": "编译与仿真",
    "analysis": "覆盖率与调试",
    "converge": "决策与收敛",
    "signoff": "审查与签核",
}


# ═══════════════════════════════════════════════════════════════
# 阶段
# ═══════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class StageSpec:
    """一个图节点的显示元数据。

    字段刻意只有"给人看的"和"给界面用的"，不含控制流信息 —— 前驱后继属于
    `graph.py` 的边，不在这里。把拓扑写进来就是第二份真相。
    """

    id: str                      # 与 graph.py 的节点名一一对应
    title: str                   # 中文显示名
    group: str                   # STAGE_GROUPS 的键
    agent: str = ""              # 归属的 agent role（""=框架/控制节点）
    round_scoped: bool = False   # 是否每轮都会重跑（界面上按轮分组时用）
    summary_key: str = ""        # 从状态增量里取哪一行做摘要（界面上的一行说明）

    @property
    def group_title(self) -> str:
        return STAGE_GROUPS.get(self.group, self.group)


#: 按概念顺序排列（与 graph.py 的拓扑一致，不是按字母）。
STAGES: Tuple[StageSpec, ...] = (
    StageSpec("init", "初始化", "control"),
    StageSpec("front", "前置分析", "design", agent="front", summary_key="spec"),
    StageSpec("design", "规格与设计", "design", agent="design",
              summary_key="design_arch"),
    StageSpec("model", "参考模型", "design", agent="model", summary_key="model"),
    StageSpec("verify", "验证计划与 UVM", "verify", agent="verify",
              summary_key="tests"),
    StageSpec("env_arch_check", "环境架构自检", "verify", agent="verify"),
    StageSpec("round_bump", "轮次推进", "control", round_scoped=True),

    StageSpec("ops", "编译与仿真回归", "exec", agent="ops", round_scoped=True,
              summary_key="regression"),
    StageSpec("coverage", "覆盖率收集", "analysis", agent="coverage",
              round_scoped=True, summary_key="functional_coverage"),
    StageSpec("debug_functional", "功能失败调试", "analysis", agent="debug",
              round_scoped=True, summary_key="debug"),

    StageSpec("decide", "决策", "converge", agent="coverage", round_scoped=True,
              summary_key="last_action"),
    StageSpec("governor", "治理门控", "converge", round_scoped=True,
              summary_key="governance_outcome"),
    StageSpec("governor_retry", "治理重试", "converge", round_scoped=True),
    StageSpec("approval", "人工审批", "converge", round_scoped=True,
              summary_key="approval_outcome"),
    StageSpec("record_decision", "决策记账", "converge", round_scoped=True,
              summary_key="pending_action"),
    StageSpec("apply_converge", "执行收敛", "converge", round_scoped=True),
    StageSpec("apply_compile_retry", "编译重试", "converge", round_scoped=True),
    StageSpec("refactor_rtl", "RTL 重构", "converge", round_scoped=True,
              summary_key="guardian_verdict"),
    StageSpec("apply_update_model", "更新参考模型", "converge", round_scoped=True),
    StageSpec("apply_directed_test", "生成定向测试", "converge", round_scoped=True),
    StageSpec("apply_relax", "放宽约束", "converge", round_scoped=True),
    StageSpec("apply_expand_seeds", "扩大随机种子", "converge", round_scoped=True),

    StageSpec("audit", "质量审查", "signoff", agent="audit", summary_key="audit"),
    StageSpec("finalize", "签核与证据", "signoff"),
)

_BY_ID: Dict[str, StageSpec] = {s.id: s for s in STAGES}


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════

def get(stage_id: str) -> Optional[StageSpec]:
    """按节点名取元数据；未知节点返回 None（调用方自己决定怎么显示）。"""
    return _BY_ID.get(stage_id)


def title_of(stage_id: str) -> str:
    """节点名 → 中文显示名。未知节点原样返回 —— 宁可在界面上看到一个 id，
    也不要因为没登记就显示成空字符串（那才是真的查不出问题）。"""
    spec = _BY_ID.get(stage_id)
    return spec.title if spec else stage_id


def agent_of(stage_id: str) -> str:
    spec = _BY_ID.get(stage_id)
    return spec.agent if spec else ""


def group_of(stage_id: str) -> str:
    spec = _BY_ID.get(stage_id)
    return spec.group if spec else ""


def is_round_scoped(stage_id: str) -> bool:
    spec = _BY_ID.get(stage_id)
    return bool(spec and spec.round_scoped)


def outputs_of(stage_id: str) -> List[str]:
    """该阶段会写哪些 PipelineState 字段（由 PHASE_OWNERS 反查得到）。

    反查看起来绕，但这是刻意的：**归属只有一份**。若在这里另写一份字段清单，
    加字段时必然漏一处，而漏掉的那处正是"没人知道谁写的"。
    """
    return sorted(f for f, node in PHASE_OWNERS.items()
                  if _owner_matches(node, stage_id))


def _owner_matches(owner: str, stage_id: str) -> bool:
    """PHASE_OWNERS 里的属主名与节点名对齐。

    历史上属主名带轮次后缀（`ops_r` / `coverage_r`），因为原命令式实现里它们是
    「每轮调用的函数名」。图化之后节点叫 `ops` / `coverage`，所以这里做一次
    规范化比对 —— 与其去改 state.py 的注册表（那会牵动 387 个测试），
    不如在读取侧归一。
    """
    return owner.rstrip("_r") == stage_id or owner == stage_id


def grouped() -> List[Tuple[str, str, List[StageSpec]]]:
    """按分组返回 [(group_id, group_title, stages), ...]，供界面建树。

    组内保持 STAGES 的声明顺序；空组不出现在结果里。
    """
    out: List[Tuple[str, str, List[StageSpec]]] = []
    for gid, gtitle in STAGE_GROUPS.items():
        members = [s for s in STAGES if s.group == gid]
        if members:
            out.append((gid, gtitle, members))
    return out


def all_ids() -> Tuple[str, ...]:
    return tuple(s.id for s in STAGES)
