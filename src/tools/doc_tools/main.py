"""
MD 文档生态工具集 — 通过 SQL 后端读写规格文档

这些工具供 LangChain Agent 调用，提供：
- 多条件搜索文档（关键词 / 需求ID / 层级 / 标签）
- 获取文档完整信息（内容 + 版本历史 + 需求列表）
- 需求追溯（需求ID → 来源文档 → 覆盖状态）
- 文档层级树（父子关系）
- 列出文档中的需求清单
"""
from langchain.tools import tool
import asyncio
import json

from src.layers.l4_memory.persistence import repository

# 公开给测试与外部调用者直接 patch/替换
search_documents = repository.search_documents
get_document = repository.get_document
get_requirement_trace = repository.get_requirement_trace
get_document_tree = repository.get_document_tree


def _search_docs_impl(keyword: str = "", req_id: str = "", level: str = "", tags: str = "") -> str:
    """搜索 MD 规格文档。可按关键词、需求ID（如 REQ_ALU_BT_001）、层级（chip/subsystem/module）、标签搜索。
    返回匹配的文档列表（id, path, title, level, status, tags, updated_at）。"""
    docs = asyncio.run(search_documents(
        keyword=keyword, req_id=req_id, level=level or None, tags=tags or None, limit=50
    ))
    return json.dumps(docs, ensure_ascii=False, indent=2)


def _get_doc_impl(doc_id: int) -> str:
    """获取单个文档的完整内容、版本历史和需求列表。输入 doc_id（整数）。
    返回: {id, path, title, content, level, status, tags, versions, requirements}"""
    doc = asyncio.run(get_document(doc_id))
    if not doc:
        return json.dumps({"error": f"文档 ID {doc_id} 不存在"}, ensure_ascii=False)
    return json.dumps(doc, ensure_ascii=False, indent=2)


def _get_req_trace_impl(req_id: str) -> str:
    """追溯一个需求 ID（如 REQ_UART_TX_001）的来源文档、覆盖状态。
    返回: {req_id, description, req_type, is_covered, source_doc}"""
    r = asyncio.run(get_requirement_trace(req_id))
    if not r:
        return json.dumps({"error": f"需求 {req_id} 未找到"}, ensure_ascii=False)
    return json.dumps(r, ensure_ascii=False, indent=2)


def _get_doc_tree_impl(project_id: int = 1) -> str:
    """获取项目的文档层级树结构（父子关系）。输入 project_id（整数）。
    返回嵌套的树形 JSON。"""
    tree = asyncio.run(get_document_tree(project_id))
    return json.dumps(tree, ensure_ascii=False, indent=2)


def _list_doc_requirements_impl(doc_id: int) -> str:
    """列出指定文档中的所有需求 ID 及覆盖状态。输入 doc_id（整数）。
    返回: [{req_id, description, req_type, line_number, is_covered}, ...]"""
    doc = asyncio.run(get_document(doc_id))
    if not doc:
        return json.dumps({"error": f"文档 ID {doc_id} 不存在"}, ensure_ascii=False)
    return json.dumps(doc.get('requirements', []), ensure_ascii=False, indent=2)


search_docs_tool = tool("search_docs")(_search_docs_impl)
get_doc_tool = tool("get_doc")(_get_doc_impl)
get_req_trace_tool = tool("get_req_trace")(_get_req_trace_impl)
get_doc_tree_tool = tool("get_doc_tree")(_get_doc_tree_impl)
list_doc_requirements_tool = tool("list_doc_requirements")(_list_doc_requirements_impl)

# 保留可直接调用的 Python 函数接口，并提供 LangChain 工具实例供 Agent 使用
search_docs = _search_docs_impl
get_doc = _get_doc_impl
get_req_trace = _get_req_trace_impl
get_doc_tree = _get_doc_tree_impl
list_doc_requirements = _list_doc_requirements_impl


class DocTools:
    """Agent 可用的文档工具集 — 通过 SQL 后端访问规格文档"""
    def get_tools(self):
        return [search_docs_tool, get_doc_tool, get_req_trace_tool, get_doc_tree_tool, list_doc_requirements_tool]
