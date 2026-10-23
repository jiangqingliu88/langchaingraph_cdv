"""点状 LLM 调用的**出处** —— 事后能答"这一行 RTL 是谁在哪一轮催出来的"。

## 这里防的是哪一种事故

`call_llm` 是唯一收口，但它**够不着 LangGraph 的 state**：调用链是
`node → _run_agent（把 state 降级成纯 dict）→ executor 的 @staticmethod →
call_llm(prompt, code, errors)`，七个调用点里没有一个手里有 state。
所以"出处"只能从**唯一同时看得见 state 与 task 的地方**（`runtime._run_agent`）
经 contextvar 带下来 —— 这个隐式通道断了不会有任何报错，只会让审计里的
`node_id` 恒为空，于是"是谁催出来的"永远答不了。

## 两条容易写错、且错了不报的地方

  · **用 `contextvars` 而不是全局变量**：LangGraph 会并发跑节点，
    全局变量会让并发的链互相覆盖出处 —— 而**错得出处比没有出处更坏**
    （它会把人指向一个无辜的节点）。
  · **`origin_scope` 退出时恢复外层**（`reset(token)`），不是清空 ——
    嵌套时（一个节点里再调一个带出处的工具）清空会把外层的也抹掉。
"""
from __future__ import annotations

import json

import pytest

from src.layers.l2_orchestration.context.llm_origin import (
    current, origin_scope,
)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """把真正的 LLM 调用换成桩 —— 这组测的是**审计管线**，不是模型。

    不桩的话每次跑都会真发请求（本机配了 key）：慢（实测 27 秒）、花钱、
    而且在没有 key 的机器上结论会变。审计记的是"尝试过"，
    `status` 是不是 `ok` 与本组要验的东西无关。
    """
    from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine

    monkeypatch.setattr(
        LLMQueryEngine, "_invoke_with_fallback",
        lambda self, task_type, messages, max_retries, timeout_s:
            ("module stub; endmodule", 0.01, 0, "deadbeefdeadbeef"))
    # 缓存与预算都可能让"第二次调用"不产生新记录；清掉让每条测试从零开始
    LLMQueryEngine.get_instance().reset()


class TestTheOriginScope:
    def test_outside_the_graph_there_is_no_origin(self):
        """不在图里跑（CLI 单跑工具）→ `None`，如实当作"没有"。"""
        assert current() is None

    def test_inside_the_scope_the_origin_is_visible(self):
        with origin_scope("design", 3, "/tmp/run1"):
            o = current()
            assert o is not None
            assert (o.node_id, o.round, o.audit_dir) == ("design", 3, "/tmp/run1")
        assert current() is None

    def test_nesting_restores_the_outer_scope_not_clears_it(self):
        """嵌套时退出内层要**恢复外层** —— 清空会把外层的出处一并抹掉，
        于是从那一层往后所有 LLM 调用的 `node_id` 都成了空串。"""
        with origin_scope("outer", 1, "/tmp/a"):
            with origin_scope("inner", 2, "/tmp/b"):
                assert current().node_id == "inner"
            assert current() is not None, "内层退出把外层也清掉了"
            assert current().node_id == "outer"

    def test_two_concurrent_chains_do_not_see_each_other(self):
        """`contextvars` 的意义：并发链互不覆盖。

        用全局变量的话，B 链会把 A 链的出处盖掉 —— 审计里 A 的调用被记成 B 的
        节点。那是**错得出处**，比空着更坏：查的人会去找一个无辜的节点。
        """
        import threading

        seen = {}

        def worker(name):
            with origin_scope(name, 1, "/tmp/x"):
                import time
                time.sleep(0.01)           # 让两条链真的重叠
                seen[name] = current().node_id

        ts = [threading.Thread(target=worker, args=(n,)) for n in ("A", "B")]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        assert seen == {"A": "A", "B": "B"}


class TestTheAuditRecordCarriesTheOrigin:
    """真实走一遍 `call_llm` → 审计记录 + `docs/llm_audit.jsonl`。

    不需要 API key：LLM 调不通时 `query()` 照样记一条（`status != "ok"`）——
    审计记的是"**尝试**过"，不是"成功过"。
    """

    def _call(self, run_dir, node_id="design", round_num=3):
        from src.tools.lib.llm_call import call_llm

        with origin_scope(node_id, round_num, str(run_dir)):
            call_llm("写一个 fifo", "", "")
        return run_dir / "docs" / "llm_audit.jsonl"

    def test_the_record_has_site_node_round_and_prompt_hash(self, tmp_path):
        from src.layers.l2_orchestration.context.query_engine import LLMQueryEngine

        run = tmp_path / "output_x_20260101_000000"
        path = self._call(run)
        assert path.is_file(), "审计没落盘 —— 事后就查不到出处了"

        rec = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
        assert rec["node_id"] == "design"
        assert rec["round"] == 3
        assert len(rec["prompt_hash"]) == 12
        assert rec["site"], "site 是自动取的调用点，为空说明取景逻辑坏了"
        assert "test_llm_origin" in rec["site"], f"site 指错地方了：{rec['site']}"

        # 内存里那条也要有出处（快视图与落盘必须同形）
        last = LLMQueryEngine.get_instance().audit_log[-1]
        assert last["node_id"] == "design" and last["prompt_hash"] == rec["prompt_hash"]

    def test_two_calls_append_rather_than_overwrite(self, tmp_path):
        """同一 run 里多次调用是**追加** —— 重写会把前面几轮抹掉。"""
        run = tmp_path / "output_y_20260101_000000"
        self._call(run, round_num=1)
        self._call(run, round_num=2)
        lines = [l for l in (run / "docs" / "llm_audit.jsonl")
                 .read_text(encoding="utf-8").splitlines() if l.strip()]
        assert len(lines) >= 2
        assert [json.loads(l)["round"] for l in lines[-2:]] == [1, 2]

    def test_outside_a_run_nothing_is_written(self, tmp_path, monkeypatch):
        """没有 run 目录时**不落盘**（也没地方落）—— 只进内存，如实。"""
        from src.tools.lib.llm_call import call_llm

        monkeypatch.chdir(tmp_path)
        call_llm("单独跑工具", "", "")
        assert not (tmp_path / "docs").exists()
