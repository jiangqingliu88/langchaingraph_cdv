# 调试工具集 (debug_tools)

分析仿真日志、定位问题根因的工具集。

## Functions
- `analyze_simulation_log(log_path)`: 分析仿真日志
- `analyze_waveform(waveform_path, signals)`: 分析波形
- `trace_error_source(error_description)`: 追踪错误源
- `generate_fix_suggestion(root_cause)`: 生成修复建议

## Class
- `DebugTools`: LangChain Agent 使用的工具集类

## Consumed By
- `DebugEngineer` agent

## Test
```bash
pytest src/tools/checking/debug_tools/ -v
```
