# 回归测试框架 (Regression Framework)

一个功能强大、高度可配置的回归测试自动化框架，专为芯片验证设计，支持多模式执行、任务依赖管理、LSF集群调度、报告生成与趋势分析。

---

## 🚀 核心特性

- **配置驱动**: 基于YAML的声明式配置，支持`include`、`extends`继承、变量替换（`${VAR}`）
- **参数化测试**: 通过`matrix`自动展开参数组合，`count`支持重复运行（自动递增种子）
- **灵活执行模式**: 支持`mock`（模拟）、`local`（本地顺序执行）、`lsf`（集群提交）
- **任务依赖管理**: 基于DAG（有向无环图）的依赖关系解析，自动拓扑排序
- **增量回归**: 基于Git变更自动过滤受影响测试，大幅缩短回归时间
- **断点续跑**: 支持中断恢复，避免重复执行已完成任务
- **编译缓存**: 基于MD5哈希自动缓存编译结果，加速多测试共享编译
- **并行编译**: 支持多Build并行执行，充分利用多核资源
- **动态并行度**: LSF模式下根据集群负载自动调整并发数
- **测试过滤**: 支持正则表达式过滤测试名称，支持按Build过滤
- **标签过滤**: 通过`--tags`/`--exclude-tags`按标签筛选测试
- **命令行覆盖**: 使用`--set key=value`动态覆盖YAML配置
- **失败重跑**: `--rerun-failed`自动提取失败用例并复制脚本到新目录
- **报告生成**: 
  - 美观的HTML报告（可折叠分组）
  - JSON格式机器可读报告
  - 文本摘要报告
- **趋势分析**: 自动将每次回归结果存入SQLite数据库，支持历史趋势查询
- **通知集成**: 支持Slack Webhook通知（可扩展Email/钉钉）
- **日志系统**: 完善的logging模块，支持文件输出和不同日志级别
- **跨平台**: 支持Linux/macOS/Windows（WSL或原生环境）

---

## 📦 安装

### 环境要求
- Python 3.8+
- 推荐使用虚拟环境

### 安装步骤

```bash
# 克隆或下载框架代码
cd /path/to/regression_framework

# 创建虚拟环境（可选）
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

`requirements.txt` 内容：
```
pyyaml>=6.0
jinja2>=3.1.2
jsonschema>=4.17.0
requests>=2.28.0
```

---

## 🧭 快速开始

### 1. 准备YAML配置文件

创建一个示例配置 `my_regression.yaml`：

```yaml
global_vars:
  SEED: 12345
  WAVES: 0
settings:
  default_build: build_base
  default_count: 1
  simulators:
    vcs:
      compile: "vcs -full64 -sverilog {opts} {files}"
      run: "./simv +vcs+lic+wait {run_opts}"
builds:
  - name: build_base
    compile_opts: ["-debug_access+all"]
    files: ["rtl/*.v", "tb/*.sv"]
tests:
  - name: test_smoke
    build: build_base
    count: 1
    run_opts: ["+UVM_TESTNAME=smoke_test", "+seed=${SEED}"]
    expect: {errors: 0}
    tags: ["smoke"]
```

### 2. 运行回归

```bash
# 模拟运行（仅打印命令，不实际执行）
python regression.py --config my_regression.yaml --action all --mode mock

# 本地真实执行（顺序运行）
python regression.py --config my_regression.yaml --action all --mode local

# LSF集群提交
python regression.py --config my_regression.yaml --action all --mode lsf --lsf-queue normal --lsf-project my_project
```

### 3. 查看结果

运行后会在输出目录生成：
- `report_summary.txt` – 文本摘要
- `report.html` – HTML可视化报告
- `report.json` – 结构化数据
- `pass/`、`fail/`、`unknown/` – 符号链接（或路径记录）

---

## 📝 YAML 配置详解

### 顶层结构

```yaml
includes:          # 引用其他YAML文件
  - common.yaml
  - project_a.yaml

global_vars:       # 全局变量，可在任何地方通过 ${VAR} 引用
  SEED: 12345
  WAVES: 0

settings:          # 全局设置
  default_build: build_base
  default_count: 1
  simulators:      # 仿真器命令模板
    vcs:
      compile: "vcs -full64 -sverilog {opts} {files}"
      run: "./simv +vcs+lic+wait {run_opts}"
  hooks:           # 全局钩子
    pre_build: "./common/pre_build.sh"
    post_sim: "./common/post_sim.sh"
  lsf_opts:        # LSF全局选项
    queue: normal
    resource: "rusage[mem=4096]"
  build_cache: true   # 启用编译缓存

builds:            # 编译任务定义
  - name: build_base
    simulator: vcs
    compile_opts: ["-debug_access+all"]
    files: ["rtl/*.v", "tb/*.sv"]
    local_vars: { WAVES: 0 }
    hooks:
      post_build: "./scripts/merge_cov.sh"

tests:             # 测试用例定义
  - name: test_alu
    build: build_base
    count: 2
    matrix:          # 参数组合展开
      - { MODE: ["ADD", "SUB"] }
      - { WIDTH: [8, 16] }
    name_format: "alu_{MODE}_{WIDTH}"  # 自定义实例命名
    local_vars:
      UVM_TEST: "alu_test"
    run_opts:
      - "+UVM_TESTNAME=${UVM_TEST}"
      - "+MODE=${MODE}"
      - "+WIDTH=${WIDTH}"
      - "+seed=${SEED}"
    expect:
      errors: 0
    tags: ["regression", "alu"]
    file_pattern: ["rtl/alu/*.v"]  # 增量回归匹配
```

### 关键字段说明

| 字段 | 说明 |
| :--- | :--- |
| `includes` | 引用其他YAML文件，支持嵌套 |
| `global_vars` | 全局变量，可被 `${VAR}` 引用 |
| `settings.default_count` | 默认重复次数，`count`未指定时使用 |
| `matrix` | 参数组合列表，自动展开为多个测试实例 |
| `name_format` | 自定义实例命名模板，支持 `{idx}` 和参数变量 |
| `count` | 重复运行次数，自动递增 `SEED`（若存在） |
| `file_pattern` | 增量回归时匹配变更文件的通配符列表 |
| `tags` | 标签，用于 `--tags` / `--exclude-tags` 过滤 |
| `hooks` | 可在 `pre_build`、`post_build`、`pre_sim`、`post_sim` 插入脚本 |

---

## 🎛️ 命令行使用

### 基本选项

```bash
python regression.py --config <yaml> --action {generate|run|all} --mode {mock|local|lsf}
```

### 常用参数

| 参数 | 说明 |
| :--- | :--- |
| `--config` | YAML配置文件路径 |
| `--action` | `generate`(仅生成脚本)、`run`(仅运行)、`all`(生成+运行) |
| `--mode` | `mock`(模拟)、`local`(本地)、`lsf`(集群) |
| `--input-dir` | 指定已有目录进行运行（跳过生成） |
| `--output-dir` | 指定输出目录（默认自动生成） |
| `--backend` | `shell`(生成Shell脚本) 或 `makefile` |
| `--build-only` | 只编译，不运行测试 |
| `--test-only` | 只运行测试，假设编译已完成 |
| `--parallel-builds N` | 并行编译数量（默认1） |
| `--incremental` | 启用增量回归（基于Git变更） |
| `--repo-path` | Git仓库路径（默认当前目录） |
| `--tests` | 正则表达式过滤测试名称（如 `test_alu.*`） |
| `--exclude-tests` | 排除匹配的测试 |
| `--builds` | 按Build名称过滤（逗号分隔） |
| `--set key=value` | 覆盖YAML配置项（支持嵌套路径） |
| `--rerun-failed` | 从之前回归目录提取失败用例并复制脚本 |
| `--dry-run` | 仅打印任务列表，不执行 |
| `--verbose` | 输出DEBUG级别日志 |
| `--log-file` | 将日志写入文件 |

### LSF相关

| 参数 | 说明 |
| :--- | :--- |
| `--lsf-queue` | LSF队列名 |
| `--lsf-project` | LSF项目名 |
| `--lsf-resource` | LSF资源需求（如 `rusage[mem=8192]`） |

### 示例

```bash
# 只运行冒烟测试（标签过滤）
python regression.py --config reg.yaml --mode local --tags smoke

# 只运行指定测试（正则）
python regression.py --config reg.yaml --mode local --tests "test_alu.*"

# 排除慢测试
python regression.py --config reg.yaml --mode local --exclude-tests ".*slow.*"

# 增量回归（只跑受影响的测试）
python regression.py --config reg.yaml --mode lsf --incremental --repo-path /path/to/repo

# 命令行覆盖参数
python regression.py --config reg.yaml --mode local --set global_vars.SEED=9999

# 干跑模式查看任务列表
python regression.py --config reg.yaml --mode local --dry-run

# 从失败用例重跑
python regression.py --rerun-failed regression_lsf_20260626_120000

# 启用详细日志并保存到文件
python regression.py --config reg.yaml --mode lsf --verbose --log-file regression.log
```

---

## 📊 报告与趋势

### 报告输出
每次回归完成后，在输出目录下生成：
- `report_summary.txt` – 快速查看通过/失败统计
- `report.html` – 交互式HTML报告，可按Build分组展开
- `report.json` – 结构化数据，便于工具集成
- `pass/`、`fail/`、`unknown/` – 符号链接到对应测试工作目录

### 趋势数据库
框架自动将每次回归的摘要写入当前目录下的 `regression_trend.db` SQLite文件，包含：
- `runs` 表：时间戳、总用例数、通过/失败/未知数、通过率
- `task_details` 表：每个任务的名称、状态、工作目录、错误指纹

您可以使用任何SQLite浏览器或编写查询脚本进行历史趋势分析。

---

## 🧩 插件化扩展

### Matrix 自定义生成
可以在 `plugins/matrix_functions.py` 中定义函数，在YAML中通过 `plugin` 字段调用：

```yaml
matrix:
  - plugin: "generate_seeds"
    args: {count: 10, min: 1, max: 9999}
```

### 通知扩展
继承 `Notifier` 类（位于 `src/regression_framework/notifiers/`），实现 `notify` 方法，然后在主入口中集成。

---

## ⚙️ 高级特性

### 1. 增量回归
通过 `--incremental` 启用，框架会检测Git仓库中 `HEAD~1` 的变更文件，与测试的 `file_pattern` 匹配，只运行受影响的测试。未指定 `file_pattern` 的测试默认包含。

### 2. 断点续跑
框架在输出目录下维护 `.regression_state.json` 文件，记录已完成的任务。如果回归被中断，重新运行同一目录会自动跳过已完成任务。

### 3. 编译缓存
在 `settings` 中启用 `build_cache: true`，框架会对每个Build生成MD5哈希值（基于编译选项、文件列表、局部变量），若缓存命中则直接复制缓存目录，跳过实际编译。缓存目录默认为 `.build_cache`。

### 4. 动态并行度
在LSF模式下，框架会查询 `bqueues` 获取当前集群作业数，自动调整并行编译数量（负载高时减半，负载低时加倍）。

---

## 🔧 故障排查

### 1. YAML编码问题
如果遇到 `UnicodeDecodeError`，确保YAML文件保存为UTF-8编码，并删除BOM头。

### 2. LSF作业状态收集
框架通过 `bjobs -o 'id stat'` 轮询作业状态，若作业已完成但未正确收集，检查 `job.log` 是否包含错误关键词（`ERROR`、`FATAL`、`UVM_ERROR`、`FAILED`）。

### 3. 符号链接创建失败（Windows）
Windows默认需要管理员权限或开发者模式才能创建符号链接。框架在Windows上会降级为创建 `.txt` 路径记录文件和空目录占位。

### 4. 日志级别调整
使用 `--verbose` 输出DEBUG日志，或 `--log-file` 保存完整日志到文件。

---

## 🤝 贡献与支持

欢迎提交Issue和Pull Request。如有问题，请查阅文档或联系项目维护者。

---

## 📄 许可证

本项目采用 MIT 许可证。

---

*Generated by Regression Framework Team*