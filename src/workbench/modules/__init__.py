"""业务模块 —— 按业务线分目录，目录名与 `config/workbench.yaml` 的 `groups[].id` 一致。

    按 Architecture 4.0 的 8 个职责平面组织（见 architecture/planes.py）：

    Generation Plane   design/ model/ verify/   RTL / 参考模型 / UVM / SVA
    Engine Plane       ops/ coverage/ debug/ audit/   确定性执行与裁决
    Evidence Plane     flow/                   运行历史、证据链、签核判定
    Interfaces Plane   project/ soc/ ip/ service/ ide/   项目与工程入口
    Runtime Plane      platform/               权限、环境、任务恢复
    Agent / Orchestration / IR / Knowledge / Experience 由 architecture/ 总览展示

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
