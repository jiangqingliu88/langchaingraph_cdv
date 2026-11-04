"""约束模型落盘与状态标注（Phase 2.1）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import structlog

from src.executors.verify.steps.helpers import _constraint_ports, _find_case_model, _spec_of

logger = structlog.get_logger()


class ConstraintSteps:
    def _write_constraint_yaml(self, output_dir: Path) -> None:
        """`inputs/yaml/uvm/constraint.yaml` —— case 模型 → 约束模型（`env/cons/*` 的输入）。

        ## 这一步补的是"方法学的第三条腿"

            case 模型     说「该测什么」   themes[].method
            覆盖率模型    说「怎么量」     coverpoints / bins
            约束模型      说「怎么驱动」   policies + combinator   ← 这里产出

        在这之前 `build_constraint` **只有 CLI 调**（`vagent case-model constraints`），
        流水线里从来没生成过 —— 于是 `env/cons/*` 在任何真实 run 里都不存在，
        "批次 test 挂策略名" 那条链（`batch_policy` → `create_from_batch`）一直是空转。
        产物丢进同一个 `inputs/yaml/uvm/` 目录即可，`gen_uvm` 按**顶层 `constraint:` 键**
        识别（文件名不参与）。

        ## 端口从 env.yaml 推（不写进 case 模型）

        约束要 `transactions`（agent 名 + seq_item 类型）才能生成协调序列 —— 而
        case 模型是**建模概念**（中文维度名），不该混进实现名。所以从 `find_spec_yaml`
        刚写下的 env.yaml 反读 agents。

        **类型名从 `type` 推，不是从 `name`**：env.yaml 里
        `name: npu_sched_in` / `type: npu_sched_in_master_agent`，而生成的
        seq_item 类是 `npu_sched_in_master_seq_item` —— 照 `name` 拼会得到
        `npu_sched_in_seq_item`，那个类**不存在**（编译期才报）。推导规则与
        `gen_uvm.AgentModel.seq_item_type` 逐字一致（去掉 `_agent` 再加 `_seq_item`）。

        没有 case 模型 / 没有 agent / `build_constraint` 报错 —— 一律**记日志不写**：
        一个空的 `transactions` 渲染出来的协调序列是个空壳（发送循环一次都不进），
        不生成比生成空壳诚实。
        """
        cm_file = _find_case_model(_spec_of(output_dir), output_dir)
        if cm_file is None:
            logger.info("没有 case 模型 —— 跳过约束模型生成（env/cons 不会出现）")
            return
        ports = _constraint_ports(output_dir)
        if not ports:
            logger.info("env.yaml 里没有 agent —— 跳过约束模型生成"
                        "（没有端口就不生成，见 build_constraint）")
            return
        try:
            from src.tools.generation.casemodel_tools.associate import build_constraint

            # `agent_fields` 决定"这个字段该约束哪个 agent" —— 没有它，可驱动
            # 维度只能在一端口时才敢落，多 agent 时全部退化成骨架。
            payload = build_constraint(
                cm_file.read_text(encoding="utf-8"), ports=ports,
                agent_fields=self._agent_transaction_fields(output_dir) or None)
            if payload.get("error"):
                logger.warning(f"约束模型生成不了，跳过: {payload['error']}")
                return
            (output_dir / "inputs" / "yaml" / "uvm" / "constraint.yaml").write_text(
                payload["constraint_yaml"], encoding="utf-8")
            self._write_constraint_status(output_dir, payload)
            # **同一份生效状态也要能被覆盖率计划读到**：签核的人先看
            # `coverage_plan.yaml`，再看 `constraint.yaml` 是两步；把
            # `constraint_backing` 写进计划产物，一步就能回答"哪些策略在约束"。
            self._annotate_coverage_plan(output_dir, payload)
        except Exception as e:                       # noqa: BLE001 旁路，别拦 env 生成
            logger.warning(f"约束模型落盘失败（env/cons 将不生成）: {e}")
            return
        # **日志放在 try 之外**：打日志本身可能失败（Windows 控制台是 GBK，
        # 而 `notes` 里那个 `↔` 不在 GBK 里 —— 实测撞过），而那时文件**已经写成了**。
        # 把它圈在同一个 try 里，except 就会把"日志没打出来"报成"落盘失败"，
        # 让排查的人去找一个并不存在的写入问题。**日志失败不该冒充落盘失败。**
        logger.info(f"约束模型：{payload['policy_count']} 条策略 / "
                    f"default_mode={payload['default_mode']} / "
                    f"{len(ports)} 个端口 → constraint.yaml（渲染出 env/cons/）")
        for note in payload.get("notes") or []:
            logger.warning(f"约束模型: {note}")

    @staticmethod
    def _write_constraint_status(output_dir: Path, payload: Dict[str, Any]) -> None:
        """`coverage/constraint_status.json` —— **约束到底有没有在约束**。

        与 `constraint.yaml` 一起落盘，供覆盖率阶段拼进 `semantic_validations`、
        再由 audit 门禁读（`PASS_WITH_CAVEAT` 就挂在这个字段上）。

        **为什么在生成期判、不去抓仿真日志**：`env_cons_policies.sv.j2` 里策略体
        落到 `default:` 是**运行期**的分支，而那条 `uvm_info` 是 `UVM_HIGH` ——
        默认 verbosity（`UVM_MEDIUM`）下**根本不打**，`sim.sh` 里也没有
        `+UVM_VERBOSITY`。所以"从日志 grep `default:`"那条路是死的（实测）。
        而这件事**生成期就确定**（`build_constraint` 声明 `policies_are_skeletons`），
        不必等仿真、也不必改 verbosity。
        """
        from src.tools.generation.uvm_tools.generation.generators.constraint_gen import (
            write_constraint_status)
        write_constraint_status(output_dir, payload, logger)

