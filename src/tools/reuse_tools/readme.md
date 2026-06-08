# 复用工具集 (reuse_tools)

VIP 扫描、搜索、匹配和参数化复用的工具集。

## Functions
- `scan_environment(env_dir)`: 扫描环境目录
- `extract_interface_info(component_dir)`: 提取接口信息
- `auto_parameterize(component_dir)`: 自动参数化
- `normalize_naming(component_dir)`: 规范化命名
- `backup_to_library(source_dir, component_name)`: 备份到库
- `search_library(query, library_dir)`: 搜索 VIP 库
- `match_vip(dut_interfaces_json, library_dir)`: 匹配 VIP
- `generate_integration_code(vip_name, target_env_name)`: 生成集成代码
- `generate_reuse_report(project_name)`: 生成复用报告
- `library_stats(library_dir)`: 库统计

## Class
- `ReuseTools`: LangChain Agent 使用的工具集类

## Test
```bash
pytest src/tools/reuse_tools/ -v
```
