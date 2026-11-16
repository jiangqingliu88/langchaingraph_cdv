# ChipStack 风格产物工作区

> 目录架构已统一到 `CS-DIR-REQ-001` 的 L0–L5 五层模型，权威实现与 CLI/GUI
> 入口见 [CHIPSTACK_PROJECT_LAYOUT.md](CHIPSTACK_PROJECT_LAYOUT.md)。本文保留
> interface-timing 产物投影的细节；该投影现在复用同一套目录/manifest/日志契约。

## 1. 这次调整的是什么

按你给出的目录理念，本次调整的是**运行产物组织**，不是重排源码、增加 Agent 类型或增加架构平面。现有 IR / Engine / Generation / Runtime / Orchestration 的职责与验证语义保留。

实现分两层：

- **原执行链和原始产物**：保持不变，存放在 `Archive/<run_id>/`；
- **项目 AI 工作区视图**：将同源产物映射到 `<top_design_name>/mental_model_agent/`、`uvm_agent/`、`simulation_agent/` 等目录，按工程角色查找与复盘。

**这不是对 Cadence 数据库、ChipStack 服务、Verisium、SuperLint 或 JasperGold 的接入。** SQLite 是本工作区自己的索引，不覆盖既有 lineage/config 数据库。没有真实执行的工具，只写真实状态，不补造报告、波形、PPA 数值或 formal proof。

## 2. 实际工作树

本次真实执行产生的示范工作区在 [chipstack_demo](../../review_bundle/chipstack_demo)：

```text
review_bundle/chipstack_demo/
├── artifacts.sqlite                   # 专用运行与文件哈希索引
├── run_manifest.json                  # 最新项目/本次运行和归档指针
├── Archive/
│   └── run-<time_ns>/
│       ├── manifest.json              # 原始证据与完整元数据
│       ├── source/                    # 源 Spec 快照
│       ├── contract/                  # Temporal IR、Binding、Specification 报告
│       ├── monitors/                  # Monitor 源文件
│       ├── rtl/                       # 合规/故意违例 RTL 对照快照
│       └── runs/                      # 按场景归档的运行结果、日志和可用波形
│
├── axi_stream/                        # <top_design_name>
│   ├── mental_model_agent/
│   │   ├── mental_model.md            # 可读、有限共享理解，附 Binding/Spec 状态
│   │   ├── temporal_ir.json
│   │   ├── binding_report.json
│   │   ├── specification_readiness.json
│   │   ├── traceability.json
│   │   ├── provenance.jsonl
│   │   └── provenance_summary.json
│   ├── rtl_generation/
│   │   ├── reference_inputs/          # 参考 RTL 快照，没有冒充 AI 改写 RTL
│   │   └── status.json
│   ├── uvm_agent/
│   │   ├── monitors/                  # 已生成、但本机尚未编译的 checker
│   │   └── monitor_manifest.json
│   ├── simulation_agent/
│   │   ├── positive/                  # runtime.json + execution_manifest.json
│   │   └── negative_control/          # 明示故意违例的负对照
│   ├── functional_coverage_agent/
│   │   └── coverage.json              # 只描述声明场景，不虚报功能覆盖率
│   ├── coverage_closure_agent/
│   │   └── status.json                # 缺运行时证据时为 INCOMPLETE
│   ├── dv_debug/
│   │   └── findings.json              # 确定性错误/状态汇总，而非 LLM 根因断言
│   ├── formal_agent/status.json        # NOT_RUN
│   ├── rtl_early_estimation_agent/status.json  # NOT_RUN
│   ├── lint_autofix/status.json        # NOT_RUN
│   └── compile_n_fix/status.json        # NOT_RUN
│
├── .symphony_logs/<run_id>.jsonl
├── .cli_logs/<run_id>.json
└── tui/sessions/<run_id>.json         # structured authoring 时 records=[]
```

每个任务实例的 `run_id` 都是新的，所以新的证据不会覆盖旧的波形或配置。历史查询按 ID 保留；`run_manifest.json` 的 latest 指针随当前写入项目更新。

“按时间戳保存”和“逻辑上不可变归档”是工作区约定，**不是密码学不可篡改的承诺，也不是操作系统的写保护**。`artifact_files.sha256` 用来对照实际文件；完整 Evidence v2 的包签核与跨 Run 失效传播仍是另一阶段。

## 3. 系统级与项目级如何关联

### 系统级

[run_manifest.json](../../review_bundle/chipstack_demo/run_manifest.json) 记录：

- `latest_design`、`latest_run_id`；
- 每个设计的 `latest_run_id`；
- 每个设计对应的 `Archive/<run_id>/manifest.json`；
- `overall_status` 和 `simulation_kind`；
- `artifacts.sqlite` 的用途。

[artifacts.sqlite](../../review_bundle/chipstack_demo/artifacts.sqlite) 中只有真正的索引表：

- `runs`：设计名、run_id、seed、overall/binding/specification status、仿真类别、manifest 路径与 SHA-256、记录时间；
- `artifact_files`：原始归档文件路径、SHA-256、字节数，并关联到对应 run。

它不保存虚构的“Agent 已完成”状态，也不接管既有产品数据库。

### 项目级

| 目录 | 目前真正保存的内容 | 不包含什么 |
|---|---|---|
| `mental_model_agent/` | Temporal IR、来源、绑定协议、规格生命周期和可读共享理解 | 整颗芯片已被 LLM 完整理解的断言 |
| `rtl_generation/` | 合规与故意故障的源 RTL 快照 | 自动设计生成、ECO、未发生的修改 |
| `uvm_agent/` | 从结构化时序义务生成的 monitor 与生成引用 | 已完成的 UVM 验证平台、完整编译结果 |
| `simulation_agent/` | 每个场景的期望状态、实际状态、后端类别及可用的日志/波形 | 本机不存在的真实仿真通过证据 |
| `functional_coverage_agent/` | 正、反样例的覆盖场景与可用计数 | 全部功能覆盖率、无依据的百分比 |
| `coverage_closure_agent/` | 未证明义务和闭合状态 | 已 100% 闭合或正式签核 |
| `dv_debug/` | 实际绑定错误、缺失工具、未满足场景 | LLM 推测的 Root Cause 或自动修复 |
| `formal_agent/` | `NOT_RUN` 状态和原因 | JasperGold 任务、形式证明结果 |
| `rtl_early_estimation_agent/` | `NOT_RUN` 状态和原因 | 面积、功耗、性能估计 |
| `lint_autofix/` | `NOT_RUN` 状态和原因 | SuperLint 报告或自动整改代码 |
| `compile_n_fix/` | `NOT_RUN` 状态和原因 | 未被创建的编译修复结果 |

这保留了“工程上下文可以由下一任务读取”的能力，但只允许共享理解覆盖已知、已绑定的范围。不能把当前一条握手规则当整份芯片心智模型。

## 4. 接口与兼容性

### 默认项目工作区

```powershell
python -m src.workbench.cli.commands interface-timing run-slice --seed 4444
```

默认根目录为 `review_bundle/chipstack_artifacts`，demo design 目录由其 fixture 名 `axi_stream` 标识。也可以显式指定：

```powershell
python -m src.workbench.cli.commands interface-timing run-slice `
  --out review_bundle/chipstack_demo --top-design-name axi_stream --seed 4444 --allow-incomplete
```

`--allow-incomplete` 只放开查看出口码，不改变运行时的事实状态。

本次实际生成物包括：

- [项目共享理解](../../review_bundle/chipstack_demo/axi_stream/mental_model_agent/mental_model.md)；
- [绑定报告](../../review_bundle/chipstack_demo/axi_stream/mental_model_agent/binding_report.json)；
- [Specification Readiness](../../review_bundle/chipstack_demo/axi_stream/mental_model_agent/specification_readiness.json)；
- [生成的 Monitor](../../review_bundle/chipstack_demo/axi_stream/uvm_agent/monitors/monitor_r_valid_data_stable.sv)；
- [正向 Runtime 状态](../../review_bundle/chipstack_demo/axi_stream/simulation_agent/positive/runtime.json)；
- [负向 Runtime 状态](../../review_bundle/chipstack_demo/axi_stream/simulation_agent/negative_control/runtime.json)；
- [根归档 Manifest](../../review_bundle/chipstack_demo/Archive/run-1794629719187233900/manifest.json)。

其中 Source/Binding 和 Specification 均为 `VALIDATED`，本机仿真仍为 `INCOMPLETE`、`rtl_simulation_completed=false`。这两层不能互相替代。

### 查询运行历史

```powershell
python -m src.workbench.cli.commands interface-timing runs `
  --workspace review_bundle/chipstack_demo --design axi_stream --json
```

也可直接调用 `read_workspace_runs()` 取得按 `id` 升序的真实 SQL 记录。查询不启动仿真、不把历史状态提升为通过。

### 保留旧布局

```powershell
python -m src.workbench.cli.commands interface-timing run-slice `
  --out review_bundle/chipstack_legacy_probe --legacy-layout --allow-incomplete
```

此时保留 `<out>/run-<time_ns>/` 的旧平铺结构，不写新的项目工作区或 SQLite。先前的 `review_bundle/interface_timing/` 证据仍在，没有被删除。

## 5. 真实验证与目录状态边界

- 工作区投影不改变原验证逻辑：SourceAnchor、端口/时钟/复位绑定、原 Specification 编译、monitor 生成、后端执行及三态裁决继续使用原实现。
- 工作区索引不是“Agent 说已完成”的自述表。它来自这些实际产生的文件、状态和哈希。
- `NOT_RUN`、`INCOMPLETE`、`VALIDATED`、`test_double`、`unavailable` 是不同事实，不能混用。
- 新查询统计不解决 EDA 缺失。当前验证包没有模拟执行出来的 VCD，也没有验证 formal/lint/PPA/compile-fix 自主恢复能力。
- 此次实现没有迁移或合并 Cadence SQLite schema，也没有启动 ChipStack 服务。
- Workbench、TUI、日志及未来 Agent 应从同一份 manifest/IR/绑定记录复用上下文，不能各自复制一份互相漂移的“理解”。

## 6. 验收证据

- 新增 [工作区测试](../../tests/test_chipstack_workspace.py)：目录、SQLite、跨运行记录、legacy 兼容和路径逃逸防护。
- 与 [接口时序测试](../../tests/test_interface_timing_slice.py) 合计 **32 项定向测试通过**。
- 工具板块与架构结构 Guard 在变更后继续检查，不放宽允许依赖、平面归属或 Hash 证据标准。
- 最终全量 `tests/`：**1343 passed、16 skipped，`PYTEST_EXIT=0`**（其中包含上述工作区与接口用例）。
- Architecture Guard：**OK**。

下一项应该先让真实仿真环境跑通同一个 AXI-Stream 样例，并把生成的波形、编译日志和结果接入这份现有索引；而不是把尚未执行的目录继续命名成“自主设计、形式证明、覆盖率完全闭合或自动修复完成”。
