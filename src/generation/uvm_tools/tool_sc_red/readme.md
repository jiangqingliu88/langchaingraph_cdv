# SystemC 参考模型工具 (tool_sc_red)

生成 SystemC 参考模型和 Scoreboard Predictor 桥接 (RTL-SC integration via UVMC)。

## Features
- Prod/Monitor 接口自动生成 (Jinja2 模板)
- SC 参考模型模板渲染
- UVMC (UVM-SystemC) 桥接代码

## Usage
```bash
python -m src.generation.uvm_tools.tool_sc_red.main
```

## Files
- `generate.py` — 主生成逻辑
- `mpu_sc_pred.yaml` — SC Predictor 配置
- `sc_pred_templates/` — Jinja2 模板
- `rtl_sc/` — RTL-SC 集成代码 (Verilog + C++)

## Consumed By
- `ModelAgent` — 参考模型工程师

## Test
```bash
pytest src/generation/uvm_tools/ -v
```
