"""9 个领域专家（目录名 = GUI 模式 id）。

    agentic_chat / mental_model / formal / uvm / rtl_designer /
    unit_testing / functional_coverage / debug / workflows

每个目录都有 `chat.py`（统一对话入口）；独立专家另有 `main.py`/`graph.py`。
目录唯一，不再保留 `design` / `coverage` / `verify` / `mental` / `unit_test`
别名副本；旧路径已随本次重构删除，import 请用上面的目录名。
"""
