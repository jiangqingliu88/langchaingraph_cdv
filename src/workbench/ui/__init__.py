"""通用控件 —— 与任何具体业务无关的 Qt 积木。

这里的每个模块都**不认识 case 模型、也不认识调试工具**：主题只管配色，
行表模型只管「表头 + 若干行」，控制台只管分级日志。领域相关的模型
（case 属性表、组织树）不在这里，它们归各自的业务模块。

刻意不在本文件里 import 任何子模块：`ui/theme.py`、`ui/models.py` 都要拉
Qt，而这个包被 `app.py` 之前的代码碰到时（例如只想拿 `table_helpers` 的
纯函数做单测）不该被迫建 QApplication。要用什么就 `from .ui import theme`。
"""
