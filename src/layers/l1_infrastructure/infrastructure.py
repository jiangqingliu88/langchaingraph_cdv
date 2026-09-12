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

logger = structlog.get_logger()


def sha256_file(path: str | Path, chunk_size: int = 65536) -> str:
    """分块计算文件 SHA256 —— 覆盖率数据库的唯一哈希实现。

    ucdb 动辄几十 GB，整文件 read_bytes() 会直接打爆内存。铁律二（覆盖率
    数据库版本固化）与此处共用同一份实现，避免再出现「一份分块、一份整读」
    的两套哈希。
    """
    p = Path(path)
    if not p.exists():
        return ""
    sha = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            sha.update(chunk)
    return sha.hexdigest()


class InfrastructureManager:
    """L1 基础设施层统一入口。"""

    def __init__(self, output_root: str | Path, repo_root: str | Path = None):
        self.output_root = Path(output_root)
        # 仓库根目录（git tag 打在这里，通常 = 项目根）
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()

        # 归档区（持久，不随 output 丢弃）
        self.meta_dir = self.output_root / ".signoffai"
        self.coverage_archive = self.meta_dir / "coverage_archive"
        self.rtl_archive = self.meta_dir / "rtl_archive"

    # ═══════════════════════════════════════════════════════════════
    # 文件系统：目录布局
    # ═══════════════════════════════════════════════════════════════

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

    # ═══════════════════════════════════════════════════════════════
    # 覆盖率数据库：归档 + 哈希固化
    # ═══════════════════════════════════════════════════════════════

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

    def run_regression(self, reg_yaml: str = None, mode: str = "local",
                       tests: str = None) -> dict:
        """L1 统一入口：吃 regression.yaml 批量跑回归 case（通过回归框架）。

        回归框架（regression_framwork）是成熟的执行器：ConfigBuilder 解析 yaml
        → ShellGenerator 生成脚本 → Scheduler 批量跑 build + test（每个 test 一个 case）。
        这里是 L1 对它的统一封装——上层（RegressionRunTool / ops agent）走这里，
        不各自散落调用回归框架。

        返回 {status, passed, failed, unknown, total, report_path}。
        """
        reg_yaml = reg_yaml or str(self.output_root / "inputs" / "yaml" / "regression.yaml")
        if not Path(reg_yaml).exists():
            return {"status": "FAIL", "error": f"regression.yaml not found: {reg_yaml}"}

        try:
            # ── 0. 生成完整 filelist（UVM 环境此时已由 jinja_render 生成）──
            # regression.yaml 的 compile 命令引用 filelist.f，但 find_spec_yaml 生成
            # regression.yaml 时 agents/env/bench 尚未生成，故这里重新生成完整 filelist。
            try:
                from src.tools.lib.filelist import build_filelist_for_tb
                env_name = "dut_env"
                for p in sorted((self.output_root / "env").glob("*_pkg.sv")):
                    env_name = p.name.replace("_pkg.sv", "")
                    break
                agents = []
                agents_dir = self.output_root / "agents"
                if agents_dir.exists():
                    agents = [{"name": d.name} for d in agents_dir.iterdir() if d.is_dir()]
                build_filelist_for_tb(self.output_root, agents, env_name, "filelist.f")
                # loopback filelist：每个 agent 一个 filelist_<ag>_lb.f，供 per-agent loopback build 编译
                try:
                    from src.tools.lib.filelist import build_loopback_filelist
                    for ag in agents:
                        build_loopback_filelist(self.output_root, ag["name"])
                except Exception as _lb_e:
                    logger.warning(f"loopback filelist 生成失败: {_lb_e}")
            except Exception as e:
                logger.warning(f"filelist 生成失败: {e}")

            # ── 1. ConfigBuilder 解析 regression.yaml（builds + tests）──
            from src.tools.regression_tools.regression_framwork.src.regression_framework.core.config import ConfigBuilder
            builder = ConfigBuilder(reg_yaml)
            config = builder.build()

            # ── 2. ShellGenerator 生成 build_*/test_* 目录 + 脚本 ──
            from src.tools.regression_tools.regression_framwork.src.regression_framework.generators.shell import ShellGenerator
            root_dir = str(self.output_root / "regression_run")
            # 清理上一次回归残留（state_file 会导致断点续跑跳过所有已完成任务）
            import shutil as _shutil
            if os.path.isdir(root_dir):
                _shutil.rmtree(root_dir, ignore_errors=True)
            ShellGenerator().generate(config, root_dir, mode)

            # ── 3. Scheduler 批量跑 build + test（扫描生成目录）──
            from src.tools.regression_tools.regression_framwork.src.regression_framework.models.scheduler import Scheduler
            from src.tools.regression_tools.regression_framwork.src.regression_framework.execution.strategy import LocalStrategy, MockStrategy
            from src.tools.regression_tools.regression_framwork.src.regression_framework.models.task import TaskFactory
            import re as _re

            strategy = LocalStrategy() if mode == "local" else MockStrategy()
            # 不传 state_file：每次回归全新跑（不跨 run 续跑，避免第二轮跳过所有任务）
            scheduler = Scheduler(strategy)
            test_patterns = [_re.compile(p.strip()) for p in tests.split(",")] if tests else None

            build_dirs = sorted([d for d in os.listdir(root_dir)
                                 if d.startswith("build_") and os.path.isdir(os.path.join(root_dir, d))])
            added_builds = set()
            total_tests = 0
            for build_dir in build_dirs:
                build_path = os.path.join(root_dir, build_dir)
                build_name = build_dir.replace("build_", "")
                test_dirs = sorted([d for d in os.listdir(build_path)
                                    if d.startswith("test_") and os.path.isdir(os.path.join(build_path, d))])
                for test_dir in test_dirs:
                    test_name = test_dir.replace("test_", "")
                    if test_patterns and not any(p.search(test_name) for p in test_patterns):
                        continue
                    if build_name not in added_builds:
                        scheduler.add_task(TaskFactory.create_build_task(build_name, build_path))
                        added_builds.add(build_name)
                    scheduler.add_task(TaskFactory.create_test_task(
                        test_name, os.path.join(build_path, test_dir), build_name))
                    total_tests += 1

            scheduler.run(root_dir)

            # ── 4. 读 report_summary.txt ──
            report_path = os.path.join(root_dir, "report_summary.txt")
            report_text = ""
            passed = failed = unknown = 0
            if os.path.exists(report_path):
                report_text = Path(report_path).read_text(encoding="utf-8", errors="replace")
                for line in report_text.splitlines():
                    if line.startswith("Pass:"):
                        passed = int(line.split(":")[1].strip())
                    elif line.startswith("Fail:"):
                        failed = int(line.split(":")[1].strip())
                    elif line.startswith("Unknown:"):
                        unknown = int(line.split(":")[1].strip())

            # ── case 库回写：回归结果 → 更新用例状态（planned → passed/failed）──
            # case 库跨 run 共享，在项目根 .signoffai/（而非 run 目录）
            try:
                from src.layers.l4_memory.testcase_registry import TestcaseRegistry
                case_reg = TestcaseRegistry()
                import re as _re
                for line in report_text.splitlines():
                    m = _re.match(r"(pass|fail|unknown)\s*:\s*(\S+)", line.strip())
                    if not m:
                        continue
                    st, tname = m.group(1), m.group(2)
                    # task.name 丢了 test_ 前缀（Scheduler 用 replace 去掉了），补回以匹配 case 库用例名
                    cname = tname if tname.startswith("test_") else f"test_{tname}"
                    if st == "pass":
                        case_reg.update_status(cname, "passed", result={"new_coverage": 0})
                    elif st == "fail":
                        case_reg.update_status(cname, "failed")
                case_reg.close()
            except Exception as _e:
                logger.warning(f"case 库回写失败: {_e}")

            # ── 5. elaboration/load 失败检测：vopt 多驱动等错误在 test 任务 load 阶段失败 ──
            # 这类是「编译级」失败（RTL 有问题），不是「测试」失败——必须标记 compile=FAIL，
            # 让上层 execution.py 路由到 COMPILE_RETRY（CompileSelfHealer），而非 RETRY_ENV。
            compile_fail = ""
            try:
                _elab_errs = []
                for _bd in os.listdir(root_dir):
                    _bp = os.path.join(root_dir, _bd)
                    if not _bd.startswith("build_") or not os.path.isdir(_bp):
                        continue
                    for _td in os.listdir(_bp):
                        _tp = os.path.join(_bp, _td)
                        if not _td.startswith("test_") or not os.path.isdir(_tp):
                            continue
                        _sim_log = os.path.join(_tp, "sim.log")
                        if not os.path.exists(_sim_log):
                            continue
                        _txt = Path(_sim_log).read_text(encoding="utf-8", errors="replace")
                        if not _re.search(r"vopt-|Error loading design|Error \(suppressible\)", _txt):
                            continue
                        for _ln in _txt.splitlines():
                            if _re.search(r"vopt-|Error loading design|Error \(suppressible\)|Errors:", _ln):
                                _elab_errs.append(_ln.strip())
                if _elab_errs:
                    compile_fail = "\n".join(_elab_errs[:40])
            except Exception as _e:
                logger.warning(f"elaboration 失败检测失败: {_e}")

            result = {
                "status": "PASS" if failed == 0 and passed > 0 else "FAIL",
                "passed": passed,
                "failed": failed,
                "unknown": unknown,
                "total": passed + failed + unknown,
                "total_tests": total_tests,
                "root_dir": root_dir,
                "report_path": report_path,
                "report": report_text[-2000:],
            }
            if compile_fail:
                result["compile"] = "FAIL"
                result["stderr"] = compile_fail
                result["elaboration_failed"] = True
            return result
        except Exception as e:
            logger.warning(f"回归执行失败: {e}")
            return {"status": "FAIL", "error": str(e)[:500]}

    @staticmethod
    def _sha256(path: Path) -> str:
        return sha256_file(path)

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

    # ═══════════════════════════════════════════════════════════════
    # 版本清单：tag ↔ 产物哈希 关联
    # ═══════════════════════════════════════════════════════════════

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

    # ═══════════════════════════════════════════════════════════════
    # Git 仓库：版本 tag
    # ═══════════════════════════════════════════════════════════════

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

    # ═══════════════════════════════════════════════════════════════
    # 复现：哈希比对
    # ═══════════════════════════════════════════════════════════════

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
