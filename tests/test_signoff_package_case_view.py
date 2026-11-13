"""签核证据包：Case 证据（三集合）要进包，而且打包必须是**增量**的。

两件事一起钉：

1. **收录**：`case_ir / cell_matrix / evd / gates / case_view.* / case_cov/**`
   都是签核产出 —— 复查的人要能离线回答"这条用例证明了哪些组 / SVA / SB"。
2. **增量**：重跑 audit 时，源文件哈希没变的条目从上一版包**复用**（硬链接），
   只复制新增/变化的。两三百份 `case_cov` 不该每次全量重拷。
"""
from __future__ import annotations

import json
from pathlib import Path

from src.orchestration_plane.l2.evidence.signoff_package import (
    SECTION_FILES, verify_package, write_package,
)


def _write(path: Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _pkg(root: Path) -> dict:
    """最小 manifest：`verify_package` 要求有 verdict 段。"""
    return write_package(root, {"run": root.name, "artifacts": {},
                                "verdict": {"hard_ok": True, "verdict": "PASS"}})


def _run_dir(tmp_path: Path) -> Path:
    root = tmp_path / "run_pkg_20260101_000000"
    cov = root / "coverage"
    _write(cov / "case_ir.json", {"schema": "case_ir_v1", "cases": [{"id": "CASE-A"}]})
    _write(cov / "cell_matrix.json", {"schema": "cell_matrix_v1", "cells": []})
    _write(cov / "evd.json", {"schema": "evd_v1", "evd": []})
    _write(cov / "gates.json", {"schema": "case_gates_v1", "verdict": "PASS"})
    _write(cov / "case_view.json", {"schema": "case_associate_view_v2", "cases": []})
    (cov / "case_view.md").write_text("# case view\n", encoding="utf-8")
    _write(cov / "case_cov" / "p1" / "t1.json", {"case_id": "CASE-A"})
    _write(cov / "case_cov" / "p1" / "t2.json", {"case_id": "CASE-B"})
    return root


def _sources(manifest: dict, section: str = "case_view") -> set:
    return {f["source"] for f in manifest["files"] if f["section"] == section}


def test_case_view_artifacts_are_packaged(tmp_path):
    root = _run_dir(tmp_path)
    manifest = _pkg(root)
    sources = _sources(manifest)
    assert "coverage/case_ir.json" in sources
    assert "coverage/gates.json" in sources
    assert "coverage/case_view.md" in sources
    # `case_cov/**` 用通配展开（一条用例一份）
    assert "coverage/case_cov/p1/t1.json" in sources
    assert "coverage/case_cov/p1/t2.json" in sources
    pkg = root / "signoff_evidence"
    assert (pkg / "case_view" / "coverage" / "case_cov" / "p1" / "t1.json").is_file()
    # `SECTION_FILES` 与实现同源：这条断言是给"以后有人改常量"的
    assert "coverage/case_cov/**/*.json" in SECTION_FILES["case_view"]


def test_second_package_reuses_everything_unchanged(tmp_path):
    root = _run_dir(tmp_path)
    first = _pkg(root)
    assert first["incremental"]["copied"] > 0
    assert first["incremental"]["reused"] == 0

    second = _pkg(root)
    assert second["incremental"]["copied"] == 0, "源文件没变就该全部复用"
    assert second["incremental"]["reused"] == first["incremental"]["copied"]
    assert all(f.get("reused") for f in second["files"] if f.get("source"))


def test_only_the_changed_file_is_copied(tmp_path):
    root = _run_dir(tmp_path)
    _pkg(root)
    # 改一份 case_cov，其余不动
    _write(root / "coverage" / "case_cov" / "p1" / "t2.json",
           {"case_id": "CASE-B", "changed": True})

    manifest = _pkg(root)
    assert manifest["incremental"]["copied"] == 1
    changed = [f for f in manifest["files"]
               if f.get("source") == "coverage/case_cov/p1/t2.json"][0]
    assert changed["reused"] is False


def test_package_still_verifies_after_incremental_rebuild(tmp_path):
    root = _run_dir(tmp_path)
    _pkg(root)
    _pkg(root)
    result = verify_package(root / "signoff_evidence")
    assert result.get("ok"), result
