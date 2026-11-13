# 文档生态工具集 (doc_tools)

通过 SQL 后端访问、搜索、追溯 MD 规格文档。

## Functions
- `search_docs(keyword, req_id, level, tags)`: 多条件搜索文档
- `get_doc(doc_id)`: 获取文档完整信息（内容+版本+需求）
- `get_req_trace(req_id)`: 需求追溯（需求ID → 来源文档 → 覆盖状态）
- `get_doc_tree(project_id)`: 文档层级树（父子关系）
- `list_doc_requirements(doc_id)`: 列出文档中的所有需求清单及覆盖状态

## Class
- `DocTools`: LangChain Agent 使用的工具集类

## Usage
```python
from src.generation.doc_tools import search_docs, get_doc

# 按关键词搜索
result = search_docs(keyword="baud", level="module")

# 按需求 ID 搜索
result = search_docs(req_id="REQ_ALU_BT_001")

# 获取文档详情
doc = get_doc(doc_id=1)

# 需求追溯
trace = get_req_trace("REQ_UART_TX_001")

# 文档层级树
tree = get_doc_tree(project_id=1)
```

## Consumed By
- 所有需要查询规格文档的 Agent
- SpecAndTestPlanner（规格分析时查文档）
- CoverageAnalyzer（覆盖率分析时追溯需求）
- RegressionManager（回归时关联文档）

## Test
```bash
pytest src/generation_plane/doc_tools/ -v
```
