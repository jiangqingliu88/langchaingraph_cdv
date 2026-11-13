"""集成设计环境（ide）的工具层 —— 目前只有「人工节点」YAML 的校验。

本包**零 Qt 依赖**：把 `manual_nodes.yaml` 按 JSON Schema 校验成一张诊断清单，
界面（`src/workbench/modules/ide/manual_nodes/`）拿它显示问题。校验逻辑在工具层、
界面是只读视图 —— 与 `trend_tools` 同一条纪律。

**这份 YAML 目前不接闭环**：闭环图（`src/orchestration_plane/l2/graph.py`）的节点
是写死的，`build_closed_loop_graph()` 不读任何节点声明；设计文档
`docs/design/gui_pipeline_architecture.md` §8 也明确「不在 GUI 里编辑流程拓扑」。
所以这里的「人工节点」是**声明/规划**性质的：编辑它、校验它，等以后真有注入机制
再把这份声明喂给闭环。

    from src.runtime_plane.tools.integration.ide_tools import run_manual_nodes
    run_manual_nodes("config/ide/manual_nodes.yaml")
    # → {"valid": bool, "error_count": int, "issues": [...]}
"""
from .api import ENUM_VALUES, SCHEMA_PATH, SKELETON_KEYS, run_manual_nodes

__all__ = ["run_manual_nodes", "SCHEMA_PATH", "SKELETON_KEYS", "ENUM_VALUES"]
