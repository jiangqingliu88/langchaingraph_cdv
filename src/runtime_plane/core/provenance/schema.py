"""Provenance DAG 的词汇契约 —— 节点/边类型只在这里定义一次。

新增边类型不改已有返回键（与 `knowledge/schema.py` 的 `QUERY_CONTRACT` 同一条
纪律）；改已有语义才升 `SCHEMA` 版本。
"""
from __future__ import annotations
from src.runtime_plane.core.contracts import versions

SCHEMA = versions.PROVENANCE

#: 节点种类。新增种类时同步 `graph.py` 的建边逻辑与文档。
NODE_KINDS = (
    "artifact",      # spec / RTL / TP IR / StimulusPlan / ucdb / report / evidence
    "tp",            # 测试点（tp_id 主键）
    "test",          # UVM test（round_manifest 的 test_name）
    "bin",           # 覆盖率 bin（coverpoint.bin）
    "seed",          # 随机种子
    "job",           # 一次 EDA 进程（未来由 JobSupervisor 落盘）
    "decision_obj",  # 一次决策及其期望/实际效果
)

#: 边类型。`hit_by` 是**精确**归因；`attributed_by` 是**弱**归因 —— 两者
#: 不能混用，读者据此决定能不能把覆盖率功劳记到某条 test 上。
EDGE_TYPES = (
    "derived_from",   # artifact → artifact：后者由前者确定性派生
    "produced_by",    # artifact → agent/producer（attrs 里存 producer）
    "realizes",       # test → tp：这条 test 实现了该测试点
    "aggregates",     # tp → bin：测试点声明的覆盖 bin
    "hit_by",         # bin → test：per-test 覆盖率证明确实是它命中的（exact）
    "attributed_by",  # bin → test：只有合并 ucdb，按计划映射（weak）
    "seed_derived",   # test → seed：从 test 目录名 `_seed_<n>` 得到
    "executed_by",    # test → job：这一条 test 由哪个 EDA 进程执行
    "executed_with",  # test → stimulus_plan：这条 test 用的是哪份计划
    "executed_against",  # test → rtl_snapshot：这条 test 跑的是哪版 RTL
    "verifies",       # evidence/quality → run
    "evaluated",      # decision_obj → 效果事实
)


def tp_node_id(tp_id: str) -> str:
    return f"tp:{tp_id}"


def test_node_id(test_name: str) -> str:
    return f"test:{test_name}"


def bin_node_id(coverpoint: str, bin_name: str = "") -> str:
    name = ".".join(x for x in (coverpoint, bin_name) if x) or "unknown"
    return f"bin:{name}"


def seed_node_id(seed: int | str) -> str:
    return f"seed:{seed}"
