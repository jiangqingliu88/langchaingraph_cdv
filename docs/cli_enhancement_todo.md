# SignOffAI CLI 增强 TODO List

> 日期：2026-08-09  
> 当前 CLI：699 行，10 个命令  
> 目标：对标 `git`/`docker` 的命令行体验，支持 CI/CD 集成和交互式调试

---

## 当前状态总览

```
已有命令（10 个）：
  vagent init         ✅ 创建输出目录
  vagent verify       ✅ 运行验证流水线
  vagent dump         ✅ 导出证据包
  vagent watch        ✅ 实时监控流水线
  vagent status       ⚠️ 仅列出 Agent 状态
  vagent history      ❌ 占位符（空实现）
  vagent debug_log    ⚠️ 仅查看日志
  vagent workflows    ❌ 占位符（写死两行字）
  vagent repl         ✅ 交互调试控制台
  vagent web          ⚠️ 启动 Web 服务器
```

---

## P0 — 核心验证流程（必须实现）

### 1. `vagent verify` 增强（已有，需扩展）

当前只支持 `--workflow` 和 `--refine`，需要增加：

```bash
# 子阶段执行（不跑全流程，只跑指定阶段）
vagent verify --step coverage          # 只跑覆盖率分析
vagent verify --step regress           # 只跑回归
vagent verify --from UVM               # 从 UVM 阶段开始跑
vagent verify --to test                # 跑到 test 阶段停止
vagent verify --steps UVM,test,regress # 跑指定几个阶段

# 输出格式控制（CI 集成关键）
vagent verify --json                   # 纯 JSON 输出（给 CI）
vagent verify --summary                # 仅输出最终摘要
vagent verify --quiet                  # 只打印错误

# 上下文复用（增量验证）
vagent verify --resume <run_id>        # 断点续跑
vagent verify --retry-failed           # 只重跑失败阶段
vagent verify --ctx <json_file>        # 从外部注入上下文
```

**工作量**：~200 行，在现有 `verify` 命令上增加 `click.option`

---

### 2. `vagent signoff` — 签核命令（新建）

```bash
# 签核报告生成
vagent signoff <run_id>                    # 为指定 run 生成签核报告
vagent signoff <run_id> --type tapeout     # 流片签核
vagent signoff <run_id> --type milestone   # 里程碑签核

# 证据链
vagent signoff <run_id> --export evidence.zip  # 导出签核证据包
vagent signoff <run_id> --verify               # 验证证据链完整性
vagent signoff <run_id> --checklist            # 输出签核检查清单

# 对比签核
vagent signoff --diff <run_a> <run_b>      # 两次签核对比
```

**工作量**：~150 行

---

### 3. `vagent diff` — 版本差异对比（新建）

```bash
# 覆盖率对比
vagent diff coverage --run-a <id1> --run-b <id2>
vagent diff coverage --run-a <id1> --run-b <id2> --format table

# 规格变更影响分析
vagent diff spec --old <spec_v1.md> --new <spec_v2.md>

# 回归结果对比
vagent diff regression --run-a <id1> --run-b <id2>
```

**工作量**：~120 行

---

## P1 — 工具调用与调试（需实现）

### 4. `vagent tool` — 工具发现与直接调用（新建）

```bash
# 工具发现
vagent tool list                              # 列出所有已注册工具
vagent tool list --agent verify_architect     # 列出某 Agent 的工具
vagent tool list --risk safe                  # 按风险等级过滤
vagent tool show <tool_name>                  # 查看工具详情（Schema/描述/风险等级）

# 直接调用工具（绕过 LLM）
vagent tool call <tool_name> --args '{"tb":"tb_top.sv"}'          # JSON 参数
vagent tool call gen_test_sv --gap burst_16 --out test.sv         # 命名参数
vagent tool call read_report --path output/coverage.json          # 文件路径参数

# 工具调用历史
vagent tool history                           # 查看最近调用
vagent tool history --limit 20                # 最近 20 条
vagent tool history --tool run_vcs            # 指定工具的调用记录
```

**工作量**：~180 行

---

### 5. `vagent agent` — Agent 管理命令组（新建）

```bash
# Agent 详情（不只是 status）
vagent agent list                             # 列出所有 Agent + 摘要
vagent agent show <role>                      # 查看单个 Agent 详情（I/O 契约/工具/指标）
vagent agent show <role> --tools              # 列出该 Agent 的工具
vagent agent show <role> --contract           # 显示 consumes/produces/min_score

# Agent 单独执行（测试单个 Agent）
vagent agent run <role> --input '{"spec":{...}}'     # JSON 输入
vagent agent run <role> --spec <file.md>             # 从文件读取输入
vagent agent run <role> --spec <file.md> --dry-run   # 不真正执行，只打印会调用哪些工具
```

**工作量**：~160 行

---

### 6. `vagent debug` — 调试命令增强（替换 debug_log）

```bash
# 替换当前的 debug_log，增强功能
vagent debug log --run <run_id>                    # 查看某次运行的完整日志
vagent debug log --run <run_id> --phase UVM        # 只看 UVM 阶段日志
vagent debug log --run <run_id> --level error      # 只看错误日志
vagent debug log --run <run_id> --agent debug_engineer  # 只看某 Agent

# 失败分析
vagent debug analyze --run <run_id>                # 分析失败原因（调用 debug_engineer）
vagent debug analyze --log <sim.log>               # 分析仿真日志

# 交互式调试（现有 repl 的增强版）
vagent debug repl                                  # 进入交互调试模式
vagent debug repl --agent spec                     # 进入指定 Agent 的调试模式
```

**工作量**：~180 行（替换现有 40 行 `debug_log` + `repl`）

---

## P2 — 项目与配置管理（应实现）

### 7. `vagent config` — 配置管理（新建）

```bash
# 查看配置
vagent config show                   # 显示当前完整配置
vagent config show --section llm     # 只看 LLM 配置
vagent config show --section agent   # 只看 Agent 配置

# 修改配置
vagent config set llm.model deepseek-chat
vagent config set llm.temperature 0.3
vagent config set agent.max_iterations 10

# 配置初始化
vagent config init                   # 生成默认 .env 文件
vagent config validate               # 校验配置完整性
```

**工作量**：~130 行

---

### 8. `vagent project` — 项目管理（新建）

```bash
# 项目初始化
vagent project init <name>                    # 创建新项目目录结构
vagent project init <name> --template uart    # 使用模板
vagent project init <name> --template axi     # 使用 AXI 模板

# 项目状态
vagent project status                         # 当前项目状态概览
vagent project info                           # 项目详细信息
vagent project list                           # 列出所有项目

# 清理
vagent project clean                          # 清理输出目录
vagent project clean --all                    # 清理所有（含日志）
```

**工作量**：~150 行

---

### 9. `vagent spec` — 规格文档操作（新建）

```bash
# 规格分析（不跑全流水线）
vagent spec analyze <file.md>                 # 分析规格文档，输出结构化 JSON
vagent spec analyze <file.md> --format table  # 表格格式输出
vagent spec validate <file.md>                # 校验规格文档完整性

# 规格转换
vagent spec convert <file.md> --to json       # MD → 结构化 JSON
vagent spec convert <file.json> --to md       # JSON → MD

# 需求追溯
vagent spec trace <req_id>                    # 追溯需求 → 模块 → 测试点
vagent spec trace <req_id> --full             # 完整追溯链
```

**工作量**：~140 行

---

## P3 — 高级功能（长远规划）

### 10. `vagent ci` — CI/CD 集成命令

```bash
# CI 模式（最小化输出 + 退出码）
vagent ci verify --spec <file.md>              # CI 模式运行
vagent ci verify --spec <file.md> --junit      # 输出 JUnit XML
vagent ci verify --spec <file.md> --gitlab     # GitLab CI 格式

# CI 检查
vagent ci check                                # 检查 CI 环境是否就绪
vagent ci precheck --spec <file.md>            # 预检查（不实际执行）
```

### 11. `vagent regression` — 回归管理

```bash
vagent regression run --tests <yaml>            # 运行回归
vagent regression report --run <id>             # 回归报告
vagent regression trend --days 30               # 30 天趋势
vagent regression compare --run-a a --run-b b   # 两次回归对比
```

### 12. `vagent coverage` — 覆盖率管理

```bash
vagent coverage report --run <id>               # 覆盖率报告
vagent coverage gaps --run <id>                 # 覆盖率缺口
vagent coverage trend --days 30                 # 覆盖率趋势
vagent coverage merge --runs a,b,c              # 合并多次覆盖率
```

### 13. `vagent env` — UVM 环境操作

```bash
vagent env generate --spec <file.md>            # 生成 UVM 环境
vagent env validate --dir <env_dir>             # 校验 UVM 环境
vagent env compile --dir <env_dir>              # 编译 UVM 环境
vagent env template --type agent --name uart    # 生成单个组件模板
```

### 14. `vagent plugin` — 插件管理

```bash
vagent plugin list                              # 列出已安装插件
vagent plugin install <name>                    # 安装插件
vagent plugin enable <name>                     # 启用插件
```

---

## 工作量汇总

| 优先级 | 命令 | 类型 | 预估行数 | 累计行数 |
|:---:|------|------|:---:|:---:|
| P0 | `verify` 增强 | 扩展 | 200 | 200 |
| P0 | `signoff` | 新建 | 150 | 350 |
| P0 | `diff` | 新建 | 120 | 470 |
| P1 | `tool` | 新建 | 180 | 650 |
| P1 | `agent` | 新建 | 160 | 810 |
| P1 | `debug` | 替换增强 | 180 | 990 |
| P2 | `config` | 新建 | 130 | 1,120 |
| P2 | `project` | 新建 | 150 | 1,270 |
| P2 | `spec` | 新建 | 140 | 1,410 |
| P3 | `ci` / `regression` / `coverage` / `env` / `plugin` | 新建 | ~800 | ~2,200 |

**总计：从 699 行扩展到 ~2,200 行（3 倍），从 10 个命令扩展到 19+ 个子命令组。**

---

## 命令总览对照

```
增强前（10 条命令）：              增强后（19 条命令组，40+ 子命令）：

vagent init                       vagent init
vagent verify [--workflow]        vagent verify  [--step/--json/--resume/--retry-failed/...]
vagent dump                       vagent dump    (保持，增强 --diff)
vagent watch                      vagent watch   (保持)
vagent status                     vagent status  (保持)
vagent history  ← 占位符           vagent history  (保持)
vagent debug_log                  vagent debug   log/analyze/repl
vagent workflows ← 占位符          vagent workflows (改为动态读取)
vagent repl                       vagent repl    (合并到 vagent debug repl)
vagent web                        vagent web     (保留但降优先级)
                    新 增 →
                                  vagent signoff  (签核)
                                  vagent diff     (差异对比)
                                  vagent tool     (工具调用)
                                  vagent agent    (Agent 管理)
                                  vagent config   (配置管理)
                                  vagent project  (项目管理)
                                  vagent spec     (规格操作)
                                  vagent ci       (CI 集成)
                                  vagent regression (回归管理)
                                  vagent coverage (覆盖率管理)
                                  vagent env      (环境操作)
```

---

## 共享基础设施

所有命令需要的公共能力（与 UI 无关，在 `src/cli/` 内实现）：

### 输出适配器

```python
# src/cli/output.py
class OutputAdapter:
    """统一输出 — 自动检测终端/CI/文件"""
    def __init__(self, fmt: Literal["auto", "rich", "json", "plain"] = "auto"):
        ...
    def print_result(self, data: dict, title: str = ""): ...
    def print_table(self, headers: list, rows: list): ...
    def print_error(self, msg: str, code: int = 1): ...
    def print_progress(self, current: int, total: int, label: str): ...
```

### 公共参数

```python
# 所有命令共用的 click decorator
def common_options(f):
    """注入全局选项: --json / --quiet / --verbose / --output-dir"""
    ...
```

### 自动补全

```bash
# 生成 shell 补全脚本
vagent completion bash  > /etc/bash_completion.d/vagent
vagent completion zsh   > ~/.zsh/completions/_vagent
vagent completion fish  > ~/.config/fish/completions/vagent.fish
```

---

## 实施路线图

```
Week 1-2: P0 核心验证流程
  ├── vagent verify 增强 (--step/--json/--resume/--retry-failed)
  ├── vagent signoff  (签核报告 + 证据链)
  └── vagent diff     (覆盖率对比 + 规格对比)

Week 3-4: P1 工具与调试
  ├── vagent tool     (工具发现 + 直接调用)
  ├── vagent agent    (Agent 管理 + 单独执行)
  └── vagent debug    (日志分析 + 失败定位)

Week 5-6: P2 配置与项目
  ├── vagent config   (配置管理)
  ├── vagent project  (项目管理)
  └── vagent spec     (规格操作)

Week 7+: P3 高级功能
  ├── vagent ci       (CI/CD 集成)
  ├── vagent regression/coverage/env (专项管理)
  └── shell 自动补全
```

---

## 验收标准

1. **CI 可集成**：`vagent verify --json --quiet` → 退出码 0/非0 + stdout JSON
2. **人不迷路**：`vagent --help` → 三级命令树，每个命令有示例
3. **错误可诊断**：命令失败时输出明确错误信息 + `--debug` 模式打印堆栈
4. **进度可感知**：`vagent verify` 实时输出阶段进度，`vagent watch` 可监控后台运行
5. **数据可追溯**：`vagent signoff <run_id> --export` 导出完整证据包
