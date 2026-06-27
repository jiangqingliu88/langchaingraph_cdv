# QuestaSim 回归测试配置

基于 `regression_framework` 的 QuestaSim 回归测试 YAML 配置集合。

## 文件结构

```
config/regression/
├── README.md                    # 本文件
├── questa_base.yaml             # 基础配置 (simulators, builds, 全局变量)
├── questa_smoke.yaml            # 冒烟测试 (快速检查, <5min)
├── questa_alu_full.yaml         # ALU 全量回归 (回环+矩阵+错误注入+覆盖率)
├── questa_apb_uart.yaml         # APB+UART 子系统回归
├── run_regression.sh            # Linux/WSL 启动脚本
└── run_regression.bat           # Windows 启动脚本
```

## 快速开始

### 1. 确保环境

```bash
# Python 3.8+
python --version

# QuestaSim 在 PATH 中
which vlog vsim vlib

# 安装 Python 依赖
pip install pyyaml jinja2 jsonschema requests tqdm
```

### 2. 冒烟测试 (首选)

```bash
# 模拟运行 — 查看会生成哪些命令
python src/tools/regression_tools/regression_framwork/regression.py \
    --config config/regression/questa_smoke.yaml \
    --action all --mode mock --dry-run

# 本地真实执行
python src/tools/regression_tools/regression_framwork/regression.py \
    --config config/regression/questa_smoke.yaml \
    --action all --mode local
```

或使用便捷脚本：

```bash
# Linux
bash config/regression/run_regression.sh smoke_mock   # 模拟
bash config/regression/run_regression.sh smoke         # 真实

# Windows
config\regression\run_regression.bat smoke_mock
config\regression\run_regression.bat smoke
```

### 3. 全量回归

```bash
# ALU 全量 (本地)
bash config/regression/run_regression.sh alu

# APB+UART 全量 (本地)
bash config/regression/run_regression.sh apb_uart

# LSF 集群
bash config/regression/run_regression.sh alu_lsf
```

## 配置说明

### Simulator 类型

| Simulator Key | 用途 | 关键差异 |
|:---|:---|:---|
| `questasim` | 标准仿真 | vlog + vsim, work 库 |
| `questasim_uvm` | UVM 仿真 | +incdir+UVM, -mfcu 编译 |
| `questasim_cov` | 覆盖率收集 | +cover=sbceft, -coverage |
| `questasim_debug` | 波形调试 | log -r /*, -wlf wave.wlf |

### Build 定义

| Build Name | Simulator | 包含内容 |
|:---|:---|:---|
| `build_alu` | questasim | ALU_in + ALU_out agents + env + bench |
| `build_alu_loopback` | questasim | 含 loopback env/scb/test/tb |
| `build_uart` | questasim_uvm | UART agent + env + seqs + tests + bench |
| `build_apb` | questasim | APB agent (agent/pkg/if/drv/mon/seq/cov) |

### 测试矩阵示例

```yaml
# 运算模式 × 位宽: 4×4=16 组合, 每组合 count=3 → 48 个仿真
- name: "alu_op"
  build: "build_alu"
  count: 3
  matrix:
    - { OP: ["ADD", "SUB", "MUL", "DIV"] }
    - { WIDTH: [8, 16, 32, 64] }
  name_format: "alu_op_{OP}_W{WIDTH}"
```

生成的任务名示例: `alu_op_ADD_W8_run_1`, `alu_op_ADD_W8_run_2`, ...

### 标签体系

| 标签 | 含义 | 适用场景 |
|:---|:---|:---|
| `smoke` | 冒烟测试 | CI/CD 每次提交 |
| `fast` | 快速测试 (< 1min) | 提交前检查 |
| `regression` | 常规回归 | 每日/每周回归 |
| `random` | 随机种子覆盖 | 充分性验证 |
| `stress` | 压力测试 | 发布前夜间回归 |
| `matrix` | 参数矩阵展开 | 边界覆盖 |
| `loopback` | 回环测试 | Agent 自检 |
| `error_inject` | 错误注入 | 鲁棒性验证 |
| `coverage` | 覆盖率收集 | 覆盖率收敛 |
| `nightly` | 夜间回归 | 成本较高的长时间测试 |
| `ci` | CI 流水线 | 自动触发的快速测试 |
| `debug` | 调试波形 | 需要波形文件的测试 |
| `direct` | 定向测试 | 特定场景验证 |
| `baud` | 波特率相关 | UART 波特率测试 |

## 命令行覆盖

```bash
# 覆盖 seed
python regression.py --config ... --set global_vars.SEED=7777

# 覆盖 UVM verbosity
python regression.py --config ... --set global_vars.UVM_VERBOSITY=UVM_HIGH

# 覆盖 LSF queue
python regression.py --config ... --set settings.lsf_opts.queue=priority

# 批量覆盖
python regression.py --config ... \
    --set global_vars.SEED=9999 \
    --set global_vars.WAVES=1 \
    --set global_vars.COV=1
```

## 输出目录结构

每次回归在项目根目录生成独立目录:

```
regression_local_20260626_120000/
├── .regression_state.json     # 断点续跑状态
├── report_summary.txt         # 文本摘要
├── report.html                # HTML 可视化报告
├── report.json                # JSON 结构化数据
├── run_all_local.sh           # 总入口脚本
├── pass/                      # 通过的测试 → 符号链接
├── fail/                      # 失败的测试 → 符号链接
├── unknown/                   # 未知状态 → 符号链接
├── build_alu/                 # ALU 编译目录
│   ├── build.sh              #   编译脚本
│   ├── pre_build.sh           #   编译前钩子
│   ├── test_alu_op_ADD_W8/   #   测试实例目录
│   │   ├── sim.sh            #     仿真脚本
│   │   ├── sim.log           #     仿真日志
│   │   ├── sim_time.log      #     耗时记录
│   │   └── wave.log          #     波形路径
│   └── ...
└── build_uart/
    └── ...
```

## 输出文件说明

| 文件 | 内容 |
|:---|:---|
| `report_summary.txt` | 通过/失败数量、每个测试的状态和耗时 |
| `report.html` | 可折叠 HTML 报告, 按 Build 分组, 波形链接 |
| `report.json` | 机器可读 JSON, 便于 CI 集成 |
| `.regression_state.json` | 已完成任务列表, 支持断点续跑 |
| `regression_trend.db` | SQLite 趋势数据库 (项目根目录) |

## 典型工作流

### 开发阶段 (每次 commit)

```bash
# 冒烟测试
bash config/regression/run_regression.sh smoke
```

### 每日回归

```bash
# ALU + UART 全量 (本地)
bash config/regression/run_regression.sh alu
bash config/regression/run_regression.sh apb_uart
```

### 发布前验证

```bash
# LSF 集群 + 覆盖率
python regression.py \
    --config config/regression/questa_alu_full.yaml \
    --mode lsf --lsf-queue normal \
    --tags nightly,coverage

# 命令行覆盖
python regression.py \
    --config config/regression/questa_apb_uart.yaml \
    --mode lsf --lsf-queue normal \
    --set global_vars.COV=1
```

### 增量回归 (基于 Git 变更)

```bash
# 只运行受最近 commit 影响的测试
bash config/regression/run_regression.sh alu_inc
```

### 重跑失败用例

```bash
# 从之前的回归目录提取失败用例
bash config/regression/run_regression.sh rerun regression_local_20260626_120000
```

### 按标签过滤

```bash
# 只跑 stress 标签
python regression.py --config config/regression/questa_alu_full.yaml --mode local --tags stress

# 排除 slow 标签
python regression.py --config config/regression/questa_apb_uart.yaml --mode local --exclude-tags slow
```

## 扩展指南

### 添加新的仿真器

编辑 `questa_base.yaml` 的 `settings.simulators`:

```yaml
simulators:
  questa_xrun:
    compile: "xrun -sv -work work {opts} {files}"
    run:     "xrun -R -sv_seed ${SEED} {run_opts}"
```

### 添加新的 Build

```yaml
builds:
  - name: "build_my_ip"
    simulator: "questasim"
    compile_opts: ["+incdir+${GEN_HOME}/my_ip"]
    files:
      - "${GEN_HOME}/my_ip/pkg.sv"
      - ...
    hooks:
      post_build: "./my_post_build.sh"
```

### 添加 Matrix 插件

```yaml
matrix:
  - plugin: "seed_generator"
    args: {count: 200, min: 1, max: 999999, mode: "random"}
```

## 目录

```
cdv_a/
├── config/regression/          ← QuestaSim 回归 YAML 配置 (本目录)
├── src/tools/regression_tools/
│   └── regression_framwork/    ← 回归框架源码
└── generated/                  ← 生成的 UVM 验证环境
    ├── alu/                    ← ALU agents + loopback
    └── verify_architect_test/  ← UART + APB agents + env
```
