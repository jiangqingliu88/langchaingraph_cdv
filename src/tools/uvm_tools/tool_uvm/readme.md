# UVM 环境代码生成工具 (tool_uvm)

从 YAML 描述符自动生成完整的 UVM SystemVerilog 验证环境代码。

## Features
- 基于 Jinja2 模板的代码生成
- 支持 interface agent, environment, bench 三层
- Agent 回环测试环境自动生成
- 约束策略与序列生成
- 编译文件列表 (filelist) 生成

## Key Classes
- `UVMGenerator`: 主生成器
- `JinjaRenderer`: 模板渲染引擎
- `YAMLLoader`: YAML 配置加载器
- `AgentModel`, `EnvironmentModel`, `BenchModel`: 数据模型
- `ConstraintModel`: 约束模型

## YAML Config Files
- `ALU_env.yaml` — 环境定义
- `ALU_in.yaml` — 接口定义
- `ALU_constraint.yaml` — 约束定义
- `ALU_bench.yaml` — Bench 定义

## Entry Point
```bash
# 生成 UVM 环境
python -m src.tools.uvm_tools.tool_uvm.main -i ALU_env.yaml -o generated/

# 列出模板
python -m src.tools.uvm_tools.tool_uvm.main --list-templates
```

## Output
```
generated/<module>/
├── shared/       # transaction, interface, driver, monitor, agent
├── agent_tb/     # Agent 回环验证 TB
├── env_tb/       # 完整验证环境 TB
├── filelist.f    # QuestaSim 编译文件列表
└── quality_report.json
```

## Consumed By
- `VerificationArchitect` agent

## Test
```bash
pytest src/tools/uvm_tools/tool_uvm/ -v
```
