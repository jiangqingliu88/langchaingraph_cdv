"""LLM 输出治理 —— schema 绑定、prompt 版本、缓存、失败策略。

不调真实模型：把 `_invoke_with_fallback` 打桩成固定输出，只验契约层。
"""
from __future__ import annotations

import pytest

from src.orchestration_plane.l2.context.query_engine import (
    LLMContractError,
    LLMQueryEngine,
)


def _engine(content: str = '{"instr_opcode": "generic"}'):
    engine = LLMQueryEngine()
    engine._invoke_with_fallback = lambda *a, **k: (content, 0.01, 10, "sha")
    return engine


JSON_SCHEMA = {"type": "object"}
CODE_SCHEMA = {"type": "string", "minLength": 1}
MSGS = [{"role": "user", "content": "classify"}]


def test_missing_schema_is_rejected_and_audited():
    engine = _engine()
    assert engine.query("t", MSGS) == ""
    rec = engine.audit_log[-1]
    assert rec["status"] == "schema_missing"
    assert rec["validation"] == ""
    assert engine.cache == {}


def test_invalid_json_is_not_cached_or_returned():
    engine = _engine("not json")
    out = engine.query("t", MSGS, output_schema=JSON_SCHEMA,
                       output_format="json", prompt_version="v1")
    assert out == ""
    assert engine.cache == {}
    rec = engine.audit_log[-1]
    assert rec["status"] == "schema_invalid"
    assert rec["prompt_version"] == "v1"
    assert rec["output_format"] == "json"


def test_valid_output_is_cached_and_audited():
    engine = _engine()
    args = dict(output_schema=JSON_SCHEMA, output_format="json",
                prompt_version="v1")
    first = engine.query("t", MSGS, **args)
    second = engine.query("t", MSGS, **args)
    assert first == second == '{"instr_opcode": "generic"}'
    assert engine.audit_log[-1]["status"] == "cache_hit"
    assert engine.audit_log[-2]["validation"] == "valid"


def test_prompt_version_changes_invalidate_cache():
    engine = _engine("hello")
    engine.query("t", MSGS, output_schema=CODE_SCHEMA, prompt_version="v1")
    engine.query("t", MSGS, output_schema=CODE_SCHEMA, prompt_version="v2")
    statuses = [r["status"] for r in engine.audit_log]
    assert statuses.count("ok") == 2
    assert "cache_hit" not in statuses


def test_cache_hit_does_not_reinvoke():
    engine = _engine("hello")
    calls = []
    engine._invoke_with_fallback = lambda *a, **k: (calls.append(1) or "hello",
                                                    0.0, 0, "")
    args = dict(output_schema=CODE_SCHEMA, prompt_version="v1")
    engine.query("t", MSGS, **args)
    engine.query("t", MSGS, **args)
    assert len(calls) == 1


def test_fail_fast_raises_on_invalid_output():
    engine = _engine("")
    with pytest.raises(LLMContractError):
        engine.query("t", MSGS, output_schema=CODE_SCHEMA,
                     prompt_version="v1", failure_policy="fail_fast")


def test_unknown_failure_policy_is_a_programming_error():
    with pytest.raises(ValueError, match="failure_policy"):
        _engine().query("t", MSGS, output_schema=CODE_SCHEMA,
                        prompt_version="v1", failure_policy="ignore")


def test_call_llm_requires_schema_and_prompt_version():
    from src.runtime_plane.tools.common.lib.llm_call import call_llm

    with pytest.raises(TypeError):
        call_llm("p", "", "")               # 缺 output_schema / prompt_version
    with pytest.raises(ValueError, match="prompt_version"):
        call_llm("p", "", "", output_schema=CODE_SCHEMA, prompt_version="")


def test_code_fences_are_stripped_before_caching():
    from src.runtime_plane.tools.common.lib.llm_call import CODE_SCHEMA

    engine = _engine("```systemverilog\nmodule x; endmodule\n```")
    out = engine.query("t", MSGS, output_schema=CODE_SCHEMA,
                       prompt_version="v1")
    assert out == "module x; endmodule"
    assert engine.cache
