"""业务模块 —— 按业务线分目录，目录名与 `config/workbench.yaml` 的 `groups[].id` 一致。

    纵向 · 七条 agent 线（每条 = 一个领域角色的能力在界面上的表达）
    design/    设计构建     规格分析 → IP 拆解 → RTL 生成
    model/     参考模型     多语言参考模型 + 版本回滚
    verify/    验证构建     UVM 环境 / 测试用例 / SVA 断言
    ops/       编译与回归   编译 + 仿真 + 回归
    coverage/  覆盖率       功能覆盖点 + 收集 + gap 归因
    debug/     调试技术     日志、错误指纹、波形、失败用例二分
    audit/     签核审查     四道门禁 + 签核报告

    横向 · 一条流程与证据线（横切全部 agent）
    flow/      流程与证据   闭环编排、运行历史、证据链、签核判定、跟踪、趋势

> 为什么是"七条 agent 线 + 一条横切线"，见
> `docs/design/agent_gui_business_architecture.md`：agent 是纵向能力，而证据/治理/
> 记忆/进化是横切的 —— 只按 agent 分，横切能力无边可挂。

**本目录不集中注册模块**：谁上界面由清单说了算（`factory` 指向哪个类就加载
哪个类），这里不做 `__all__` 列举。加一个模块 = 写一个类 + 在清单里加一条，
不用改这个文件。

**模块之间不互相 import**（那会让插件化名存实亡）：跨模块共享的纯函数/小部件
放在**非模块**位置 —— 线内共享放该线的 `run_common.py`，跨线共享放
`modules/agent_output.py` 这类平台级文件。
"""
