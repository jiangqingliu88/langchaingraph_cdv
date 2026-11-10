"""executor 角色 ↔ 工具模块 —— 白名单**真的**在筛，不是每次回退到全部。

## 这里防的是哪一种事故

工具注册时绑的是**模块名**（`assert` / `spec` / `uvm` …），而调用方给的是
**executor 角色**（`verify` / `design` / `ops` …）。两套名字之间原先没有桥，
于是 8 个 executor 里只有 `coverage` / `debug` 两个碰巧同名，**其余每次**
都走"没有绑定 → 回退到 hub 里全部工具（含 WRITE / DANGER）"。

"回退到全部"至少还会 warning，不至于静默；但它让白名单形同虚设 ——
一个只该读 spec 的 `design`，手里握着 `write_file` 和 `regression.run`。

## 为什么必须用测试钉住这张表

因为**它没法从代码里自证**：表写错了（漏一个模块、写个不存在的模块名、
或者把某个 executor 想当然填成空）都不会报错 —— 表现只是"某个 agent 忽然
拿不到工具"或"某个 agent 又多拿了几个"。两条防线：

  · 填的模块名**必须真实存在**（`_by_agent` 里有那个键）—— 防手滑写成
    `assertion` 而实际键是 `assert`（那样会静默取到 0 个工具）；
  · 表里的角色**必须覆盖仓库里全部 executor**（从 `executors/` 目录读）——
    新加一个 executor 却忘了登记，就会走回退拿到全部工具。

还有一条**回归**断言：`ops`。模块角色里也有个叫 `ops` 的（挂着
`regression.run` / `coverage.collect` / `regression.reference_finder`，
正是这个 executor 的本职工具）—— 迁移时按"executor 名 == 模块名"把它归零
就会**悄悄拿走**那三个工具。这条钉住"别名不同源时别想当然"。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.layers.l2_orchestration.communication.tool_hub import ToolHub


@pytest.fixture(scope="module")
def hub():
    h = ToolHub()
    h.bootstrap()
    return h


def _executor_roles() -> set:
    """仓库里实际存在的 executor 角色 —— 从目录名读，不手写清单。"""
    d = Path(__file__).resolve().parents[1] / "src" / "skills"
    return {p.name for p in d.iterdir()
            if p.is_dir() and (p / "main.py").is_file()}


class TestEveryExecutorIsInTheTable:
    def test_no_executor_is_missing(self):
        """**新加一个 executor 忘了登记** → 它会走回退拿到全部工具。

        这条从目录读角色，所以新目录一出现就会红。
        """
        table = ToolHub.EXECUTOR_TOOL_MODULES
        missing = sorted(_executor_roles() - set(table))
        assert not missing, (
            f"这些 executor 不在 `EXECUTOR_TOOL_MODULES` 里：{missing} —— "
            f"它们会回退到**全部**工具（含 WRITE/DANGER）。"
            f"确实不用工具的填空元组 `()`（那是「就是没有」，与「没查到」不同）。"
        )

    def test_no_phantom_executor_in_the_table(self):
        """反向：表里不该有已经删掉的 executor —— 那是死条目。"""
        ghosts = sorted(set(ToolHub.EXECUTOR_TOOL_MODULES) - _executor_roles())
        assert not ghosts, f"这些角色已经不是 executor 了：{ghosts}"


class TestEveryMappedModuleExists:
    def test_mapped_modules_are_real_registration_keys(self, hub):
        """表里写的模块名必须是**注册时真的用过**的键。

        写成 `assertion` 而实际是 `assert` 不会报错 —— `_by_agent.get()` 返回 `[]`，
        那个 executor 静默拿到 0 个工具。
        """
        known = set(hub._by_agent)
        bad = {}
        for role, modules in ToolHub.EXECUTOR_TOOL_MODULES.items():
            unknown = [m for m in modules if m not in known]
            if unknown:
                bad[role] = unknown
        assert not bad, (
            f"这些模块名在 `_by_agent` 里不存在（写错就会静默取 0 个工具）：{bad}。"
            f"实际登记过的模块：{sorted(known)}"
        )

    def test_a_non_empty_mapping_actually_yields_tools(self, hub):
        """填了模块却一个工具都没取到 —— 说明映射写歪了（多半是名字拼错）。

        与上一条的区别：上一条查键存不存在，这条查"取出来的东西非空"。
        """
        empty = []
        for role, modules in ToolHub.EXECUTOR_TOOL_MODULES.items():
            if modules and not hub._tool_names_for(role):
                empty.append(role)
        assert not empty, f"这些 executor 填了模块但取到 0 个工具：{empty}"


class TestTheKnownCases:
    def test_an_unknown_role_returns_none_so_the_caller_can_warn(self, hub):
        """不认识的角色 → `None`（**不是空列表**）—— 调用方据此决定回退并出声。

        返回空列表会被当成"声明了不用工具"，于是新角色静默拿不到任何工具 ——
        比回退到全部更坏（后者至少能用）。
        """
        assert hub._tool_names_for("definitely_not_an_executor") is None

    def test_ops_keeps_its_regression_tools(self, hub):
        """**回归**：`ops` executor 靠同名巧合拿到了模块角色 `ops` 的三个工具。

        模块 `ops` 挂的是 `regression.run` / `coverage.collect` /
        `regression.reference_finder` —— 正是这个 executor 的本职。迁移时按
        "executor 名 == 模块名，所以不用映射"把它填成 `()`，就会**悄悄拿走**它们。
        （`ops/main.py` 的 `_get_tools()` 返回 `[]`，光看那儿是看不出来的。）
        """
        names = hub._tool_names_for("ops")
        assert names is not None
        assert "regression.run" in names, (
            "ops 的回归工具丢了 —— 别把它按「executor 名 == 模块名」归零"
        )

    def test_declared_no_tool_executors_get_exactly_nothing(self, hub):
        """`front` / `model` / `audit` 的 `_get_tools()` 就是 `[]` —— 精确取空，
        **不回退**。这是收紧的重点：它们此前每次拿到全部工具。"""
        for role in ("front", "model", "audit"):
            assert hub._tool_names_for(role) == [], role

    def test_verify_gets_uvm_and_assertion_tools_not_everything(self, hub):
        """`verify` 实测用的就是这两类的工具 —— 不该拿到 `write_file` 以外的一大堆。"""
        names = set(hub._tool_names_for("verify"))
        assert "find_spec_yaml" in names and "jinja_render" in names   # uvm
        assert "generate_sva_assertions" in names                      # assert
        assert len(names) < len(hub._tools), "verify 拿到了全部工具 —— 白名单没生效"
