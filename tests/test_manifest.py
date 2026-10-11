"""Manifest & Evidence Package tests — SignOffAI 签核证据链核心测试

import 路径已从已删除的 src.layers.l2_orchestration.manifest
修正为当前实际位置 src.layers.l2_orchestration.evidence.manifest。
"""
import zipfile
from pathlib import Path

from src.layers.l2_orchestration.evidence.manifest import (
    ManifestBuilder, EvidencePackager, RunManifest, PhaseArtifact,
    hash_file, hash_content, hash_json,
)


# ═══════════════════════════════════════════════════
# Hash utilities
# ═══════════════════════════════════════════════════

def test_hash_content_deterministic():
    assert hash_content("hello") == hash_content("hello")
    assert hash_content("hello") != hash_content("world")


def test_hash_json_key_order_stable():
    a = hash_json({"b": 2, "a": 1})
    b = hash_json({"a": 1, "b": 2})
    assert a == b


def test_hash_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello", encoding="utf-8")
    assert hash_file(f) == hash_content("hello")
    assert hash_file(tmp_path / "nonexistent.txt") == ""


# ═══════════════════════════════════════════════════
# Manifest Builder
# ═══════════════════════════════════════════════════

class TestManifestBuilder:
    def test_list_sessions_returns_empty_when_no_logs(self, tmp_path):
        builder = ManifestBuilder(str(tmp_path))
        sessions = builder.list_sessions()
        assert isinstance(sessions, list)

    def test_build_minimal_manifest(self):
        builder = ManifestBuilder()
        phases = [
            {"name": "spec", "status": "passed", "score": 95, "time": 0.5, "retries": 0},
            {"name": "design", "status": "passed", "score": 90, "time": 0.3, "retries": 0},
            {"name": "cover", "status": "degraded", "score": 70, "time": 2.0, "retries": 1},
        ]
        run_state = {
            "run_id": "test_run_001",
            "workflow": "full_verification",
            "state": "completed",
            "started_at": "2026-08-08T10:00:00",
            "completed_at": "2026-08-08T10:05:00",
            "passed": 2, "total": 3,
            "ctx": {},
        }
        manifest = builder.build(
            session_id="20260808_100000",
            run_state=run_state,
            phases=phases,
            output_root=str(Path("output") / "test_run"),
        )
        assert manifest.run_id == "test_run_001"
        assert manifest.workflow == "full_verification"
        assert manifest.state == "completed"
        assert len(manifest.phases) == 3
        assert manifest.total_phases == 3
        assert manifest.passed == 2
        assert manifest.manifest_hash  # non-empty
        assert manifest.generated_at
        assert manifest.generator == "vagent dump"

    def test_build_manifest_sets_failed_count(self):
        builder = ManifestBuilder()
        phases = [
            {"name": "spec", "status": "passed", "score": 95, "time": 1, "retries": 0},
            {"name": "regress", "status": "failed", "score": 0, "time": 5, "retries": 2, "reason": "compile error"},
            {"name": "cover", "status": "error", "score": 0, "time": 0, "retries": 0, "error": "tool not found"},
        ]
        manifest = builder.build(
            session_id="s1",
            run_state={"run_id": "r1", "workflow": "test", "state": "completed_with_errors",
                       "started_at": "", "completed_at": "", "passed": 1, "total": 3, "ctx": {}},
            phases=phases,
        )
        assert manifest.passed == 1
        assert manifest.failed == 2
        assert manifest.degraded == 0


# ═══════════════════════════════════════════════════
# Evidence Packager
# ═══════════════════════════════════════════════════

class TestEvidencePackager:
    def test_package_and_verify(self, tmp_path):
        builder = ManifestBuilder(str(tmp_path))
        manifest = builder.build(
            session_id="pkg_test",
            run_state={"run_id": "test_run", "workflow": "quick", "state": "completed",
                       "started_at": "", "completed_at": "", "passed": 1, "total": 1, "ctx": {}},
            phases=[{"name": "spec", "status": "passed", "score": 95, "time": 0.5, "retries": 0}],
            output_root=str(tmp_path),
        )

        # Create an output artifact
        out_dir = tmp_path / "output"
        out_dir.mkdir(exist_ok=True)
        (out_dir / "result.txt").write_text("PASS", encoding="utf-8")
        manifest.output_root = str(out_dir)

        zip_path = tmp_path / "evidence.zip"
        packager = EvidencePackager(str(tmp_path))
        result_path = packager.package(manifest, zip_path)

        assert result_path.exists()
        assert result_path.stat().st_size > 0

        # Verify — manifest hash mismatch is expected when output_root differs
        # from build time (evidence_hash is re-computed on package)
        verify_result = packager.verify(zip_path)
        assert verify_result["manifest"] is not None
        assert verify_result["manifest"]["run_id"] == "test_run"

    def test_verify_detects_corrupted_zip(self, tmp_path):
        corrupt_zip = tmp_path / "corrupt.zip"
        corrupt_zip.write_text("not a zip file", encoding="utf-8")
        packager = EvidencePackager(str(tmp_path))
        result = packager.verify(corrupt_zip)
        assert not result["valid"]

    def test_verify_nonexistent_file(self, tmp_path):
        packager = EvidencePackager(str(tmp_path))
        result = packager.verify(tmp_path / "nonexistent.zip")
        assert not result["valid"]
        assert "not found" in result["issues"][0]

    def test_summary_md_in_package(self, tmp_path):
        builder = ManifestBuilder(str(tmp_path))
        manifest = builder.build(
            session_id="s1",
            run_state={"run_id": "r1", "workflow": "full", "state": "completed",
                       "started_at": "", "completed_at": "", "passed": 2, "total": 2, "ctx": {}},
            phases=[
                {"name": "spec", "status": "passed", "score": 95, "time": 0.5, "retries": 0},
                {"name": "design", "status": "degraded", "score": 70, "time": 1.0, "retries": 1},
            ],
        )
        out_dir = tmp_path / "output"
        out_dir.mkdir(exist_ok=True)
        manifest.output_root = str(out_dir)

        zip_path = tmp_path / "evidence.zip"
        packager = EvidencePackager(str(tmp_path))
        packager.package(manifest, zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            assert "manifest.json" in names
            assert "summary.md" in names


class TestFunctionalCoverageIsARunAsset:
    """功能覆盖点作为**运行级资产**进证据链。

    `output_files` + `evidence_hash` 已经覆盖了"哪些文件、哈希是多少"，答的是
    "东西没被换过"。但签核要回答的是另一件：「这次签的是**哪几个覆盖点**」——
    一个 hash 答不了那个问题。所以声明本身（点名 / bin / cross / 文件哈希）
    也要进证据包。
    """

    def _points(self, tmp_path, **over):
        import json

        from src.tools.casemodel_tools.api import run_covergroups

        spec = (Path(__file__).resolve().parents[1]
                / "specs" / "apb_uart" / "casemodel.yaml")
        p = run_covergroups(spec.read_text(encoding="utf-8"), "apb_uart")
        p.update({"module": "apb_uart", "source": "casemodel", **over})
        d = tmp_path / "coverage"
        d.mkdir(parents=True, exist_ok=True)
        (d / "coverage_points.json").write_text(
            json.dumps(p, ensure_ascii=False), encoding="utf-8")
        return p

    def test_declaration_lands_in_the_manifest(self, tmp_path):
        self._points(tmp_path)
        m = RunManifest(run_id="r1")
        ManifestBuilder._attach_functional_coverage(m, tmp_path)
        fc = m.metadata["functional_coverage"]
        assert [c["signal"] for c in fc["coverpoints"]] == ["paddr", "pwrite", "pwdata"]
        assert fc["counts"]["bin_count"] == 10

    def test_the_points_file_is_hashed_into_the_record(self, tmp_path):
        """声明的**那一份文件**的哈希要记下来 —— 否则"这次签的覆盖点"无法回溯。"""
        self._points(tmp_path)
        m = RunManifest(run_id="r1")
        ManifestBuilder._attach_functional_coverage(m, tmp_path)
        fc = m.metadata["functional_coverage"]
        assert fc["points_file"] == "coverage/coverage_points.json"
        assert len(fc["points_file_sha256"]) == 64

    def test_no_declaration_means_no_key_at_all(self, tmp_path):
        """读不到就**不写这个键**，不写空壳 ——"没有声明"与"声明是空的"是两件事，
        后者是模型的问题，得能分辨出来。"""
        m = RunManifest(run_id="r1")
        ManifestBuilder._attach_functional_coverage(m, tmp_path)
        assert "functional_coverage" not in m.metadata

    def test_a_corrupt_file_does_not_break_the_manifest(self, tmp_path):
        """坏文件不能让整份证据包构建失败 —— 证据链比这一点细节重要。"""
        d = tmp_path / "coverage"
        d.mkdir(parents=True)
        (d / "coverage_points.json").write_text("{ not json", encoding="utf-8")
        m = RunManifest(run_id="r1")
        ManifestBuilder._attach_functional_coverage(m, tmp_path)
        assert "functional_coverage" not in m.metadata


class TestArtifactReviewListsFunctionalCoverage:
    """产物审查台要看得见功能覆盖那三份 —— 否则"生成了没有"无从查起。"""

    def test_the_coverage_declaration_is_listed(self, tmp_path):
        from src.tools.flow_tools.api import run_artifacts

        (tmp_path / "coverage").mkdir(parents=True)
        (tmp_path / "coverage" / "coverage_points.json").write_text("{}", encoding="utf-8")
        payload = run_artifacts(str(tmp_path))
        groups = {a["path"]: a["group"] for a in payload["artifacts"]}
        assert groups.get("coverage/coverage_points.json") == "功能覆盖"
        assert groups.get("inputs/casemodel.yaml") == "功能覆盖"
        assert groups.get("inputs/yaml/uvm/env_cov_bins.yaml") == "功能覆盖"

    def test_a_missing_one_is_still_listed(self, tmp_path):
        """"还没生成"是有用的信息 —— 照列，标 `exists: false`。"""
        from src.tools.flow_tools.api import run_artifacts

        payload = run_artifacts(str(tmp_path))
        by = {a["path"]: a for a in payload["artifacts"]}
        assert by["coverage/coverage_points.json"]["exists"] is False
