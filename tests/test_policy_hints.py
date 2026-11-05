"""验证策略包（prompt 库）—— **有 id 才算资产，被消费才算存在**。

实测过的两处"死"：`prompt_hints` 写进 `spec["_policy_pack"]` 后**零读取处**，
而专门写着注入用的 `PolicyPackLoader.apply_to_prompt` **零调用方** —— 库和注入器
都写好了，只差最后一根线。这一组钉住那根线：**条目有 id、文本真的进 prompt**。
"""
from __future__ import annotations

from src.layers.l2_orchestration.governance.policy_pack import PolicyPack, get_policy_pack_loader


class TestHintItems:

    def test_old_block_form_splits_into_numbered_items(self):
        """旧写法（整块文本）按行首编号拆条 —— 现有的三个 policy.yaml 都是这个形式。"""
        pack = PolicyPack(design_style="baseline", prompt_hints=
                          "针对通用设计：\n1. 基本功能\n2. 边界值\n3. 复位")
        items = pack.prompt_hint_items()
        assert [i["id"] for i in items][0].startswith("baseline_1")
        assert any("边界值" in i["text"] for i in items)

    def test_explicit_id_form_is_used_as_is(self):
        """新写法：显式 id 原样用（不猜、不改名）。"""
        pack = PolicyPack(design_style="pipeline", prompt_hints=[
            {"id": "hp_reset", "text": "复位与初始化必须覆盖"},
            {"text": "无 id 的条目给个兜底名"},
        ])
        items = pack.prompt_hint_items()
        assert items[0] == {"id": "hp_reset", "text": "复位与初始化必须覆盖"}
        assert items[1]["id"].startswith("pipeline_2")

    def test_single_block_gets_one_id_not_fake_granularity(self):
        """拆不出多段就当一个条目 —— **不编造粒度**。"""
        pack = PolicyPack(design_style="baseline", prompt_hints="一句话的领域知识。")
        items = pack.prompt_hint_items()
        assert len(items) == 1 and items[0]["text"] == "一句话的领域知识。"

    def test_empty_hints_yield_nothing(self):
        assert PolicyPack(design_style="baseline", prompt_hints="").prompt_hint_items() == []

    def test_shipped_packs_all_have_ids(self):
        """随仓库发的三个策略包，每条 hint 都得有 id —— 没 id 就没法统计哪条有用。"""
        loader = get_policy_pack_loader()
        for style in ("baseline", "pipeline", "low_power"):
            pack = loader.load(style)
            if pack is None:
                continue
            for item in pack.prompt_hint_items():
                assert item["id"] and item["text"], f"{style} 有条目缺 id/text"


class TestHintsReachThePrompt:
    """**被消费才算存在** —— 这两条钉的是"库到 prompt"那根线。"""

    # 注：本来还有一条"prompt 里必须含 hint"的测试，但 `_call_llm_raw` 是在函数
    # 体内 import 的，**打桩打不进去** —— 写了两版都真发了 LLM 请求（不过第一次
    # 那笔请求恰好证明了线是通的：prompt 里确实是「验证策略…复位与初始化必须覆盖」）。
    # 要让它可测，得先把 prompt 组装抽成 `_gap_stimulus_prompt(...)` 再打桩 ——
    # 那是下一步的小重构，不在这里硬凑。

    def test_directed_seq_threads_hints_toward_the_llm(self):
        """`generate_gap_directed_seq` 得收下 hints 并往下传（否则上面那根线断在半路）。"""
        import inspect

        from src.layers.l3_decision.evidence.main import (generate_gap_directed_seq,
                                                  llm_generate_gap_stimulus)
        assert "design_hints" in inspect.signature(llm_generate_gap_stimulus).parameters
        assert "design_hints" in inspect.signature(generate_gap_directed_seq).parameters
