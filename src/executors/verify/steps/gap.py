"""gap 定向激励生成 / 编译校验 / 注入（Phase 2.1）。"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List

import structlog

from src.executors.verify.steps.helpers import (
    _main_phase_objection_at, _regression_test_name, _test_files_defining,
)

logger = structlog.get_logger()


class GapRenderSteps:
    def _generate_gap_tests(self, output_dir: Path, gaps: list):
        """根据 gap 生成定向激励 sequence，注册到 agent package 并注入 random test。

        **文件位置一律问 `agent_layout`，不按平铺名猜。** 生成的 env 用编号子目录
        布局（`1_interface/`、`3_transaction_sequencer/`…），按 `<agent>_interface.sv`
        这种名字找的结果是每个 agent 都被跳过 —— 补测试产出 0 个文件，
        `verify_supplement` 判 FAIL 20，那个动作等于空转（实测）。
        """
        import re
        from src.layers.l3_decision.evidence.main import generate_gap_directed_seq
        from src.tools.common.lib.env_introspect import (binding_for_agent,
                                                 env_active_agents,
                                                 env_agent_bindings)
        from src.tools.common.lib.filelist import agent_layout

        agents_dir = output_dir / "agents"
        if not agents_dir.exists() or not gaps:
            return

        # 哪些 agent 真的能收激励 —— 问**模型**（`env.yaml` 的 `is_active`）。
        # passive agent 的 sequencer 压根没建出来，注给它就是 `start_item` 当场
        # fatal（详见 `env_active_agents` 的注释）。下面那个"接口里有没有 output"
        # 的文本判据只在模型读不到时兜底用。
        active = env_active_agents(output_dir)
        if not active:
            logger.warning("读不到 env 模型（inputs/yaml/uvm/env.yaml）的 is_active —— "
                           "无法判断哪些 agent 能收激励，本次跳过定向激励注入")

        # 读 DUT RTL 供 LLM 因果反推（output signal 的缺口需要理解 DUT 逻辑）
        dut_rtl = ""
        rtl_dir = output_dir / "rtl"
        if rtl_dir.exists():
            for sv in sorted(rtl_dir.glob("*.sv")):
                dut_rtl = sv.read_text(encoding="utf-8", errors="replace")
                break

        # **验证策略包的领域知识**：这是 `prompt_hints` 唯一的消费点（见
        # `llm_generate_gap_stimulus`）。没有它，那份"prompt 库"就只是个没人读的字段。
        self._design_hints = ""
        try:
            _pack = (spec.get("_policy_pack") or {}) if isinstance(spec, dict) else {}
            self._design_hints = str(_pack.get("prompt_hints") or "")
            self._hint_ids = [str(it.get("id", "")) for it in
                              (_pack.get("prompt_hint_items") or []) if it.get("id")]
            if self._design_hints:
                logger.info(f"gap 激励将注入验证策略（{len(self._design_hints)} 字符）")
        except Exception:                              # noqa: BLE001
            pass

        # 环境接线（句柄 / 序列器成员 / 事务项类型）—— 从生成出来的 env 里读，
        # 不猜。读不到就如实跳过：编一个名字去生成只会得到编译不过的代码。
        bindings = env_agent_bindings(output_dir)
        if not bindings:
            logger.warning("读不到 env 接线（env_agent_bindings 返回空），跳过定向激励")
            return

        generated = []
        for agent_dir in sorted(agents_dir.iterdir()):
            if not agent_dir.is_dir():
                continue
            agent_dir_name = agent_dir.name
            if agent_dir_name in active and not active[agent_dir_name]:
                logger.info(f"{agent_dir_name}: passive agent（env 模型 is_active=false）"
                            f"—— 它没有 sequencer，注激励进去只会 start_item 报错，跳过")
                continue
            prefix = agent_dir_name[:-len("_agent")] \
                if agent_dir_name.endswith("_agent") else agent_dir_name
            binding = binding_for_agent(bindings, agent_dir_name)
            if not binding or binding.get("unresolved") or not binding.get("item"):
                logger.info(f"{agent_dir_name}: 接线读不出来"
                            f"（{binding.get('unresolved') if binding else '没有对应句柄'}），"
                            f"跳过定向激励")
                continue
            layout = agent_layout(agent_dir)
            # 只对 input agent（interface 有 output 数据端口，即 TB 驱动 DUT 输入）生成；
            # output agent 的 driver 是空实现，驱动它无意义
            if not layout["interface"]:
                logger.info(f"{agent_dir_name}: 找不到接口文件（见 agent_layout），跳过定向激励")
                continue
            iface_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace") for p in layout["interface"])
            # 这个 agent 会不会驱动 DUT？（驱动方向写在**时钟块**里）
            # 模板接口是"内部 logic + 时钟块 + modport"那一套：master_cb 里是
            # `output paddr;` —— 没有 `logic` 也没有位宽。原来只认
            # `output logic` / `output [`，于是**每个 agent 都被判成"不驱动 DUT"**
            # 而跳过（实测：补激励产出 0 个文件，verify_supplement FAIL 20）。
            if not re.search(r"^\s*output\s+\w", iface_text, re.M):
                continue
            if not layout["seq_items"]:
                logger.info(f"{agent_dir_name}: 找不到事务项（*_seq_item.sv），跳过定向激励")
                continue
            # 事务项可能拆成多份（base / master / slave）—— 全读，宽度表按变量名合并
            tx_text = "\n".join(
                p.read_text(encoding="utf-8", errors="replace") for p in layout["seq_items"])
            widths = {}
            for m in re.finditer(r"rand\s+bit\s*\[(\d+):0\]\s+(\w+)\s*;", tx_text):
                widths[m.group(2)] = int(m.group(1)) + 1
            # input agent 处理所有 gap：input signal 直接驱动，output signal LLM 反推，generic 随机
            agent_gaps = [g for g in gaps if isinstance(g, dict)]
            if not agent_gaps:
                continue
            seq_code = generate_gap_directed_seq(
                prefix, agent_gaps, widths, dut_rtl, item_class=binding["item"],
                design_hints=self._design_hints)
            seq_path = agent_dir / f"{prefix}_gap_seq.sv"
            seq_path.write_text(seq_code, encoding="utf-8")
            if not layout["package"]:
                logger.warning(f"{agent_dir_name}: 找不到主包，gap sequence 无法注册（不 include）")
                continue
            self._add_include_to_pkg(layout["package"], seq_path.name)
            generated.append({"cls": f"{prefix}_gap_seq",
                              "dir": agent_dir_name,
                              "handle": binding["handle"],
                              "member": binding.get("member", "sequencer"),
                              "extends": f"uvm_sequence #({binding['item']})"})
            logger.info(f"{agent_dir_name}: 定向激励已生成 {seq_path.name}"
                        f"（{len(agent_gaps)} 个 gap；item={binding['item']}，"
                        f"发往 env.{binding['handle']}.{binding.get('member', 'sequencer')}）")

        if generated:
            self._inject_gap_seq_to_test(output_dir / "env" / "tests", generated)
            # 铁律 1：LLM 生成的代码必须经真实 EDA（vlog）编译校验返回 0/1，阻断自说自话
            compiled = self._verify_compilation(output_dir)
            # **记结局**：prompt 库能不能淘汰全看这张表（"有它 vs 没它"）。
            # 这里能确定的结局只有"生成的序列过没过 EDA 编译门禁"；覆盖率增量是
            # 多因素的，算到单条 hint 头上是过度归因（见 l4_memory/hint_stats.py）。
            try:
                from src.layers.l4_memory.hint_stats import record_hint_outcome

                _ids = list(getattr(self, "_hint_ids", []) or [])
                record_hint_outcome(
                    _ids, compiled, run_id=Path(output_dir).name,
                    note=f"生成 {len(generated)} 个定向 seq" if compiled else "编译门禁未过")
            except Exception as _e:                    # noqa: BLE001 旁路
                logger.debug(f"hint 结局记账跳过: {_e}")
            if not compiled:
                logger.warning("gap sequence 编译校验失败，回退为空实现（LLM 代码被 EDA 否决）")
                self._neutralize_gap_seq(output_dir, generated)

    def _verify_compilation(self, output_dir: Path) -> bool:
        """铁律 1：调用真实 EDA（vlog）编译校验，返回 0/1 作为唯一真理。

        不靠 AI 自我判断语法/时序，只认 vlog 的 PASS/FAIL。
        """
        try:
            from src.tools.common.lib.compile import run_compile_check
            env_name = ""
            for p in sorted((output_dir / "env").glob("*_pkg.sv")):
                env_name = p.name.replace("_pkg.sv", "")
                break
            agents = []
            agents_dir = output_dir / "agents"
            if agents_dir.exists():
                agents = [{"name": d.name} for d in agents_dir.iterdir() if d.is_dir()]
            result = run_compile_check(output_dir, agents, env_name)
            return bool(result.get("passed", False))
        except Exception as e:
            logger.warning(f"编译校验失败: {e}")
            return False

    @staticmethod
    def _neutralize_gap_seq(output_dir: Path, generated: list):
        """把 gap_seq 重写为空实现（LLM 代码未通过 EDA 编译校验后的回退）。

        `generated` 是 `[{cls, handle, member, dir}]`（见 `_generate_gap_tests`）——
        类名与所在目录都在里面，回退时不用再猜一遍；`item` 也带上，免得回退出来的
        类继承一个不存在的基类（原来写死 `{agent}_base_seq`，生成器根本不产它）。
        """
        for item in generated:
            gap_file = output_dir / "agents" / item["dir"] / f"{item['cls']}.sv"
            if not gap_file.exists():
                continue
            extends = item.get("extends") or "uvm_sequence"
            empty = (
                f"// gap_seq 回退为空实现（LLM/Gap 生成的代码未通过 EDA 编译校验）\n"
                f"class {item['cls']} extends {extends};\n"
                f"  `uvm_object_utils({item['cls']})\n"
                f"  function new(string name = \"{item['cls']}\");\n"
                f"    super.new(name);\n"
                f"  endfunction\n"
                f"  virtual task body();\n"
                f"    `uvm_info(\"GAPSEQ\", \"neutralized (generated code rejected by EDA)\", UVM_MEDIUM)\n"
                f"  endtask\n"
                f"endclass : {item['cls']}\n"
            )
            gap_file.write_text(empty, encoding="utf-8", errors="replace")

    @staticmethod
    def _add_include_to_pkg(pkg_file: Path, include_name: str):
        """在 agent package 的 endpackage 前加 include（幂等）。"""
        if not pkg_file.exists():
            return
        text = pkg_file.read_text(encoding="utf-8", errors="replace")
        if include_name in text:
            return
        text = text.replace("endpackage", f'  `include "{include_name}"\nendpackage', 1)
        pkg_file.write_text(text, encoding="utf-8", errors="replace")

    @staticmethod
    def _inject_gap_seq_to_test(tests_dir: Path, generated: list):
        """把 gap sequence 的运行代码注入**随机/生成测试**（不是定向测试）。

        **为什么不能注入定向测试**：`*_direct(ed)_test` 是精确计数的 —— 它按剧本
        发 N 笔事务，scoreboard 就核对那 N 笔。往里多塞几笔"额外激励"，对不上账，
        整个 case 直接挂。实测：注入定向测试之后，第 2 轮回归 **24 个 case 挂 21 个**
        （`pass=3 fail=21`），覆盖率一分没涨还把结果全污染了。

        所以额外激励的落点是**能容忍它的那个测试**（`*_gen_test` / `*_random_test`）。

        **代价要说清楚**：这条路的另一半是"回归得真的去跑那个测试"。实测生成的
        `regression.yaml` 给**每个** case 都写 `+UVM_TESTNAME=<定向测试>`，所以现在
        这份激励生成、注册、编译都过了，但**还没有 case 会执行它** —— 日志里会明说，
        不假装它生效了。要让它生效，得给回归加一个跑生成测试的 case（或在 case
        库里把它挂上）。
        """
        if not tests_dir.exists():
            return
        targets = []
        for pattern in ("*_gen_test.sv", "*_random_test.sv"):
            targets = sorted(tests_dir.glob(pattern))
            if targets:
                break
        if not targets:
            logger.warning("没有可注入 gap sequence 的生成/随机测试（只有定向测试），"
                           "跳过注入 —— 定向测试是精确计数的，塞额外激励会把它挂掉")
            return
        running = _regression_test_name(tests_dir.parent.parent)
        runs_the_stimulus = running and any(
            p in _test_files_defining(tests_dir, running) for p in targets)
        if running and not runs_the_stimulus:
            logger.warning(
                f"gap 激励已注入 {[p.name for p in targets]}，但回归跑的测试是 "
                f"`{running}` —— **没有 case 会执行这段激励**，覆盖率不会因此变化。"
                f"要让它生效，给回归加一个跑生成测试的 case（见 regression.yaml 的 tests）")
        for test_file in targets:
            text = test_file.read_text(encoding="utf-8", errors="replace")
            if "gap_seq" in text:
                continue
            blocks = []
            for item in generated:
                blocks.append(
                    f"    begin\n"
                    f"      {item['cls']} _gseq;\n"
                    f"      _gseq = {item['cls']}::type_id::create(\"_gseq\");\n"
                    f"      _gseq.start(env.{item['handle']}.{item['member']});\n"
                    f"    end"
                )
            inj = "    // Gap-directed stimulation（根据覆盖率 gap 自动生成）\n" + \
                  "\n".join(blocks) + "\n"
            # ⚠️ **锚点必须在 `main_phase` 里**，不能是"文件里第一个
            # `phase.raise_objection(this);`" —— 生成的测试里 `configure_phase`
            # 和 `main_phase` **各有一句**，`str.replace(..., 1)` 取到的是前者。
            #
            # 后果（实测：端到端 `verify --rtl specs/npu_sched`，p0 挂 1 条）：
            # `configure_phase` 跑在 **run_phase 之前**，而 `start_item/finish_item`
            # 靠 **sequencer 的 run_phase** 递送事务 —— 在 configure_phase 里永远
            # 递不出去，于是激励自己那条 20us 超时先报
            #   `[GAPSEQ] 定向激励超时：20000 ns 内对手方未应答`
            # 紧跟着 `[SEQ] neither the item's sequencer ... to start item`
            # 把整条测试判失败。看起来像"DUT 不应答"，其实是**相位用错了**。
            anchor_at = _main_phase_objection_at(text)
            if anchor_at < 0:
                logger.warning(f"{test_file.name}: 找不到 main_phase 的 "
                               f"raise_objection 锚点，未注入")
                continue
            anchor = "    phase.raise_objection(this);\n"
            text = text[:anchor_at] + anchor + "\n" + inj + text[anchor_at + len(anchor):]
            test_file.write_text(text, encoding="utf-8", errors="replace")
