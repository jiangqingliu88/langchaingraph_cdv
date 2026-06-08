# UVM 生成子系统

UVM (Universal Verification Methodology) 代码生成工具集群。

## 子工具

### tool_uvm
UVM 验证环境代码生成工具。从 YAML 描述符生成完整的 UVM SystemVerilog 代码：
- Interface 组件 (driver, monitor, agent)
- Environment 组件 (env, config, virtual sequencer)
- Bench 组件 (tb_top, assertions)
- 约束策略与序列
- Agent 回环测试环境

### tool_sc_red
SystemC 参考模型工具。生成 C++ 参考模型和 Scoreboard Predictor 桥接：
- Prod/Monitor 接口生成
- SC 参考模型模板
- UVMC (UVM-SystemC) 桥接

## Usage
```bash
# UVM 环境生成
python -m src.tools.uvm.main -i ALU_env.yaml -o generated/

# 列出模板
python -m src.tools.uvm.main --list-templates

# SC 参考模型生成
python -m src.tools.uvm.tool_sc_red.main
```

## Test
```bash
pytest src/tools/uvm/ -v
```
