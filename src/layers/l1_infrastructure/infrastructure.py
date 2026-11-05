"""
InfrastructureManager — L1 基础设施层：统一管理三大件。

三件套（文件系统 / Git 仓库 / 覆盖率数据库）的协同，是"可复现、可审计、可追溯"的根基：

  1. 文件系统
     - 工作区（output_root）：每次 run 的产物，可丢弃，git ignore
     - 归档区（.signoffai/）：覆盖率数据库归档 + 版本清单，持久
  2. Git 仓库
     - 源代码（RTL/TB 生成器）版本化，覆盖率达标时打 tag
     - 产物不进 git，但用哈希关联到 tag（version_manifest.json）
  3. 覆盖率数据库（.ucdb / .vdb）
     - 几十 GB 不进 git，归档到 .signoffai/coverage_archive/，用硬链接避免复制
     - 每轮记录 SHA256，复现时回滚比对；LLM 只读降采样后的 text 汇总

用法:
    from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
    infra = InfrastructureManager(output_root)
    infra.setup()
    ...
    infra.archive_coverage(round_num, ucdb_path)
    infra.write_version_manifest({...})
    infra.git_tag("v1.0", "coverage 95%")
    result = infra.verify_reproducible()
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

# 运行目录布局 —— **写端的落点也走契约**（`regression_run` 那一层叫什么、在哪）。
# 这里以前拼 `self.output_root / "regression_run"`，读端另拼一份，改一处漏一处。
from src.layers.l1_infrastructure import layout

logger = structlog.get_logger()



from .infra_helpers import (
    _strip_test_prefix_local,
    sha256_file,
    is_elab_failure_line,
    collect_hung_tests,
    classify_sim_failures,
    declared_tests_by_build,
    _stage_tests,
    logger,
)

from .regression_stage import RegressionStageMixin


class InfrastructureManager(RegressionStageMixin):
    """L1 基础设施层统一入口。"""

    def __init__(self, output_root: str | Path, repo_root: str | Path = None,
                 case_library=None):
        """`case_library` —— 回归结果回写的目标（L4 的 `TestcaseRegistry`）。

        为什么是**注入**的：本模块在 L1，而 `TestcaseRegistry` 在 L4。
        直接 import 就是 L1 反向依赖 L4 —— 反了的话 L1 没法脱离记忆层单独跑，
        而 L1 恰恰是最该能单独测的那一层。

        所以由调用方（L2 的 `hydrate_runtime`）传进来。**不传就不回写，
        并记一条 warning** —— 回归结果默默不落库，比报错难查得多。
        """
        self.output_root = Path(output_root)
        # 仓库根目录（git tag 打在这里，通常 = 项目根）
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self._case_library = case_library

        # 归档区（持久，不随 output 丢弃）
        self.meta_dir = self.output_root / ".signoffai"
        self.coverage_archive = self.meta_dir / "coverage_archive"
        self.rtl_archive = self.meta_dir / "rtl_archive"

    def setup(self) -> Dict[str, str]:
        """初始化标准目录布局，返回各目录路径。"""
        dirs = {
            "rtl": self.output_root / "rtl",
            "env": self.output_root / "env",
            "agents": self.output_root / "agents",
            "bench": self.output_root / "bench",
            "build": self.output_root / "build" / "work",
            "sim": self.output_root / "sim" / "coverage",
            "docs": self.output_root / "docs",
            "meta": self.meta_dir,
            "coverage_archive": self.coverage_archive,
            "rtl_archive": self.rtl_archive,
        }
        for d in dirs.values():
            d.mkdir(parents=True, exist_ok=True)
        return {k: str(v) for k, v in dirs.items()}

    def collect_coverage(self, round_num: int = 0, top_module: str = "",
                         seed: int = 0, backend=None) -> dict:
        """L1 统一入口：委托覆盖率后端做 EDA 收集 + 自动归档固化覆盖率数据库。

        把「编译仿真 + 报告解析 + 数据库归档」整合成 L1 的一个能力：
        - EDA 工具差异由 CoverageBackend（questa/vcs）隔离
        - 覆盖率数据库归档（硬链接 + SHA256 固化）是 L1 职责，收集后自动完成
        - 上层（run_closed_loop / CoverageCollectTool）统一走这里，不各自散落 subprocess

        返回 backend.collect() 的原始结果 + archive 归档信息。
        """
        from src.layers.l1_infrastructure.coverage_backend import get_coverage_backend
        backend = backend or get_coverage_backend()
        result = backend.collect(self.output_root, top_module, seed)
        result["backend"] = backend.name
        # 自动归档（L1 职责：覆盖率数据库版本固化，复现时回滚比对）
        db_path = (result.get("coverage", {}).get("db_path")
                   or result.get("coverage", {}).get("ucdb_path")
                   or result.get("db_path", ""))
        if db_path:
            try:
                result["archive"] = self.archive_coverage(round_num, db_path)
            except Exception as e:
                logger.warning(f"覆盖率数据库归档失败: {e}")
                result["archive"] = {"error": str(e)[:200]}
        return result

    def compile(self, filelist: str, coverage: bool = True, backend=None) -> dict:
        """L1 统一入口：委托 EDA 后端编译 RTL + UVM 环境（vlog/vcs）。"""
        from src.layers.l1_infrastructure.eda_backend import get_eda_backend
        backend = backend or get_eda_backend()
        return backend.compile(self.output_root, filelist, coverage)

    def simulate(self, top_module: str, uvm_test: str = "", seed: int = 0,
                 coverage: bool = True, backend=None) -> dict:
        """L1 统一入口：委托 EDA 后端仿真（vsim/simv）。"""
        from src.layers.l1_infrastructure.eda_backend import get_eda_backend
        backend = backend or get_eda_backend()
        return backend.simulate(self.output_root, top_module, uvm_test, seed, coverage)

    def archive_coverage(self, round_num: int, ucdb_path: str | Path) -> dict:
        """归档覆盖率数据库（硬链接，避免几十 GB 复制）+ 记录 SHA256。

        返回 {round, ucdb_path, sha256, size}。复现时用 sha256 比对。
        """
        ucdb = Path(ucdb_path)
        result = {"round": round_num, "ucdb_path": str(ucdb),
                  "sha256": "", "size": 0, "archived": False}

        if not ucdb.exists():
            return result

        result["sha256"] = self._sha256(ucdb)
        result["size"] = ucdb.stat().st_size

        dest = self.coverage_archive / f"round_{round_num:02d}{ucdb.suffix}"
        try:
            if not dest.exists():
                # 优先硬链接（零拷贝），跨文件系统则退化为复制
                try:
                    os.link(ucdb, dest)
                except OSError:
                    import shutil
                    shutil.copy2(ucdb, dest)
            result["archived"] = True
            result["archive_path"] = str(dest)
            # 哈希 + 元数据落盘（供复现比对）
            (self.coverage_archive / f"round_{round_num:02d}.sha256").write_text(
                result["sha256"], encoding="utf-8")
        except Exception as e:
            logger.warning(f"覆盖率数据库归档失败: {e}")
        return result

    def archive_rtl(self, round_num: int = 0) -> dict:
        """归档 RTL 代码哈希（不进 git 的产物用哈希固化）。"""
        rtl_dir = self.output_root / "rtl"
        result = {"files": {}, "aggregate": ""}
        if not rtl_dir.exists():
            return result
        for sv in sorted(rtl_dir.glob("*.sv")):
            result["files"][sv.name] = self._sha256(sv)[:16]
        sha = hashlib.sha256()
        for name in sorted(result["files"]):
            sha.update(name.encode())
            sha.update(result["files"][name].encode())
        result["aggregate"] = sha.hexdigest()
        return result

    def write_version_manifest(self, extra: Dict[str, Any] = None) -> str:
        """写版本清单（tag ↔ 覆盖率数据库哈希 ↔ RTL 哈希）。"""
        manifest = {
            "generated_at": datetime.now().isoformat(),
            "output_root": str(self.output_root),
            "repo_root": str(self.repo_root),
            **(extra or {}),
        }
        # 汇总归档的覆盖率数据库哈希
        coverage_entries = []
        for sha_file in sorted(self.coverage_archive.glob("round_*.sha256")):
            coverage_entries.append({
                "round": sha_file.stem.replace("round_", ""),
                "sha256": sha_file.read_text(encoding="utf-8").strip(),
            })
        manifest["coverage_archives"] = coverage_entries
        manifest["rtl"] = self.archive_rtl()

        path = self.meta_dir / "version_manifest.json"
        path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
        return str(path)

    def git_tag(self, tag_name: str, message: str = "") -> dict:
        """给源代码仓库打 git tag（产物不进 git，用哈希关联）。

        返回 {tagged, tag_name, commit, error}。失败不阻断（hash 固化仍是兜底）。
        """
        result = {"tagged": False, "tag_name": tag_name, "commit": "", "error": ""}
        try:
            if not (self.repo_root / ".git").exists():
                result["error"] = "not a git repository"
                return result
            # 记录当前 commit
            r = subprocess.run(["git", "-C", str(self.repo_root), "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=10)
            result["commit"] = r.stdout.strip()
            # 打 tag（轻量 tag，覆盖已存在的同名 tag）
            subprocess.run(["git", "-C", str(self.repo_root), "tag", "-f", tag_name],
                           capture_output=True, text=True, timeout=10)
            result["tagged"] = True
        except Exception as e:
            result["error"] = str(e)[:200]
        return result

    def verify_reproducible(self) -> dict:
        """复现校验：比对当前工作区的覆盖率数据库/RTL 与归档哈希是否一致。

        返回 {reproducible, mismatches}。
        """
        mismatches = []
        # 比对当前 merged.ucdb 与归档的 round_*.sha256
        current_ucdb = self.output_root / "sim" / "coverage" / "merged.ucdb"
        if current_ucdb.exists():
            current_hash = self._sha256(current_ucdb)
            for sha_file in sorted(self.coverage_archive.glob("round_*.sha256")):
                archived_hash = sha_file.read_text(encoding="utf-8").strip()
                if archived_hash == current_hash:
                    break
            else:
                mismatches.append({
                    "type": "coverage_db",
                    "detail": "current merged.ucdb hash 与任何归档都不一致",
                })
        # 比对 RTL
        rtl_dir = self.output_root / "rtl"
        if rtl_dir.exists():
            current_rtl = self.archive_rtl()
            manifest_path = self.meta_dir / "version_manifest.json"
            if manifest_path.exists():
                try:
                    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
                    saved_rtl = saved.get("rtl", {}).get("files", {})
                    if saved_rtl and saved_rtl != current_rtl.get("files", {}):
                        mismatches.append({"type": "rtl", "detail": "RTL 文件哈希与版本清单不一致"})
                except Exception:
                    pass
        return {"reproducible": not mismatches, "mismatches": mismatches}

