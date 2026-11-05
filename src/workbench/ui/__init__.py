"""通用件 —— 与任何具体业务无关的 Qt 积木，**按组件类别分目录**。

    theme/        主题与外观资源          配色（palette）+ 图标（icons）
    models/       Qt 模型                 QAbstractItemModel 一族（不是视图）
    widgets/      通用控件               横幅、面板、控制台、占位画布
    views/        自绘视图               用 QPainter 画出来的那些件
    editors/      编辑器与高亮           QPlainTextEdit + QSyntaxHighlighter
    nav/          导航                   左窗格那棵树
    containers/   容器                   决定"东西摆在哪"（停靠 / 子窗口）
    helpers/      装配助手               不产控件，只收"怎么摆/怎么连"

**为什么这么分**：Qt 自己就是这么分的 —— 模型与视图分开、绘制归绘制、容器管位置。
按这个口径放文件，"这该写在哪"不用想；找东西也从"我记得有个 trend_chart.py"
变成"自绘的都在 views/"。每个类别包的 `__init__` 把成员再导出一次，所以
`from ..ui.models import RowsModel`、`theme.current()` 这类老写法照旧可用。

这里每个件都**不认识 case 模型、也不认识调试工具**：主题只管配色，行表模型只管
「表头 + 若干行」，控制台只管分级日志。领域相关的模型（case 属性表、组织树）
不在这里，它们归各自的业务模块。

**本文件刻意不 import 任何子模块**：那会连带拉 Qt，而这个包被 `app.py` 之前的
代码碰到时（例如只想拿 `helpers.tables` 的纯函数做单测）不该被迫建
QApplication。要用什么就 `from .ui import theme` / `from .ui.models import ...`。
"""
