"""env_cov_bins 与 agent 事务字段（Phase 2.1）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import structlog

logger = structlog.get_logger()


class EnvCovSteps:
    def _write_env_cov_bins(self, output_dir: Path, cov_bins: List[Any],
                            dut: Dict[str, Any] = None) -> None:
        """把 `env_cov_bins.yaml` 落到 `find_spec_yaml` 之后、`jinja_render` 之前。

        四个键：

          · `cov_bins`   —— 策略包的语义 cross（`env_cov.sv.j2` 渲染成 `cross_<name>`）
          · `field_bins` —— **case 模型**的边界 bin（渲染成 `cp_<字段>` 的 bins）
          · `dut_if`     —— **DUT 覆盖率接口的身份**（类型名 / bind 实例名 / 时钟 /
                            复位 / 文件），由 `_write_coverage_dut_channel` 给出
          · `dut_bins`   —— DUT 侧覆盖点的 bins 表（`cg_dut` 的显式仓）

        **`dut_if` 是给两个模板读的同一份身份**：env 组件按它声明
        `virtual <type>`，tb_top 按它写 `config_db::set(..., <dut 实例>.<instance>)`。
        两边都从这一个文件读，所以**不会漂**；没有这个键时两边都不生成任何东西
        —— 而不是一边生成、一边不生成（那样组件拿到的是空句柄，覆盖率永远 0%，
        而编译不报错）。

        **键名是 `cov_bins`**（不是 `coverage_bins`）：与 schema 的文档类型一致 ——
        用错的名字会让 `UVMGenerator.run()` 的 schema 检查报 error 并 `SystemExit`，
        于是之后任何一次渲染都被它挡住（实测）。消费端两个键名都认，老的运行目录
        不受影响。

        `field_bins` 是「功能覆盖率方法学」真正落地的地方。**为什么不另生成一个
        `coverage/<module>_cg.sv`**：那份文件从来**没有进过编译清单**（全仓库没有
        一处把它加进 filelist），于是它永远不被采样 —— 一个看着像覆盖率模型、
        其实一个 bin 都没测的文件，比没有更坏。真正被编译/采样/统计的是
        `env_cov.sv.j2` 里那几个 `cg_<agent>`（monitor 每笔事务触发
        `write_<agent>` → `sample()`），所以把模型的边界 bin 喂进那条已跑通的通道：
        coverpoint 名就是事务字段名（= spec 的接口信号名）。

        拿不到模型就不写 `field_bins` —— 模板会退回"值类自动分箱"（0/1/其余），
        那是**降级**不是失败，所以只记一条日志。
        """
        bins_dir = output_dir / "inputs" / "yaml" / "uvm"
        bins_dir.mkdir(parents=True, exist_ok=True)
        payload: Dict[str, Any] = {
            "schema": "env_cov_bins_v1",
            "generated_by": "verify.env_cov_bins",
            "cov_bins": list(cov_bins or []),
        }
        field_bins = self._case_model_field_bins(output_dir)
        if field_bins:
            payload["field_bins"] = field_bins
            logger.info(f"功能覆盖率点（case 模型）：{len(field_bins)} 个字段的边界 "
                        f"bin 已注入 env_cov → 会被真编译、真采样")
        else:
            logger.info("没有可用的 case 模型覆盖点 —— env_cov 退回值类自动分箱")
        if dut:
            payload.update(dut)
        # **落盘失败必须硬失败**：静默降级会让 env_cov 退回自动分箱，
        # 覆盖率仓与验证意图脱节，而 functional_pct 仍然可能很高。
        from src.core.runtime.atomic import atomic_write_json

        atomic_write_json(bins_dir / "env_cov_bins.yaml", payload)

    @staticmethod
    def _agent_transaction_fields(output_dir: Path) -> Dict[str, List[str]]:
        """`{agent 名: [事务字段名]}` —— 只收 **master 且 rand** 的字段。

        `realization.kind=stimulus` 的测试点要落到具体 agent 上；字段名对不上
        就是"set 了一个没人读的键"（本仓库刚踩过：61 个属性 test 全是死标签）。
        数据来自 `find_spec_yaml` 写下的 agent yaml（`interfaces.transaction_vars`）。
        """
        import yaml as _yaml

        yaml_dir = output_dir / "inputs" / "yaml" / "uvm"
        env_path = yaml_dir / "env.yaml"
        try:
            env = (_yaml.safe_load(env_path.read_text(encoding="utf-8",
                                                       errors="replace")) or {}
                   ).get("environment") or {}
        except (OSError, ValueError):
            return {}
        out: Dict[str, List[str]] = {}
        for agent in (env.get("agents") or []):
            if not isinstance(agent, dict):
                continue
            name = str(agent.get("name") or "").strip()
            # **passive agent 没有 sequencer**：把它的字段当成激励通道，
            # 生成的约束会挂在一个根本不存在的驱动路径上（`_seq.start(null)`
            # 那一类问题的变体）。`is_active` 缺省当作 active。
            if not name or agent.get("is_master") is False:
                continue
            if agent.get("is_active") is False:
                continue
            try:
                doc = _yaml.safe_load(
                    (yaml_dir / f"{name}.yaml").read_text(
                        encoding="utf-8", errors="replace")) or {}
            except (OSError, ValueError):
                continue
            iface = doc.get("interfaces")
            tvars = (iface.get("transaction_vars") if isinstance(iface, dict)
                     else doc.get("transaction_vars")) or []
            fields = []
            for v in tvars:
                if not isinstance(v, dict) or not v.get("name"):
                    continue
                if str(v.get("isrand", "False")) != "True":
                    continue
                if str(v.get("is_master", "True")) == "False":
                    continue
                fields.append(str(v["name"]))
            if fields:
                out[name] = fields
        return out
