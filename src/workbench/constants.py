"""工作台窗口级常量（避免 app / main_window 循环引用）。"""
APP_TITLE = "SignOffAI · 验证工作台"
CONSOLE_TITLE = "控制台"

#: 平台自带页签的 id。双下划线打头是刻意的 —— 它们不是清单里的模块，
#: 不能跟模块 id 撞车。主窗口拆分后放这里，layout / actions 共用。
CONSOLE_PIN = "__console__"
NAV_PIN = "__nav__"

#: 项目下拉里那条“就地登记”的哨兵值（不是项目 id）。
REGISTER_ACTION = "__register__"
