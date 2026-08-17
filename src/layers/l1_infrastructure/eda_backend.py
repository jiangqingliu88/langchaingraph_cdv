"""
EdaBackend —— EDA 编译仿真后端抽象（策略模式 / 适配器模式）。

与 CoverageBackend 对称：隔离 EDA 工具差异（QuestaSim vlog/vsim vs VCS vcs/simv），
统一编译仿真调用。上层（ops agent / L1 InfrastructureManager）只认统一接口，
不散落 subprocess、不硬编码 QuestaSim。

工具差异：
    ┌───────┬───────────────────────┬──────────────────────┐
    │       │ QuestaSim             │ VCS                  │
    ├───────┼───────────────────────┼──────────────────────┤
    │ 编译  │ vlog -work ... -cover │ vcs -cm ... -f ...   │
    │ 仿真  │ vsim -coverage ...    │ simv -cm ...         │
    └───────┴───────────────────────┴──────────────────────┘

用法:
    from src.layers.l1_infrastructure.eda_backend import get_eda_backend
    backend = get_eda_backend()                 # 默认 questa，可用 EDA_BACKEND 环境变量切换
    result = backend.compile(output_dir, filelist, coverage=True)
    result = backend.simulate(output_dir, top_module, uvm_test, seed=0, coverage=True)
"""
from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class EdaBackend(ABC):
    """EDA 编译仿真后端抽象基类。子类实现 QuestaSim / VCS 的具体命令链。"""

    name: str = "base"          # 后端标识（questa / vcs）

    @abstractmethod
    def compile(self, output_dir: Path, filelist: str,
                coverage: bool = True) -> dict:
        """编译 RTL + UVM 环境（vlog / vcs）。

        返回 {status, errors, stderr, stdout}。
        """

    @abstractmethod
    def simulate(self, output_dir: Path, top_module: str,
                 uvm_test: str = "", seed: int = 0,
                 coverage: bool = True) -> dict:
        """仿真（vsim / simv）。

        返回 {status, errors, ...}。
        """


class QuestaEdaBackend(EdaBackend):
    """QuestaSim 后端：vlog / vsim。

    编译委托 RegressionRunner（成熟的 vlog 编译链：UVM 库路径 + -cover），
    仿真委托 collect_real_coverage.simulate_with_coverage（vsim + merged.ucdb + seed）。
    """

    name = "questa"

    def compile(self, output_dir: Path, filelist: str,
                coverage: bool = True) -> dict:
        from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
        runner = RegressionRunner(
            env_output_dir=str(output_dir), filelist=str(filelist), coverage=coverage)
        return runner.compile()

    def simulate(self, output_dir: Path, top_module: str,
                 uvm_test: str = "", seed: int = 0,
                 coverage: bool = True) -> dict:
        if coverage:
            # 收集覆盖率：vsim -coverage → merged.ucdb
            from src.tools.lib.collect_real_coverage import simulate_with_coverage
            return simulate_with_coverage(output_dir, top_module, uvm_test, seed)
        # 不收集覆盖率的纯功能回归：vsim 不带 -coverage，检查 UVM 测试 pass/fail
        from src.tools.regression_tools.regression_framwork.src.regression_framework.adapters.regression_runner import RegressionRunner
        runner = RegressionRunner(
            env_output_dir=str(output_dir), top_module=top_module, coverage=False)
        return runner.collect_coverage(uvm_test=uvm_test)


class VcsEdaBackend(EdaBackend):
    """VCS 后端：vcs / simv（骨架，待实现）。

    VCS 命令链（实现时按此填充）：
        1. 编译  vcs -sverilog -cm line+tgl+branch+fsm -full64 -f filelist.f
                （等价 vlog -cover sbceft，生成 simv + cm.log）
        2. 仿真  ./simv -cm line+tgl+branch+fsm -l sim.log +ntb_random_seed=<seed>
                （等价 vsim -coverage，生成 simv.vdb）
    """

    name = "vcs"

    def compile(self, output_dir: Path, filelist: str,
                coverage: bool = True) -> dict:
        # TODO(vcs): vcs -cm line+tgl+branch+fsm -full64 -f filelist.f
        raise NotImplementedError("VCS 编译待实现：vcs/simv 命令链，见类 docstring")

    def simulate(self, output_dir: Path, top_module: str,
                 uvm_test: str = "", seed: int = 0,
                 coverage: bool = True) -> dict:
        # TODO(vcs): ./simv -cm ... +ntb_random_seed=<seed>
        raise NotImplementedError("VCS 仿真待实现：simv 命令链，见类 docstring")


# ── 后端工厂 ──

_BACKENDS = {
    "questa": QuestaEdaBackend,
    "vcs": VcsEdaBackend,
}


def get_eda_backend(name: Optional[str] = None) -> EdaBackend:
    """按名字选 EDA 编译仿真后端（默认 questa，可用 EDA_BACKEND 环境变量覆盖）。"""
    name = name or os.environ.get("EDA_BACKEND", "questa")
    name = name.lower().strip()
    if name not in _BACKENDS:
        raise ValueError(f"未知 EDA 后端: {name}（可用: {', '.join(_BACKENDS)}）")
    return _BACKENDS[name]()


def list_eda_backends() -> list:
    return list(_BACKENDS.keys())
