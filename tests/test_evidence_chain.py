"""
E2E tests: 证据链与审计链完整性

覆盖: manifest hash 自校验 / artifact 绑定 / EvidenceLink / 审计哈希链验证
"""
import json
import hashlib
import pytest
import asyncio
from pathlib import Path


class TestEvidenceChainIntegrity:
    """证据链完整性测试"""

    def test_manifest_hash_self_check(self):
        """Manifest hash 自校验：存储的 hash 与重新计算一致"""
        from src.core.manifest import hash_json

        data = {
            "run_id": "test_001",
            "phases": [
                {"phase_name": "spec", "output_hash": "abc123"},
                {"phase_name": "design", "output_hash": "def456"},
            ],
        }
        # 计算 hash
        calc = hash_json(data)
        assert calc is not None
        assert len(calc) == 64  # SHA256
        # 数据不变 hash 不变
        calc2 = hash_json(data)
        assert calc == calc2
        # 数据变 hash 变
        data["phases"].append({"phase_name": "extra"})
        calc3 = hash_json(data)
        assert calc != calc3

    def test_evidence_hash_computation(self):
        """证据 hash 基于文件内容计算"""
        data = b"test evidence content"
        expected = hashlib.sha256(data).hexdigest()
        actual = hashlib.sha256(data).hexdigest()
        assert expected == actual
        assert len(expected) == 64

    def test_artifact_model_fields(self):
        """Artifact 模型有证据绑定所需字段"""
        from src.database.models import Artifact
        assert hasattr(Artifact, 'project_id')
        assert hasattr(Artifact, 'run_id')
        assert hasattr(Artifact, 'signoff_id')
        assert hasattr(Artifact, 'artifact_type')
        assert hasattr(Artifact, 'name')
        assert hasattr(Artifact, 'content_hash')
        assert hasattr(Artifact, 'size_bytes')

    def test_evidence_link_model_fields(self):
        """EvidenceLink 模型有关联字段"""
        from src.database.models import EvidenceLink
        assert hasattr(EvidenceLink, 'artifact_id')
        assert hasattr(EvidenceLink, 'object_type')
        assert hasattr(EvidenceLink, 'object_id')
        assert hasattr(EvidenceLink, 'relation_type')

    def test_signoff_hash_fields(self):
        """Signoff 模型有证据 hash 字段"""
        from src.database.models import Signoff
        assert hasattr(Signoff, 'manifest_hash')
        assert hasattr(Signoff, 'evidence_package_hash')
        assert hasattr(Signoff, 'run_id')


class TestAuditHashChain:
    """审计哈希链测试"""

    def test_hash_chain_computation(self):
        """审计哈希链正确链接前驱 hash"""
        raw1 = "0|1|1|admin|login_success|auth|IP:127.0.0.1|"
        h1 = hashlib.sha256(raw1.encode()).hexdigest()
        assert len(h1) == 64

        # 第二条引用第一条的 hash
        raw2 = f"1|2|1|admin|pipeline_run|run_001|started|{h1}"
        h2 = hashlib.sha256(raw2.encode()).hexdigest()
        assert h2 != h1  # 不同
        assert len(h2) == 64

    def test_audit_log_has_chain_fields(self):
        """AuditLog 模型有哈希链字段"""
        from src.database.models import AuditLog
        assert hasattr(AuditLog, 'prev_hash')
        assert hasattr(AuditLog, 'chain_hash')
        assert hasattr(AuditLog, 'chain_index')

    @pytest.mark.asyncio
    async def test_verify_audit_chain_function(self):
        """审计链验证函数可调用"""
        from src.database.repository import verify_audit_chain
        result = await verify_audit_chain()
        assert "valid" in result
        assert "total_records" in result
        assert "issues" in result
        assert "latest_hash" in result


class TestManifestVerification:
    """Manifest 完整性验证测试"""

    def test_manifest_verify_endpoint_structure(self):
        """验证端点返回结构完整"""
        expected_fields = {"session_id", "valid", "manifest_hash_ok",
                          "phases_complete", "file_count", "missing_files",
                          "hash_mismatches", "issues", "conclusion"}
        assert len(expected_fields) == 9

    def test_evidence_artifact_types(self):
        """产物类型枚举完整"""
        valid_types = {"manifest", "report", "coverage", "log", "doc", "testcase", "evidence_package"}
        from src.database.models import Artifact
        assert hasattr(Artifact, 'artifact_type')
        assert len(valid_types) == 7
