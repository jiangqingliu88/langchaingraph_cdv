"""文档工具集单元测试"""
import pytest
import json
from unittest.mock import patch, AsyncMock


class TestDocTools:
    """测试 doc_tools 工具函数"""

    def test_search_docs_returns_json(self):
        """search_docs 应返回有效 JSON"""
        from src.experience_plane.docs.main import search_docs

        mock_docs = [{'id': 1, 'path': 'alu/alu_arith_spec.md', 'title': 'ALU 算术规格'}]
        with patch('src.experience_plane.docs.main.search_documents', new_callable=AsyncMock) as m:
            m.return_value = mock_docs
            result = search_docs(keyword="alu")
            data = json.loads(result)
            assert isinstance(data, list)
            assert data[0]['id'] == 1

    def test_get_doc_returns_json(self):
        """get_doc 应返回有效 JSON"""
        from src.experience_plane.docs.main import get_doc

        mock_doc = {'id': 1, 'path': 'alu/alu_arith_spec.md', 'title': 'ALU', 'content': '# ALU',
                    'versions': [], 'requirements': []}
        with patch('src.experience_plane.docs.main.get_document', new_callable=AsyncMock) as m:
            m.return_value = mock_doc
            result = get_doc(doc_id=1)
            data = json.loads(result)
            assert data['id'] == 1

    def test_get_doc_not_found(self):
        """不存在的文档应返回 error"""
        from src.experience_plane.docs.main import get_doc

        with patch('src.experience_plane.docs.main.get_document', new_callable=AsyncMock) as m:
            m.return_value = None
            result = get_doc(doc_id=999)
            data = json.loads(result)
            assert 'error' in data

    def test_get_req_trace_not_found(self):
        """不存在的需求应返回 error"""
        from src.experience_plane.docs.main import get_req_trace

        with patch('src.experience_plane.docs.main.get_requirement_trace', new_callable=AsyncMock) as m:
            m.return_value = None
            result = get_req_trace("REQ_NOTEXIST")
            data = json.loads(result)
            assert 'error' in data

    def test_doc_tools_class(self):
        """DocTools.get_tools() 应返回 5 个工具"""
        from src.experience_plane.docs.main import DocTools
        tools = DocTools().get_tools()
        assert len(tools) == 5
        tool_names = [t.name for t in tools]
        assert 'search_docs' in tool_names
        assert 'get_doc' in tool_names
        assert 'get_req_trace' in tool_names
        assert 'get_doc_tree' in tool_names
        assert 'list_doc_requirements' in tool_names


class TestRepositoryHelpers:
    """测试 repository 中的辅助函数"""

    def test_hash_content(self):
        from src.knowledge_plane.persistence.repository import _hash_content
        h = _hash_content("hello")
        assert len(h) == 64
        assert _hash_content("hello") == _hash_content("hello")
        assert _hash_content("hello") != _hash_content("world")

    def test_extract_requirements(self):
        from src.knowledge_plane.persistence.repository import _extract_requirements
        content = """
# UART TX 规格

## 功能描述

**REQ_UART_BT_001**: TX 模块应支持 5-8 位数据位配置
**REQ_UART_BT_002**: TX FIFO 深度 16 字节
**REQ_UART_UT_001**: 移位寄存器应在每个 baud tick 移出一位

普通文本不提取。
        """
        reqs = _extract_requirements(content)
        assert len(reqs) == 3
        assert reqs[0]['req_id'] == 'REQ_UART_BT_001'
        assert reqs[0]['req_type'] == 'BT'
        assert '数据位配置' in reqs[0]['description']
        assert reqs[2]['req_type'] == 'UT'

    def test_extract_requirements_chip(self):
        from src.knowledge_plane.persistence.repository import _extract_requirements
        content = "**REQ_CHIP_001**: 芯片级验证"
        reqs = _extract_requirements(content)
        assert len(reqs) == 1
        assert reqs[0]['req_type'] == 'CHIP'

    def test_extract_requirements_empty(self):
        from src.knowledge_plane.persistence.repository import _extract_requirements
        assert _extract_requirements("") == []
        assert _extract_requirements("没有需求ID的文档") == []

    def test_parse_dsa_spec(self):
        from src.knowledge_plane.persistence.repository import _parse_dsa_spec
        content = """
DSA SPEC
TITLE: ALU APB 寄存器接口规格
VERSION: 1.0
DESCRIPTION: APB 从接口，提供 ALU 操作数和运算类型的配置寄存器。
REQUIREMENTS:
  - ID: REQ_ALU_BT_007
    LEVEL: BT
    DESC: APB 寄存器接口验证 (读写/地址译码/错误响应)
  - ID: REQ_ALU_UT_001
    LEVEL: UT
    DESC: ALU 控制寄存器读写验证
INTERFACES:
  - NAME: ALU_CTRL
    TYPE: register
    OFFSET: 0x00
    WIDTH: 8
    ACCESS: RW
    DESC: 控制寄存器
"""
        spec = _parse_dsa_spec(content)
        assert spec['title'] == 'ALU APB 寄存器接口规格'
        assert spec['version'] == '1.0'
        assert spec['requirements'][0]['req_id'] == 'REQ_ALU_BT_007'
        assert spec['requirements'][0]['req_type'] == 'BT'
        assert spec['interfaces'][0]['name'] == 'ALU_CTRL'
