"""运行产物清单 —— 只读的 run artifacts 体检（L2）。

从 `app/services/flow/run_api.py` 抽出；审批等 L2 节点直接用它，
不再反向依赖 app 层。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from src.orchestration_plane.l2.flow_shared import UVM_SCHEMA, _artifact


def run_artifacts(run_dir: str = "") -> Dict[str, Any]:
    """一次运行的中间产物目录 + 每份的 schema 体检结果。

    只读落盘的文件，不碰运行中的进程。文件不在就 `exists: false` 照列 ——
    "这一份还没生成"本身就是有用的信息（说明那次运行没跑到产出它的阶段）。
    """
    if not run_dir:
        return {"error": "没有指定运行目录"}
    root = Path(run_dir)
    if not root.is_dir():
        return {"error": f"run_dir not found: {run_dir}"}

    items: List[Dict[str, Any]] = []

    # 设计阶段的产出、verify 的输入。"AI 把规格理解成了什么"全在这一份里，
    # 所以它排在最前面 —— 人最该先看的是这个，而不是 UVM 配置。
    items.append(_artifact(root, Path("spec.json"), "设计", None))

    # UVM 配置：数 per-agent 命名（`dut_in.yaml` / `apb_master.yaml`），所以是 glob
    uvm_dir = root / "inputs" / "yaml" / "uvm"
    for path in sorted(uvm_dir.glob("*.yaml")):
        items.append(_artifact(root, path.relative_to(root), "验证·UVM", UVM_SCHEMA))

    items.append(_artifact(root, Path("inputs/yaml/regression.yaml"), "回归", None))

    # ── 功能覆盖：case 模型的**声明** + 它派生的语义 cross ──
    #
    # `coverage_points.json` 是「功能覆盖率方法学」的落点：模型声明了哪些覆盖点、
    # 每个点有哪些 bin、哪些维度要交叉。它**不是**命中数据（命中在 ucdb 里，见
    # 覆盖率页），所以单列一组、和 uvmd 配置那组一样是"输入侧"的产物。
    items.append(_artifact(root, Path("inputs/vplan/data/execution_meta.csv"),
                           "功能覆盖", None))
    items.append(_artifact(root, Path("coverage/coverage_points.json"), "功能覆盖", None))
    items.append(_artifact(root, Path("inputs/yaml/uvm/env_cov_bins.yaml"),
                           "功能覆盖", None))

    present = [i for i in items if i["exists"]]
    with_schema = [i for i in present if i["schema"]]
    bad = [i for i in with_schema if i["errors"]]
    return {
        "run_id": root.name,
        "run_dir": str(root),
        "artifacts": items,
        "present": len(present),
        "checked": len(with_schema),
        "with_errors": len(bad),
        # 一行话给界面顶部用 —— 数在这里算，免得界面自己再数一遍数出第二份真相
        "summary": (f"{len(present)} 份产物"
                    + (f"，{len(bad)} 份 schema 不符" if bad else "，schema 都过")),
    }
