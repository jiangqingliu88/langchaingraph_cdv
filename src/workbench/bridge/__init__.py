"""工具绑定 —— 清单里的名字 → `src/runtime_plane/tools/**` 里的函数。

叫 `bridge` 而不是 `tools`：仓库里已经有一个 `src/runtime_plane/tools/`，两个同名目录会
让 `from ...tools import ...` 看起来像指错了地方。

**本子包不 import Qt。** 「清单里这个名字绑到了哪个函数、它返回什么」应该
能在没有显示器、没有 QApplication 的地方回答 —— 这是它可测的前提。
"""
