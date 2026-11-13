"""
黄金基线 + 回归守卫 —— 防退化机制

黄金基线: 覆盖率首次达标时，打包当时的 RTL/TB/编译选项/种子 → golden.tar.gz
回归守卫: 决策层执行"设计重构"前，强制跑 golden 用例集，<100% 拒绝本次修改

用途:
    from src.runtime_plane.infrastructure.golden_baseline import GoldenBaseline, GuardianAgent
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# ═══════════════════════════════════════════════════════════════
# 黄金基线
# ═══════════════════════════════════════════════════════════════

@dataclass
class GoldenBaseline:
    """覆盖率达标时的完整快照"""
    version: str
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    coverage: Dict[str, float] = field(default_factory=dict)
    rtl_hash: str = ""
    tb_hash: str = ""
    seeds: List[int] = field(default_factory=list)
    compile_options: Dict[str, str] = field(default_factory=dict)
    source_dir: str = ""


def _dir_hash(path: Path, pattern: str = "*.sv") -> str:
    """计算目录下所有文件（按 pattern 过滤）的聚合 hash。"""
    sha = hashlib.sha256()
    if not path.exists():
        return ""
    for f in sorted(path.rglob(pattern)):
        sha.update(f.relative_to(path).as_posix().encode())
        sha.update(hashlib.md5(f.read_bytes()).digest())
    return sha.hexdigest()


def save_golden_baseline(output_dir: Path, coverage: Dict[str, float],
                         target: float = 95.0) -> Optional[str]:
    """覆盖率达标时保存黄金基线，返回 tar 路径或 None（未达标）。"""
    functional = coverage.get("functional", coverage.get("overall_pct", 0))
    if functional < target:
        return None

    od = Path(output_dir)
    baseline = GoldenBaseline(
        version=datetime.now().strftime("%Y%m%d_%H%M%S"),
        coverage=coverage,
        rtl_hash=_dir_hash(od / "rtl"),
        tb_hash=_dir_hash(od / "agents") + _dir_hash(od / "env"),
        source_dir=str(od),
    )

    # 打包 golden.tar.gz
    golden_dir = od / "golden"
    golden_dir.mkdir(parents=True, exist_ok=True)
    (golden_dir / "baseline.json").write_text(
        json.dumps({
            "version": baseline.version,
            "created_at": baseline.created_at,
            "coverage": baseline.coverage,
            "rtl_hash": baseline.rtl_hash,
            "tb_hash": baseline.tb_hash,
        }, indent=2, ensure_ascii=False), encoding="utf-8")

    tar_path = golden_dir / f"golden_{baseline.version}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for sub in ["rtl", "env", "agents", "bench", "inputs"]:
            p = od / sub
            if p.exists():
                tar.add(p, arcname=sub)

    return str(tar_path)


# ═══════════════════════════════════════════════════════════════
# 回归守卫
# ═══════════════════════════════════════════════════════════════

class GuardianAgent:
    """回归守卫：改设计前强制跑 golden 用例集，<100% 拒绝。

    `run_tool` 为什么是**注入**的，不是这里 import 的
        跑 golden 用例集走的是「工具子进程」那条通路，而它属于**编排层**
        （`l2_orchestration.communication.tool_subprocess`）。

        本模块在 **L1**（零 AI 的确定性层）—— 直接 import 就是 L1 反向依赖 L2。
        反了的话，L1 就没法脱离编排层单独跑，也就没法单独测（而 L1 恰恰是最
        该能单独测的那一层：它不该拖进 langgraph / agent 注册表任何东西）。

        所以由调用方（L2）把 runner 传进来：
            run_tool(tool_name: str, args: dict) -> {"success", "data", "error"}

    **不注入时不假装"跑过了"** —— `pre_refactor_check` 返回 `allowed=False`
    并说明原因。守卫最不能做的事就是"验证不了却放行"。
    """

    def __init__(self, output_dir: Path,
                 run_tool: Optional[Callable[..., Dict[str, Any]]] = None):
        self.output_dir = Path(output_dir)
        self.golden_dir = self.output_dir / "golden"
        self._run_tool = run_tool

    def has_golden(self) -> bool:
        """是否有黄金基线。"""
        return (self.golden_dir / "baseline.json").exists()

    def load_baseline(self) -> Optional[dict]:
        """加载黄金基线信息。"""
        bp = self.golden_dir / "baseline.json"
        if not bp.exists():
            return None
        return json.loads(bp.read_text(encoding="utf-8"))

    async def pre_refactor_check(self, rtl_hash: str = "") -> dict:
        """改设计前的守卫检查。

        返回: {allowed, reason, baseline}
        """
        baseline = self.load_baseline()
        if not baseline:
            return {"allowed": True, "reason": "无黄金基线，跳过守卫", "baseline": None}

        # 检查当前 RTL 是否已偏离基线（已修改）
        current_rtl_hash = _dir_hash(self.output_dir / "rtl")
        baseline_rtl_hash = baseline.get("rtl_hash", "")

        if current_rtl_hash == baseline_rtl_hash:
            # RTL 没变，无需守卫
            return {"allowed": True, "reason": "RTL 未变更", "baseline": baseline}

        # RTL 已变 → 强制跑 golden 用例集。
        # 没有 runner 就**不能放行** —— 守卫最不该做的就是"验证不了却放行"。
        if self._run_tool is None:
            return {
                "allowed": False,
                "reason": "没有注入 golden 运行器 —— RTL 已变更但无法验证是否破坏基线。"
                          "（L1 不 import 编排层，runner 由调用方传入）",
                "baseline": baseline,
            }

        golden_pass = await self._run_golden_tests()

        if golden_pass < 100.0:
            return {
                "allowed": False,
                "reason": f"golden 用例通过率 {golden_pass}% < 100%，拒绝本次设计修改",
                "baseline": baseline,
                "golden_pass_rate": golden_pass,
            }

        return {"allowed": True, "reason": "golden 用例 100% 通过", "baseline": baseline}

    async def _run_golden_tests(self) -> float:
        """跑 golden 用例集，返回通过率。

        跑的方式由调用方注入的 `run_tool` 决定 —— 默认那条走独立子进程
        （Stdio 进程隔离），由真实 EDA（vlog 编译 + vsim 仿真）返回 0/1
        作为唯一真理。子进程崩溃不拖垮主流程。

        **失败一律返回 0.0 而不是抛**：调用方拿它跟 100% 比，0 就是"拒绝
        本次改动"—— 那正是崩溃时该有的结论。
        """
        import asyncio
        try:
            result = await asyncio.to_thread(
                self._run_tool, "regression.run_golden",
                {"output_dir": str(self.output_dir)})
            if isinstance(result, dict) and result.get("success"):
                return float(result.get("data", {}).get("pass_rate", 0.0))
            return 0.0
        except Exception:
            return 0.0


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

async def guardian_check(output_dir: Path) -> dict:
    """便捷入口：守卫检查。"""
    return await GuardianAgent(output_dir).pre_refactor_check()
