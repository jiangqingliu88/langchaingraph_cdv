"""方法学流水线 —— 把阶段串起来，产出**可复现的测试点 IR 包**。

## 用法

    from .framework import MethodologyPipeline

    bundle = MethodologyPipeline().run(model, env_name="npu_sched_env",
                                       agents={"npu_sched_in": [...]})
    bundle.testpoints          # List[TestPoint]
    bundle.summary             # counts
    bundle.manifest()          # 落 methodology.json 的内容
    bundle.testpoints_yaml()   # 落 testpoints.yaml 的内容

## 扩展

    pipeline = MethodologyPipeline()
    pipeline.insert(MyPreprocessStage(), after="decompose")

新增 realization 不用动这里 —— 注册到 `realization.REALIZATIONS` 即可；
新增阶段只要声明 `consumes` / `produces`。

## 不变式

- 阶段顺序由**流水线**决定，阶段之间零 import；
- 依赖缺失在**启动前**报错（不是跑到一半拿到 None）；
- 截断（`max_tests`）只发生在所有阶段之后，边界取值优先；
- 产物随包附 `manifest`：阶段、计数、输入、IR 哈希 —— 可复现/可审计。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .contracts import (FRAMEWORK_NAME, FRAMEWORK_VERSION, PipelineContext,
                        Stage, StageRecord)
from .model import KIND_OBSERVE, TestPoint
from .naming import ascii_slug
from .serialize import testpoints_yaml as _testpoints_yaml
from .stages import (DecomposeStage, ExecuteStage, RealizeStage, TraceStage)

DEFAULT_STAGES: tuple = (DecomposeStage, TraceStage, RealizeStage, ExecuteStage)


@dataclass
class MethodBundle:
    """一次方法学运行的产物包。"""
    testpoints: List[TestPoint] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    stages: List[StageRecord] = field(default_factory=list)
    env_name: str = ""
    module_name: str = ""
    dropped: int = 0
    truncated: bool = False

    @property
    def count(self) -> int:
        return len(self.testpoints)

    @property
    def observe_only(self) -> int:
        return sum(1 for tp in self.testpoints if tp.observe_only)

    def by_kind(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for tp in self.testpoints:
            out[tp.realization.kind] = out.get(tp.realization.kind, 0) + 1
        return out

    def by_stage(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for tp in self.testpoints:
            out[tp.execution.stage] = out.get(tp.execution.stage, 0) + 1
        return out

    def to_dict(self) -> Dict[str, Any]:
        """**向后兼容**的 payload 形状（`build_testpoints` / API 用）。"""
        return {
            "count": self.count,
            "testpoints": [tp.to_dict() for tp in self.testpoints],
            "by_kind": self.by_kind(),
            "by_stage": self.by_stage(),
            "observe_only": self.observe_only,
            "notes": list(self.notes),
        }

    def testpoints_yaml(self) -> str:
        # **与 plan 门面共用一份序列化** —— manifest 的哈希算的就是这份文本。
        return _testpoints_yaml(self.to_dict())

    def manifest(self) -> Dict[str, Any]:
        """`methodology.json` —— 这次运行**用了哪些阶段、产出了什么**。

        与证据链同一纪律：阶段 + 计数 + 输入 + **IR 哈希**。换了一份模型，
        哈希就变；签核时能核"这堆测试点到底出自哪份 IR"。
        """
        ir = self.testpoints_yaml().encode("utf-8")
        return {
            "framework": FRAMEWORK_NAME,
            "version": FRAMEWORK_VERSION,
            "stages": [r.to_dict() for r in self.stages],
            "inputs": {"env_name": self.env_name, "module_name": self.module_name},
            "summary": {
                "count": self.count,
                "by_kind": self.by_kind(),
                "by_stage": self.by_stage(),
                "observe_only": self.observe_only,
                "dropped": self.dropped,
                "truncated": self.truncated,
            },
            "artifacts": {
                "testpoints_yaml": {"sha256": hashlib.sha256(ir).hexdigest(),
                                    "size": len(ir)},
            },
            "notes": list(self.notes),
        }


class MethodologyPipeline:
    """可组合的方法学流水线。"""

    def __init__(self, stages: Optional[Iterable[Any]] = None) -> None:
        self.stages: List[Stage] = [
            s() if isinstance(s, type) else s
            for s in (stages if stages is not None else DEFAULT_STAGES)
        ]
        self._check_unique_names()

    # ── 扩展点 ──

    def insert(self, stage: Stage, after: Optional[str] = None) -> "MethodologyPipeline":
        """插入一个阶段（默认追加在末尾）。"""
        stage = stage() if isinstance(stage, type) else stage
        if after is None:
            self.stages.append(stage)
        else:
            for i, s in enumerate(self.stages):
                if s.name == after:
                    self.stages.insert(i + 1, stage)
                    break
            else:
                raise KeyError(f"没有阶段 {after!r}（现有："
                               f"{'、'.join(s.name for s in self.stages)}）")
        self._check_unique_names()
        return self

    def stage_names(self) -> List[str]:
        return [s.name for s in self.stages]

    def _check_unique_names(self) -> None:
        names = [s.name for s in self.stages]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"阶段名重复：{'、'.join(sorted(dup))}")

    # ── 运行 ──

    def run(self, model: Any, *, env_name: str = "", agents: Optional[Dict[str, List[str]]] = None,
            module_name: str = "", coverage: Any = "auto",
            max_tests: Optional[int] = None) -> MethodBundle:
        """跑完整条流水线。`model` 会被 `resolve()`（幂等）。"""
        from ..coverage import coverage_model

        resolved = model.resolve()
        env_name = env_name or f"{ascii_slug(resolved.object) or 'dut'}_env"
        module_name = module_name or ascii_slug(resolved.object) or "dut"

        ctx = PipelineContext(model=resolved, env_name=env_name,
                              module_name=module_name, agents=agents)
        ctx.coverage = (coverage_model(resolved, module_name)
                        if coverage == "auto" else coverage)

        records: List[StageRecord] = []
        for stage in self.stages:
            missing = [k for k in stage.consumes if k not in ctx.artifacts]
            if missing:
                raise RuntimeError(
                    f"阶段 {stage.name} 依赖缺失：{'、'.join(missing)}"
                    f"（流水线顺序：{' → '.join(self.stage_names())}）")
            before = len(ctx.notes)
            stage.run(ctx)
            produced = ctx.take(stage.produces)
            records.append(StageRecord(
                name=stage.name, consumes=list(stage.consumes),
                produces=stage.produces,
                count=len(produced) if isinstance(produced, list) else 0,
                notes=len(ctx.notes) - before))

        points: List[TestPoint] = list(ctx.take("testpoints") or [])
        total = len(points)
        truncated = False
        if max_tests is not None and 0 <= max_tests < total:
            order = sorted(range(total), key=lambda i: (not points[i].boundary, i))
            points = [points[i] for i in sorted(order[:max_tests])]
            truncated = True
            ctx.notes.append(f"测试点截断到 {max_tests} 条，丢弃 "
                             f"{total - len(points)} 条（优先保留边界取值）")

        return MethodBundle(testpoints=points, notes=ctx.notes, stages=records,
                            env_name=env_name, module_name=module_name,
                            dropped=total - len(points), truncated=truncated)


