# ChipStack 工程目录架构（CS-DIR-REQ-001）落地说明

本文说明 SignOffAI 如何把 ChipStack 2.0 的 **L0–L5 五层工程目录模型**落成一个
可执行契约。唯一实现是
[`src/runtime_plane/core/project_layout.py`](../../src/runtime_plane/core/project_layout.py)，
[`src/runtime_plane/artifacts/project_layout.py`](../../src/runtime_plane/artifacts/project_layout.py)
保留为兼容入口（L1 `output_config` 只允许依赖 core，因此实现放在 core）。
CLI、GUI、Agent 产物目录都只消费它，不再各自拼路径。

## 1. 五层模型

| 层 | 内容 | 本仓库落点 |
|---|---|---|
| L0 安装层 | 只读源码与工具 | 仓库根（`install_root()`） |
| L1 用户配置层 | 每用户配置 / 技能 | `$SIGNOFFAI_HOME` 或 `~/.signoffai` |
| L2 工程输入层 | spec / rtl / tb / ecn / ref / scripts / docs | `DESIGN_ROOT/` |
| L3 工程配置层 | `cli_config.yaml` | `DESIGN_ROOT/cli_config.yaml` |
| L4 产物层 | run、日志、manifest、归档 | `DESIGN_ROOT/chipstack_artifacts/` |
| L5 工作流层 | `<flow>/<flow>.yaml` + 函数模块 | `DESIGN_ROOT/workflows/` |

```text
DESIGN_ROOT/
├── cli_config.yaml                 # L3：artifact_root / top_module / template
├── extra_instructions.md
├── spec/ rtl/ tb/ ecn/ ref/ scripts/ docs/   # L2
├── workflows/                      # L5
└── chipstack_artifacts/            # L4（可整目录删除后重跑）
    ├── run_manifest.json           # 运行索引：latest_run_id + runs[]
    ├── artifacts.sqlite            # 跨 agent 查询索引（R-030）
    ├── compile_config.yaml         # R-014 / R-015
    ├── cli_logs/cli_YYYYMMDD-HHMMSS.log
    ├── Archive/<design>.<agent>.<timestamp>/
    ├── uvm_agent/                  # 2.0 手册：UVM 产物固定在 artifact root
    ├── tui/sessions/<name>.json    # 命名 TUI 会话索引
    ├── <top>/                      # streamlined：按设计聚合
    │   ├── compile_config.yaml
    │   ├── mental_model_agent/
    │   ├── formal_agent/
    │   └── ...
    └── <top>-<run_id>/             # run 级隔离（R-019 / R-049）
        ├── run_manifest.json       # R-021：run_id/started_at/entrypoint/...
        ├── run_results/
        ├── backup/<timestamp>/     # R-025
        ├── simulation_agent/
        ├── functional_coverage_agent/
        ├── dv_debug/
        └── ...
```

L0 只读；L4 与 L2 物理分离（`ProjectLayout.audit()` 的 R-018 检查）。除显式
RTL 修改流程外，agent 只能写 L4。

## 2. 五个 Agent Domain 与产物目录（R-020）

权威注册表：
[`src/agent_plane/domains.py`](../../src/agent_plane/domains.py)。代码目录名与
ChipStack 产物目录名不是一一同名，映射在这里固定：

| Domain（代码目录） | Agent | 产物子目录 |
|---|---|---|
| `design_understanding` | `mental_model_agent` | `mental_model_agent/` |
| `design_verification` | `simulation_agent` | `simulation_agent/` |
| `verification` | `test_plan_agent` | `test_plan_agent/` |
| `verification` | `formal_agent` | `formal_agent/` |
| `verification` | `functional_coverage_agent` | `functional_coverage_agent/` |
| `verification` | `uvm_coding_agent` | `uvm_agent/`（artifact root） |
| `verification` | `dv_debug_agent` | `dv_debug/` |
| `design_signoff` | `lint_autofix` | `lint_autofix/` |
| `design_generation` | `rtl_upgrade_agent` | `rtl_generation/` |
| `design_generation` | `rtl_early_estimation_agent` | `rtl_early_estimation_agent/` |

`ReActAgent.artifact_root` 直接由该表派生；`RunLayout.record_agent()` 写
`status.json` 并同步 `run_manifest.json` / `artifacts.sqlite`。没有执行的
能力只写 `NOT_RUN` / `INCOMPLETE`，不伪造报告。

## 3. 运行时接口

```python
from src.runtime_plane.artifacts import ProjectLayout, run_session

layout = ProjectLayout.discover(".")          # 读 cli_config.yaml，找不到也不抛
layout.ensure()                                # L4 骨架 + compile_config + 索引

with run_session(layout, "sync_fifo", entrypoint="vagent verify") as run:
    run.log_cli(["vagent", "verify"], note="formal 回归")
    with run.agent_scope("formal_agent"):
        ...                                    # 产物写 run.agent_dir("formal_agent")
    run.backup(["rtl/sync_fifo.sv"], reason="RTL upgrade")
```

关键方法：

- `ProjectLayout.scaffold(...)`：`project init` / GUI「初始化工程目录」的全套 L2–L5 建立；
- `ProjectLayout.create_run(...)`：`<top>-<run_id>`（run 隔离）或 `<top>`（streamlined）；
- `RunLayout.begin/finish`：`RUNNING` / `FINISHED` / `FAILED` manifest；
- `RunLayout.record_agent / agent_scope`：agent 子目录 + `status.json`；
- `RunLayout.log_cli`：每次 CLI 调用一份 `cli_logs/cli_*.log`（R-022）；
- `RunLayout.backup`：修改输入前备份（R-025）；
- `RunLayout.archive_agent`：`<design>.<agent>.<timestamp>` 归档（R-026）；
- `ProjectLayout.audit()`：§7 验收清单（`PASS/WARN/FAIL`）。

## 4. CLI

```bash
# L2/L3/L4/L5 初始化
vagent project init sync_fifo --top sync_fifo
vagent workspace init --top sync_fifo --force     # 就地初始化
vagent project layout                             # L0–L5 树
vagent project check [--strict]                   # §7 验收，FAIL 退出码 1
vagent project runs / agents [--run-id ...]

# L4 运行
vagent workspace new-run sync_fifo --agents formal_agent,simulation_agent
vagent workspace show
vagent workspace log --note "formal 回归"
vagent workspace backup rtl/sync_fifo.sv --reason "RTL upgrade"
vagent workspace archive formal_agent
vagent project clean [--legacy]                   # 删除产物根后可重跑
```

## 5. GUI（PySide6）

`project.workspace` 模块（[workspace.py](../../src/workbench/modules/service/workspace.py)）在
「项目」业务线下提供：

- L0–L5 目录树（缺失层灰显，双击打开目录）；
- §7 验收清单表（PASS/WARN/FAIL，可复制）；
- 运行索引表（双击打开 run 目录）；
- 五个 Domain 的 agent 产物表（双击打开 agent 目录）；
- 初始化工程目录 / 新建运行 / 打开产物根。

## 6. 与既有 ChipStack 工作区投影的关系

`ChipStackWorkspace`（interface-timing 产物投影）**保持原有证据语义**，只是
收敛到同一套目录契约：补 `compile_config.yaml`、R-021 必填 manifest 字段、
R-022 `cli_logs/cli_*.log`。它不接管 Cadence 数据库、不启动 ChipStack 服务。

## 7. 边界

- 目录契约不是签核结论；`NOT_RUN` / `INCOMPLETE` / `VALIDATED` / `PASS` 不可混用。
- 归档是逻辑不可变约定，不是密码学防篡改或操作系统写保护。
- LSF/跨主机场景下 `ARTIFACT_ROOT` 必须对所有执行节点可见（R-050）。
