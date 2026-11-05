"""IP 规格 —— 编辑集成设计环境的 IP 声明 YAML，边写边校验。

**它是什么**：一份声明「一个 IP 长什么样」的 YAML 的编辑器 —— 接口有哪些端口
与协议、有哪些寄存器、干什么用、成熟到什么程度。左边写原文、下面列 schema
诊断、双击诊断跳到出事那一行。

**为什么需要它**：IP 的接口/寄存器是**设计知识**，环境生成（UVM 骨架）、参考
模型、寄存器模型都要跟它对齐。以前这些信息散在 spec 与生成的 YAML 里，改一处
不知道另一处会不会跟着错。把它显式成一份可编辑、可校验的规格，至少让「接口
到底长什么样」有一个地方说了算。

**它不是什么**：这份规格是**设计时**的声明，目前不被闭环消费（与
`manual_nodes.yaml` 同一性质）。字段刻意对齐既有的 IP 库
（`src/layers/l4_memory/ip_registry.py` 的 `ip_name` / `category` /
`function_desc` / `version`），免得同一个概念在仓库里长出两套字段名。

界面本体是 `modules/ide/decl_editor.py` 的共享件 —— 本文件只有下面几个类属性
是实质内容。
"""
from __future__ import annotations

from src.tools.integration.ide_tools.api import IP_SPEC
from src.workbench.modules.ide.decl_editor import DeclEditorModule


class IpSpecModule(DeclEditorModule):
    """IP 规格声明 YAML 的编辑器 + 校验器。"""

    DECL = IP_SPEC
    NOUN = "IP 规格"
    DEFAULT_FILENAME = "ip_spec.yaml"

    HINT = ("编辑 IP 规格的声明 YAML —— 保存时原样写回，注释与格式都保留。\n"
            "字段：name / category / function / tags / status / revision，"
            "接口 interface.protocols + ports[]，寄存器 registers[]。\n"
            "Ctrl+S 保存　Ctrl+O 打开。打字停下 0.5 秒自动校验；"
            "双击下面的诊断跳到对应行。\n"
            "⚠ 端口名要与 RTL 里的端口名一致 —— 不一致时接口绑定会静默错位。")
