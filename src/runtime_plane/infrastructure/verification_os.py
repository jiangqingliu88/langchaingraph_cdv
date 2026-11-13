"""
VerificationOS —— L1 执行机器统一门面（「AI 驱动验证基础设施」的 L1 落地）

L1 是「执行机器 / 手脚」，不是 AI。它提供五个语义化 Manager：

    CompileManager    compile(filelist)           → vlog/vcs 编译
    RegressionManager run_regression(reg_yaml)    → 批量跑 case（10000 testcase）
    EdaScheduler      simulate(top, uvm_test)     → 单 case 仿真
    CoverageCollector collect_coverage(round)     → 覆盖率收集 + 归档固化
    WaveManager       collect_waveform(top)       → 波形收集

统一委托给底层 InfrastructureManager（文件系统/Git/覆盖率DB）+ EdaBackend + CoverageBackend。
上层（run_closed_loop / ops / coverage agent）只跟 VerificationOS 打交道，
不再各自散落 subprocess / 回归框架调用 —— 这是「L1 是执行机器」的单一入口。

用法:
    from src.runtime_plane.infrastructure.verification_os import VerificationOS
    vos = VerificationOS("output/run_xxx")
    vos.setup()
    vos.compile("inputs/filelists/filelist.f")
    vos.run_regression("inputs/yaml/regression.yaml")
    cov = vos.collect_coverage(round_num=1)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from src.runtime_plane.infrastructure.infrastructure import InfrastructureManager


class VerificationOS:
    """L1 执行机器统一门面。"""

    def __init__(self, output_root: str | Path):
        self._infra = InfrastructureManager(output_root)

    # ── 生命周期 ──
    def setup(self) -> Dict[str, str]:
        return self._infra.setup()

    # ── 五个 Manager ──

    def compile(self, filelist: str, coverage: bool = True) -> dict:
        """CompileManager：编译 RTL + UVM 环境。"""
        return self._infra.compile(filelist, coverage)

    def run_regression(self, reg_yaml: str = None, mode: str = "local",
                       tests: str = None, tags: str = None,
                       exclude_tags: str = None, **kwargs) -> dict:
        """RegressionManager：吃 regression.yaml 批量跑 case。

        薄门面，参数原样转发给 `InfrastructureManager.run_regression`。除了列出来的
        常用参数，其余（`overrides` / `reference_mode` / `debug_mode`）走 `**kwargs`
        转发 —— 底下的签名再扩展，这个门面也不会悄悄掉队。

        此前它是**写死参数列表**的，于是 `tags` / `exclude_tags` 之后新增的
        `overrides`、`reference_mode`、`debug_mode` 三项它一个都没跟上。签名漂移
        比「少个参数」更糟：有人照着这个自称「上层统一门面」的类去用，会**静默**
        拿不到溯源/调试跑法这些新能力，而且不报错。
        """
        return self._infra.run_regression(reg_yaml, mode, tests, tags,
                                          exclude_tags, **kwargs)

    def simulate(self, top_module: str, uvm_test: str = "", seed: int = 0,
                 coverage: bool = True) -> dict:
        """EdaScheduler：单 case 仿真。"""
        return self._infra.simulate(top_module, uvm_test, seed, coverage)

    def collect_coverage(self, round_num: int = 0, top_module: str = "",
                         seed: int = 0) -> dict:
        """CoverageCollector：覆盖率收集 + 数据库归档固化。"""
        return self._infra.collect_coverage(round_num, top_module, seed)

    def collect_waveform(self, top_module: str = "", uvm_test: str = "",
                         seed: int = 0) -> dict:
        """WaveManager：波形收集（复用 EdaScheduler，返回波形路径）。"""
        result = self._infra.simulate(top_module, uvm_test, seed, coverage=False)
        sim_dir = self._infra.output_root / "sim"
        # `.db` = qwave.db（波形业务现在的产物）；`.wlf` 旧产物；vcd/fsdb 别路
        waves = (list(sim_dir.rglob("*.db")) + list(sim_dir.rglob("*.wlf"))
                 + list(sim_dir.rglob("*.fsdb")) + list(sim_dir.rglob("*.vcd")))
        result["waveforms"] = [str(w) for w in waves[:10]]
        return result

    # ── 复现 / 归档 ──
    def archive_coverage(self, round_num: int, db_path: str) -> dict:
        return self._infra.archive_coverage(round_num, db_path)

    def verify_reproducible(self) -> dict:
        return self._infra.verify_reproducible()

    @property
    def infra(self) -> InfrastructureManager:
        return self._infra
