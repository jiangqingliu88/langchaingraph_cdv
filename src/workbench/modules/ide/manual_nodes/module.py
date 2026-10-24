"""人工节点 —— 编辑流程人工节点的声明 YAML，边写边校验。

**它是什么**：一份声明「在闭环流程哪个阶段之后插一个人工干预点」的 YAML 的
编辑器。左边写原文、下面列 schema 诊断、双击诊断跳到出问题的那一行。

**它不是什么**：它**不改闭环流程**。闭环图（`src/layers/l2_orchestration/graph.py`）
的 23 个节点是写死的，`build_closed_loop_graph()` 不读任何节点声明；设计文档
`docs/design/gui_pipeline_architecture.md` §8 也明确「不在 GUI 里编辑流程拓扑」。
所以这份 YAML 是**声明/规划**性质的，本模块只负责「把它编辑对、校验过」，等以后
真有注入机制再由闭环去消费它。

**界面本体不在这里**：编辑器是 `modules/ide/decl_editor.py` 里的共享件
（IP 规格页用的是同一个）。本文件只有下面几个类属性是实质内容 ——
与「七条 agent 线的产出总览各自 15 行」是同一种写法。
"""
from __future__ import annotations

from src.tools.integration.ide_tools.api import MANUAL_NODES
from src.workbench.modules.ide.decl_editor import DeclEditorModule


class ManualNodesModule(DeclEditorModule):
    """人工节点声明 YAML 的编辑器 + 校验器。"""

    DECL = MANUAL_NODES
    NOUN = "人工节点"
    DEFAULT_FILENAME = "manual_nodes.yaml"

    HINT = ("编辑流程人工节点的声明 YAML —— 保存时原样写回，注释与格式都保留。\n"
            "Ctrl+S 保存　Ctrl+O 打开　Tab 插两个空格。打字停下 0.5 秒自动校验；"
            "双击下面的诊断跳到对应行。")
