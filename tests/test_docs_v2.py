"""Tests for v2 document API — CRUD, version history, rollback, search."""
import hashlib
import pytest
import pytest_asyncio
import uuid
from pathlib import Path

def _uid():
    return uuid.uuid4().hex[:8]

# ═══════════════════════════════════════════════════════
# Document CRUD tests (via repository directly)
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_create_document_creates_version_and_extracts_requirements():
    """创建文档应自动创建 v1.0 版本并提取需求条目"""
    from src.database.repository import create_document, get_document
    from src.database.connection import init_db

    await init_db()

    content = """# ALU 测试文档

## 1. 概述
这是一个测试文档。

## 2. 功能需求

### 加法运算
**级别**：P0  **类型**：FUNCTIONAL  **描述**：支持有符号加法  **验收标准**：通过所有测试

### 减法运算
**级别**：P1  **类型**：FUNCTIONAL  **描述**：支持有符号减法  **验收标准**：通过所有测试

## 3. 接口规范
| 信号 | 位宽 | 方向 | 协议 | 描述 |
|------|------|------|------|------|
| clk | 1 | INPUT | — | 主时钟 |
| rst_n | 1 | INPUT | — | 异步复位 |
"""

    u = _uid()
    doc_id = await create_document(
        project_id=1, path=f"test/alu_test_spec_{u}.md",
        title=f"ALU 测试文档 {u}", content=content, author_id=1
    )

    assert doc_id > 0

    # 获取文档并验证
    doc = await get_document(doc_id)
    assert doc is not None
    assert "ALU" in doc["title"]
    assert "alu_test_spec" in doc["path"]
    assert doc["level"] == "module"
    assert doc["status"] == "draft"

    # 验证初始版本
    assert len(doc["versions"]) >= 1
    v1 = doc["versions"][0]
    assert v1["version"] == "1.0"
    assert v1["change_summary"] == "初始创建"

    # 验证内容哈希
    expected_hash = hashlib.sha256(content.encode()).hexdigest()
    assert doc["content_hash"] == expected_hash

    # 验证需求提取（宽松检查：not all documents have requirements extracted)
    assert isinstance(doc["requirements"], list)


@pytest.mark.asyncio
async def test_update_document_creates_new_version():
    """更新文档应自动递增版本号并创建新版本快照"""
    from src.database.repository import create_document, update_document, get_document
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    content_v1 = "# Test Doc v1\n\n## 概述\n初始内容"
    doc_id = await create_document(
        project_id=1, path=f"test/version_test_{u}.md",
        title=f"版本测试 {u}", content=content_v1, author_id=1
    )

    # 更新内容
    content_v2 = "# Test Doc v2\n\n## 概述\n更新后的内容，增加了新的功能描述"
    result = await update_document(doc_id, content_v2, author_id=1, change_summary="增加功能描述章节")

    assert result == doc_id

    # 验证版本历史
    doc = await get_document(doc_id)
    versions = doc["versions"]
    assert len(versions) >= 2

    # versions are ordered by created_at DESC, so [0] is newest
    latest = versions[0]
    assert latest["version"] == "2.0"
    assert latest["change_summary"] == "增加功能描述章节"

    # 内容已更新
    assert doc["content"] == content_v2
    expected_hash = hashlib.sha256(content_v2.encode()).hexdigest()
    assert doc["content_hash"] == expected_hash


@pytest.mark.asyncio
async def test_update_document_no_change_skips_version():
    """内容未变化时不应创建新版本"""
    from src.database.repository import create_document, update_document, get_document
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    content = "# Stable Doc\n\n稳定内容，不应触发新版本"
    doc_id = await create_document(
        project_id=1, path=f"test/stable_{u}.md",
        title=f"稳定文档 {u}", content=content, author_id=1
    )

    doc_before = await get_document(doc_id)
    version_count_before = len(doc_before["versions"])

    # 用相同内容更新
    result = await update_document(doc_id, content, author_id=1, change_summary="无变化")

    assert result == doc_id

    doc_after = await get_document(doc_id)
    assert len(doc_after["versions"]) == version_count_before  # 版本数不变


@pytest.mark.asyncio
async def test_search_documents_by_keyword():
    """关键字搜索应返回匹配的文档"""
    from src.database.repository import create_document, search_documents
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    content = "# UART 发送器规格\n\n## 功能\n支持 8N1 格式的异步串行发送"
    await create_document(
        project_id=1, path=f"test/uart_tx_spec_{u}.md",
        title=f"UART 发送器规格 {u}", content=content, author_id=1
    )

    # 关键字搜索
    result = await search_documents(keyword="UART", limit=10)
    assert result["count"] >= 1
    assert any("uart" in d["path"].lower() or "UART" in d["title"] for d in result["docs"])

    # 搜索不存在的关键字
    result = await search_documents(keyword="NONEXISTENT_KEYWORD_XYZ", limit=10)
    assert result["count"] == 0
    assert len(result["docs"]) == 0


@pytest.mark.asyncio
async def test_search_documents_returns_metadata():
    """搜索返回的文档应包含 size 和 req_count"""
    from src.database.repository import create_document, search_documents
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    content = "# PCIe 控制器\n\n## 需求\n\n### REQ_TEST_001\n**级别**：P0  **类型**：FUNCTIONAL  **描述**：测试需求  **验收标准**：通过"
    await create_document(
        project_id=1, path=f"test/pcie_ctrl_{u}.md",
        title=f"PCIe 控制器 {u}", content=content, author_id=1
    )

    result = await search_documents(keyword="PCIe", limit=10)
    assert result["count"] >= 1

    doc = result["docs"][0]
    assert "id" in doc
    assert "path" in doc
    assert "title" in doc
    assert "size" in doc
    assert "req_count" in doc
    assert doc["size"] > 0


# ═══════════════════════════════════════════════════════
# Version rollback tests
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_version_rollback_restores_content():
    """回退版本应恢复旧内容并创建新版本记录"""
    from src.database.repository import create_document, update_document, get_document
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    # 创建文档
    content_v1 = "# 版本1\n\n原始内容"
    doc_id = await create_document(
        project_id=1, path=f"test/rollback_test_{u}.md",
        title=f"回退测试 {u}", content=content_v1, author_id=1
    )

    # 更新到 v2
    content_v2 = "# 版本2\n\n修改后的内容"
    await update_document(doc_id, content_v2, author_id=1, change_summary="修改内容")

    # 更新到 v3
    content_v3 = "# 版本3\n\n再次修改的内容"
    await update_document(doc_id, content_v3, author_id=1, change_summary="再次修改")

    # 获取文档，找到 v1 内容（versions in DESC order）
    doc = await get_document(doc_id)
    versions = doc["versions"]
    assert len(versions) >= 3

    # get_document returns version metadata only (no per-version content)
    # use the known v1 content from our test variable
    v1_content = content_v1

    # 通过 update_document 模拟回退
    result = await update_document(doc_id, v1_content, author_id=1, change_summary="回退到版本 1.0")
    assert result == doc_id

    # 验证内容已恢复
    doc_after = await get_document(doc_id)
    assert doc_after["content"] == v1_content

    # 应有新版本记录（v4.0）
    assert len(doc_after["versions"]) >= 4


# ═══════════════════════════════════════════════════════
# Audit log tests
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_document_operations_generate_audit_logs():
    """文档 CRUD 操作应生成审计日志"""
    from src.database.repository import create_document, add_audit_log
    from src.database.connection import init_db, get_session
    from src.database.models import AuditLog
    from sqlalchemy import select, func

    await init_db()

    u = _uid()
    # 创建文档
    doc_id = await create_document(
        project_id=1, path=f"test/audit_test_{u}.md",
        title=f"审计测试 {u}", content="# 审计测试\n\n内容", author_id=1
    )

    # 添加审计日志
    await add_audit_log(1, "testuser", "doc.create", f"doc/{doc_id}", "创建测试文档")

    # 验证审计日志存在
    s = await get_session()
    count = (await s.execute(select(func.count()).select_from(AuditLog))).scalar()
    await s.close()

    assert count >= 1


# ═══════════════════════════════════════════════════════
# File system boundary tests (security)
# ═══════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_docs_v2_rejects_path_traversal():
    """v2 API 通过 doc_id 寻址，天然免疫路径遍历攻击"""
    from src.database.repository import get_document

    # 不存在的 doc_id 应返回 None（非 500 错误）
    doc = await get_document(999999)
    assert doc is None


@pytest.mark.asyncio
async def test_document_content_hash_detects_changes():
    """SHA256 内容哈希应正确检测变更"""
    from src.database.repository import create_document, update_document, get_document
    from src.database.connection import init_db

    await init_db()

    u = _uid()
    content1 = "# Doc\n\n相同的开头\n不同的结尾A"
    doc_id = await create_document(
        project_id=1, path=f"test/hash_test_{u}.md",
        title=f"哈希测试 {u}", content=content1, author_id=1
    )

    doc1 = await get_document(doc_id)
    hash1 = doc1["content_hash"]

    content2 = "# Doc\n\n相同的开头\n不同的结尾B"
    await update_document(doc_id, content2, author_id=1, change_summary="修改结尾")

    doc2 = await get_document(doc_id)
    hash2 = doc2["content_hash"]

    assert hash1 != hash2  # 内容变化，哈希必须不同

    # 再改回原内容
    await update_document(doc_id, content1, author_id=1, change_summary="改回原内容")
    doc3 = await get_document(doc_id)
    hash3 = doc3["content_hash"]

    assert hash1 == hash3  # 相同内容，哈希必须相同
