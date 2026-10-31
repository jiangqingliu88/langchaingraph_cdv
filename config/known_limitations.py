"""已知边界（单一真相）—— `ARCHITECTURE.md` §15 必须与这里一致。

不是“TODO 列表”：每条都是**当前承诺的边界**。实现了就把 status 改成
`done` 并从文档移除，同时更新对应实现（例如 player runtime）。
`tests/test_architecture_invariants.py` 会把这份表和文档钉在一起。
"""
from __future__ import annotations

from typing import Dict, Tuple

KNOWN_LIMITATIONS: Tuple[Dict[str, str], ...] = (
    {"id": "unreachable_declaration", "status": "open",
     "text": "不可达声明未实现"},
    {"id": "verified_ref_model", "status": "open",
     "text": "没有 verified TLM 1.0 参考模型"},
    {"id": "single_backend_template", "status": "open",
     "text": "只有 Questa 后端模板完整"},
    {"id": "plusargs_source", "status": "open",
     "text": "测试语义 plusargs 还没有生成源"},
    {"id": "single_machine_regression", "status": "by_design",
     "text": "单机串行回归"},
    {"id": "no_web_ui", "status": "by_design",
     "text": "不开发 Web UI"},
    {"id": "coarse_reward", "status": "by_design",
     "text": "奖励信号是“粗连续”"},
    {"id": "kg_is_query_only", "status": "by_design",
     "text": "知识图是查询层，不是推理层"},
    {"id": "player_runtime", "status": "open",
     "text": "player 激励后端只有 plan，没有 runtime"},
    {"id": "provenance_sandbox_lifecycle", "status": "open",
     "text": "产物级 provenance DAG"},
    {"id": "cmd_allowlist_monitor", "status": "by_design",
     "text": "命令白名单默认 monitor"},
    {"id": "uvm_ir_migration", "status": "open",
     "text": "UVM 生成器尚未迁到统一 IR"},
    {"id": "incremental_dependency_map", "status": "open",
     "text": "增量回归依赖映射尚未自动生成"},
    {"id": "incremental_compile", "status": "open",
     "text": "增量编译尚未实现"},
    {"id": "optimize_seed_level", "status": "open",
     "text": "回归优化未做种子级调度"},
    {"id": "optional_auth_api", "status": "by_design",
     "text": "auth.py 是可选 API 面"},
)


def by_id(limitation_id: str) -> Dict[str, str]:
    for item in KNOWN_LIMITATIONS:
        if item["id"] == limitation_id:
            return item
    raise KeyError(limitation_id)
