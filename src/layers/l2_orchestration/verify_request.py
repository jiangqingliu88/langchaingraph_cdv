"""一次验证运行**唯一的输入契约与预检**（CLI / GUI / 应用服务共用）。

## 为什么要有这个文件

同一个 `vagent verify` 曾经有三条入口：

    CLI      → 自己 make_output_root / 拷 casemodel / 改 Settings → PipelineExecutionService
    GUI      → run_service.RunRequest → RunService 线程 → PipelineExecutionService
    app 服务 → verify_service.run_verify_async → PipelineExecutionService

三处各写一遍"运行前要准备什么"，改一处（比如 casemodel 的落点、全量回归开关）
另外两条路就不跟。所以把**输入字段 + 预检**收口到这里：

    VerifyRequest(...)        一次运行的完整声明
    .prepare(root=None)       定输出目录（不撞车）/ 拷 casemodel / 套 Settings
    .incremental_env()        `--incremental-from` 的环境变量窗口（跑完恢复）
    .approval_gate(channel)   审批通道（GUI 可注入 EventChannel）

`RunService` 与 `verify_service` 都只构造它、调用 `prepare()`；**不再各自推断
路径与默认值**。字段与 `PipelineExecutionService.run_closed_loop_streaming`
的形参一一对应。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

from src.tools.execution.regression_tools.sim_modes import (
    DEFAULT_MODE as _DEFAULT_SIM_MODE,
)


def unique_output_root(base: str | Path) -> Path:
    """`make_output_root` 的时间戳精确到秒 —— 串行两次可能撞同一目录。

    撞了就加后缀（`_2`、`_3`…），避免两次运行的日志/证据混在一起。
    """
    from src.layers.l1_infrastructure.output_config import make_output_root

    root = Path(make_output_root(str(base or "output")))
    if not root.exists():
        return root
    for i in range(2, 1000):
        candidate = root.with_name(f"{root.name}_{i}")
        if not candidate.exists():
            return candidate
    return root


def copy_casemodel(casemodel: str, run_root: str | Path) -> Optional[Path]:
    """`--config` / GUI 的 case 模型 → `<run>/inputs/casemodel.yaml`。"""
    if not casemodel:
        return None
    from src.layers.l1_infrastructure.layout import casemodel_path

    src = Path(casemodel)
    if not src.is_file():
        raise FileNotFoundError(f"casemodel 不存在：{src}")
    dest = Path(casemodel_path(run_root))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(src.read_text(encoding="utf-8", errors="replace"),
                    encoding="utf-8")
    return dest


@dataclass
class VerifyRequest:
    """一次闭环运行的输入（字段与 `run_closed_loop_streaming` 对齐）。"""

    spec_text: str = ""
    spec_file: str = ""
    #: 留空 = 用基准目录；非空 = 基准目录或显式目录。
    output_root: str = ""
    target: Optional[float] = None
    max_rounds: int = 5
    design_style: str = "baseline"
    bypass_design_model: bool = False
    #: 回归业务（`cov` / `wave` / …）。**属于这次运行的输入**。
    sim_modes: List[str] = field(
        default_factory=lambda: [_DEFAULT_SIM_MODE])
    #: 分级回归人工节点是否拦截。默认 `True` —— 门是默认该在的。
    manual_gate: bool = True
    rtl_dir: str = ""
    casemodel: str = ""
    approval: str = "threshold"
    approval_timeout_s: float = 0.0
    run_id: str = ""
    checkpointing: bool = True
    resume_from: str = ""
    resume_value: str = "approve"
    #: 全量回归（关掉增量/继承过滤）。
    full_regression: bool = False
    #: 增量验证基线 run 目录；非空时经环境变量传给 ops。
    incremental_from: str = ""
    #: 谁发起的（`cli` / `gui` / `service`）—— 写进 run 的配置快照，便于审计。
    origin: str = "service"

    def snapshot(self) -> dict:
        """本次运行的**生效值**（不是默认值）—— 落 `docs/run_config.json`。

        配置散落在 Settings / 环境变量 / CLI / Workbench 时，"这一轮到底用了
        什么"只能靠翻命令行历史。快照把生效值与来源固定下来。
        """
        import os

        env_keys = sorted(k for k in os.environ if k.startswith("SIGNOFFAI_"))
        return {
            "schema": "run_config_v1",
            "origin": self.origin,
            "spec_file": self.spec_file,
            "output_root": self.output_root or "output",
            "target": self.target,
            "max_rounds": self.max_rounds,
            "design_style": self.design_style,
            "bypass_design_model": self.bypass_design_model,
            "sim_modes": list(self.sim_modes or []),
            "manual_gate": self.manual_gate,
            "rtl_dir": self.rtl_dir,
            "casemodel": self.casemodel,
            "approval": self.approval,
            "checkpointing": self.checkpointing,
            "full_regression": self.full_regression,
            "incremental_from": self.incremental_from,
            # 环境变量会改变行为（worklist / 质量门 / IR 影子 / 白名单）——
            # 只记当前**已设置**的键，不把整台机器的环境倒进来。
            "env": {k: os.environ.get(k, "") for k in env_keys},
        }

    def resolved_spec(self) -> str:
        """`spec_file` 与 `spec_text` 二选一；文件读不到就是空规格（走启发式）。"""
        if self.spec_text:
            return self.spec_text
        if self.spec_file:
            try:
                from src.tools.common.lib.doc_intake import read_document
                return read_document(self.spec_file)
            except Exception as exc:                   # noqa: BLE001
                import structlog
                structlog.get_logger().warning(
                    f"规格读取失败 {self.spec_file}: {exc}")
        return ""

    def prepare(self, root: Optional[str | Path] = None) -> Path:
        """运行前预检：输出目录（不撞车）+ casemodel 落点 + Settings 覆写。"""
        run_root = Path(root) if root else unique_output_root(
            self.output_root or "output")
        copy_casemodel(self.casemodel, run_root)
        if self.full_regression:
            from config.settings import Settings
            Settings.get_instance().verification.incremental_regression = False
        self._write_snapshot(run_root)
        return run_root

    def _write_snapshot(self, run_root: Path) -> None:
        """落配置快照；失败不拦运行（它只是审计材料）。"""
        try:
            import json

            path = Path(run_root) / "docs" / "run_config.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(self.snapshot(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8", newline="\n")
        except OSError:
            pass

    @contextmanager
    def incremental_env(self):
        """`incremental_from` 只在本次启动有效：进环境变量、跑完恢复。

        不进 `PipelineState`：它天然不进检查点，`--resume` 也不该拿到一个
        过期的另一个基线路径。
        """
        key = "SIGNOFFAI_INCREMENTAL_BASELINE"
        prev = os.environ.get(key)
        if self.incremental_from:
            os.environ[key] = str(self.incremental_from)
        try:
            yield
        finally:
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev

    def approval_gate(self, channel=None):
        from src.layers.l2_orchestration.governance.approval import (
            create_approval_gate,
        )

        return create_approval_gate(self.approval, channel=channel,
                                    timeout_s=self.approval_timeout_s)


__all__ = ["VerifyRequest", "copy_casemodel", "unique_output_root"]
