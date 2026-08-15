"""
CoverageBackend —— 覆盖率工具后端抽象（策略模式 / 适配器模式）。

隔离 EDA 工具差异，产出**统一的覆盖率数据结构**供分析层消费。分析层
（build_coverage_gaps / coverage_map / semanticize）只认统一格式，不认
任何具体工具的文本格式——这样切换 QuestaSim ↔ VCS 时，分析层零改动。

工具差异一览：
    ┌──────────┬───────────────────────┬─────────────────────┐
    │          │ QuestaSim             │ VCS                 │
    ├──────────┼───────────────────────┼─────────────────────┤
    │ 编译     │ vlog -cover sbceft    │ vcs -cm line+tgl+branch+fsm │
    │ 仿真     │ vsim -coverage        │ simv -cm ...        │
    │ 覆盖率库 │ .ucdb                 │ .vdb（simv.vdb）     │
    │ 报告     │ vcover report         │ urg -dir ... -format text │
    └──────────┴───────────────────────┴─────────────────────┘

统一覆盖率格式（COVERAGE_METRICS 展开 + 汇总字段）：
    {metric}_pct / {metric}_bins / {metric}_misses   (metric ∈ line/branch/toggle/fsm/statement/condition)
    overall_pct / functional_pct / functional_detail
    db_path（ucdb 或 vdb）/ report_dir / backend

用法:
    from src.core.coverage_backend import get_coverage_backend
    backend = get_coverage_backend()               # 默认 questa，可用 COVERAGE_BACKEND 环境变量切换
    result = backend.collect(output_dir, top_module, seed)
    cov = result["coverage"]                        # 统一格式
    toggles = backend.parse_toggle_details(output_dir)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

# 统一覆盖率指标（分析层消费的 metric 集合，QuestoSim/VCS 都映射到这 6 个）
COVERAGE_METRICS = ("line", "branch", "toggle", "fsm", "statement", "condition")


def empty_coverage() -> dict:
    """统一的空覆盖率结构（所有后端返回同一 schema）。"""
    cov = {}
    for m in COVERAGE_METRICS:
        cov[f"{m}_pct"] = 0.0
        cov[f"{m}_bins"] = 0
        cov[f"{m}_misses"] = 0
    cov["overall_pct"] = 0.0
    cov["functional_pct"] = 0.0
    cov["functional_detail"] = {}
    cov["db_path"] = ""
    cov["report_dir"] = ""
    cov["backend"] = ""
    return cov


class CoverageBackend(ABC):
    """覆盖率工具后端抽象基类。子类实现 QuestaSim / VCS 的具体命令链。"""

    name: str = "base"          # 后端标识（questa / vcs）
    db_extension: str = ""      # 覆盖率数据库扩展名（.ucdb / .vdb）

    @abstractmethod
    def collect(self, output_dir: Path, top_module: str = "", seed: int = 0) -> dict:
        """一站式收集：编译 + 仿真 + 解析覆盖率数据库。

        返回统一结构：
            {
              "status": "PASS" | "FAIL",
              "top_module": str,
              "compile": {...},       # 编译结果
              "simulation": {...},    # 仿真结果
              "coverage": {...},      # 统一覆盖率格式（empty_coverage 的填充版）
              "error": str,
            }
        """

    @abstractmethod
    def parse_toggle_details(self, output_dir: Path) -> list:
        """提取 signal 级 toggle 缺口（统一结构）。

        返回: [{"signal", "high", "low", "h_to_l", "l_to_h", "misses", "instance"}]
        """

    def get_db_path(self, output_dir: Path) -> Path:
        """覆盖率数据库路径（子类按 .ucdb/.vdb 差异返回）。"""
        return output_dir / "sim" / "coverage" / f"merged{self.db_extension}"

    def discover_top_module(self, output_dir: Path) -> str:
        """从 bench/*_tb_top.sv 推断 testbench 顶层模块名（工具无关）。"""
        try:
            bench = output_dir / "bench"
            if bench.exists():
                for sv in sorted(bench.glob("*_tb_top.sv")):
                    return sv.stem
        except Exception:
            pass
        return ""


class QuestaCoverageBackend(CoverageBackend):
    """QuestaSim 后端：vlog / vsim / vcover / .ucdb。

    复用 src.tools.lib.collect_real_coverage 的成熟实现（编译/仿真/报告/解析），
    不重写——只做接口适配。
    """

    name = "questa"
    db_extension = ".ucdb"

    def collect(self, output_dir: Path, top_module: str = "", seed: int = 0) -> dict:
        from src.tools.lib.collect_real_coverage import run as _questa_run
        return _questa_run(str(output_dir), top_module, seed)

    def parse_toggle_details(self, output_dir: Path) -> list:
        from src.tools.lib.collect_real_coverage import parse_toggle_details as _ptd
        return _ptd(output_dir)

    def get_db_path(self, output_dir: Path) -> Path:
        return output_dir / "sim" / "coverage" / "merged.ucdb"


class VcsCoverageBackend(CoverageBackend):
    """VCS 后端：vcs / simv / urg / .vdb（骨架，待实现）。

    VCS 覆盖率命令链（实现时按此填充）：
        1. 编译   vcs -cm line+tgl+branch+fsm -full64 -f filelist.f
                  （生成 simv + cm.log，等价 vlog -cover sbceft）
        2. 仿真   ./simv -cm line+tgl+branch+fsm -l sim.log +ntb_random_seed=<seed>
                  （生成 simv.vdb，等价 vsim -coverage）
        3. 报告   urg -dir simv.vdb -format text -report coverage_report
                  （生成 urgReport/，等价 vcover report -codeAll）
        4. 解析   从 urg 文本提取 metric 覆盖 → 映射到统一 COVERAGE_METRICS 格式
                  （等价 _parse_vcover_text，但 urg 输出格式不同，需新写 _parse_urg_text）
    """

    name = "vcs"
    db_extension = ".vdb"

    def collect(self, output_dir: Path, top_module: str = "", seed: int = 0) -> dict:
        # TODO(vcs): 实现 vcs 编译 + simv 仿真 + urg 报告 + _parse_urg_text 解析
        raise NotImplementedError(
            "VCS coverage backend 待实现：vcs/simv/urg/vdb 命令链 + urg 文本解析。"
            "见类 docstring 的命令链对照。")

    def parse_toggle_details(self, output_dir: Path) -> list:
        # TODO(vcs): urg -dir simv.vdb -format text 里解析 toggle 明细
        raise NotImplementedError("VCS toggle 明细待实现：解析 urg toggle 报告")

    def get_db_path(self, output_dir: Path) -> Path:
        return output_dir / "sim" / "coverage" / "simv.vdb"


# ── 后端工厂 ──

_BACKENDS = {
    "questa": QuestaCoverageBackend,
    "vcs": VcsCoverageBackend,
}


def get_coverage_backend(name: Optional[str] = None) -> CoverageBackend:
    """按名字选覆盖率后端（默认 questa，可用 COVERAGE_BACKEND 环境变量覆盖）。

    用法:
        backend = get_coverage_backend()               # 默认 questa
        backend = get_coverage_backend("vcs")          # 显式 VCS
        # 或设置环境变量 COVERAGE_BACKEND=vcs
    """
    name = name or os.environ.get("COVERAGE_BACKEND", "questa")
    name = name.lower().strip()
    if name not in _BACKENDS:
        raise ValueError(f"未知覆盖率后端: {name}（可用: {', '.join(_BACKENDS)}）")
    return _BACKENDS[name]()


def list_backends() -> list:
    """列出所有可用后端。"""
    return list(_BACKENDS.keys())
