"""验证工作台 —— YAML 驱动的 PySide6 桌面平台（Verdi 式多面板）。

一句话：**界面清单是 YAML，业务是插件。** 平台只认 `IModule` 接口与
`ModuleSpec`，不认识任何具体模块；想知道「有哪些界面」不用读代码，读
`config/workbench.yaml`。

三层：
    ui/          通用控件（主题、行表模型、表格助手、控制台、Dock 工厂）
    bridge/      工具绑定 —— 名字 → src/tools/** 的函数路径，惰性 import
    modules/     业务模块：调试技术 / 集成设计环境 / 验证管理系统

依赖只能从上往下：`ui ← bridge ← modules ← registry ← app`。
**本包的 `__init__` 与 `bridge/` 不 import Qt**，所以「清单解析」与
「工具调用」这两件事在没有显示器、没有 QApplication 的地方也能测。

入口：
    python -m src.workbench [清单.yaml] [--module ID] [--input 路径]
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "2.0.0"
