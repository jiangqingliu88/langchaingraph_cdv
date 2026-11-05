"""工作台测试。

文件名一律加 `test_workbench_` 前缀（或者用 `test_bridge` / `test_tasks`
这种不会撞车的名字）：仓库根的 `tests/` 里已经有 `test_manifest.py` 与
`test_registry.py`，测的是别的东西（证据链 manifest、Agent 注册中心）。
同名文件在两个没有 `__init__.py` 的目录里会让 pytest 报 import 冲突。
"""
