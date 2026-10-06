"""主题与外观资源 —— 配色（palette）与图标（icons）。

**这不是控件**：本包只提供"长什么样"的原料，任何控件都可以依赖它。

`theme` 原来是**一个模块**，调用点写的都是 `theme.current()` / `theme.MUTED` /
`theme._stylesheet()`。现在它是一个包，所以这里要把那套 API 原样再导出一次 ——
调用点一个字都不用改。
"""
from . import icons                                    # noqa: F401
from . import palette as _palette
from .palette import *                                 # noqa: F401,F403


def __getattr__(name: str):
    """包上的兜底查找 —— 转发到 palette **模块**。

    为什么不靠 `import *`：它**不导出下划线开头的名字**，而 `theme._stylesheet`
    这类私有名一直有人用（测试就靠它验 QSS）。转发到**模块**而不是模块里那个
    "当前配色视图"，一举覆盖两种：私有名（`_stylesheet`）与视图代理的字段
    （`MUTED` / `TEXT` / `GRID`）—— 后者由 palette 自己的 `__getattr__` 兜。
    """
    return getattr(_palette, name)
