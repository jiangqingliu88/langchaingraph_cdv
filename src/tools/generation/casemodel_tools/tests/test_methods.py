"""生成方法策略表（P5）—— 方法 → 策略名 / 组合器 / 赋值方式只有一处真相。"""
from __future__ import annotations

from src.tools.generation.casemodel_tools.domain import METHOD_ALIASES
from src.tools.generation.casemodel_tools.domain.dimensions import build_dimension
from src.tools.generation.casemodel_tools.framework.constraints import (
    ConstraintRequest, compile_assignments,
)
from src.tools.generation.casemodel_tools.framework.methods import (
    METHODS, assignment_mode, policy_map, registered_ids, strategy,
)


class TestRegistry:
    def test_covers_every_declared_method(self):
        assert set(registered_ids()) == set(METHOD_ALIASES.values())
        assert set(registered_ids()) == {"D", "G", "SPCL", "RND", "RPLY"}

    def test_associate_tables_come_from_the_registry(self):
        from src.tools.generation.casemodel_tools import associate

        assert associate.METHOD_TO_POLICY == policy_map()
        assert set(associate.METHOD_TO_CONSTRAINT) == set(METHODS)

    def test_every_method_has_an_observable_difference(self):
        """方法不能只是文字备注 —— 策略名/组合器至少要有一项不同。"""
        shapes = {(m.suffix, m.combinator) for m in METHODS.values()}
        assert len(shapes) == len(METHODS)

    def test_unknown_method_is_not_silently_mapped(self):
        assert strategy("NOPE") is None
        assert assignment_mode("NOPE") == "cycle"      # 与 v1 的兜底一致
        assert assignment_mode("") == "cycle"


class TestAssignmentMode:
    def _dim(self):
        return build_dimension({
            "id": "D_type", "name": "类型",
            "fields": [{"name": "t", "type": "enum", "values": ["A", "B"]}],
        })

    def _compile(self, method: str):
        dim = self._dim()
        dim.stimulus_field = "t"
        req = ConstraintRequest(theme_key="TH", method=method, dims=[dim],
                                ports=[{"name": "agent"}])
        return compile_assignments(req)

    def test_random_method_uses_random_mode(self):
        rows = self._compile("RND")
        assert rows and rows[0]["mode"] == "random"

    def test_directed_method_uses_cycle_mode(self):
        rows = self._compile("D")
        assert rows and rows[0]["mode"] == "cycle"

    def test_empty_method_matches_v1_fallback(self):
        rows = self._compile("")
        assert rows and rows[0]["mode"] == "cycle"
