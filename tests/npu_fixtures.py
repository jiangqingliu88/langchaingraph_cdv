"""测试夹具路径 —— 旧 NPU casemodel / RTL 已从 `specs/npu_sched/` 移出。

`specs/npu_sched/` 现在是 VPlan spec-first 项目；旧 casemodel 只作为回归测试
夹具保留在 `tests/fixtures/legacy_npu_sched/`，避免测试把项目输入当成默认存在。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_NPU_DIR = ROOT / "tests" / "fixtures" / "legacy_npu_sched"
NPU_CASEMODEL = LEGACY_NPU_DIR / "casemodel.yaml"
NPU_RTL_DIR = LEGACY_NPU_DIR
