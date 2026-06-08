# UVM 工具集 (uvm_tools)

UVM 代码生成的向后兼容重导出层。

## Exports
- `generate_uvm`: UVM 代码生成函数（委托至 `src.tools.uvm`）

## Usage
```python
from src.tools.uvm_tools import generate_uvm
result = generate_uvm("agent", yaml_spec)
```

## See Also
- `src/tools/uvm/` — UVM 生成核心模块
- `src/tools/uvm/tool_uvm/` — UVM 环境生成工具
- `src/tools/uvm/tool_sc_red/` — SystemC 参考模型工具

## Test
```bash
pytest src/tools/uvm_tools/ -v
```
