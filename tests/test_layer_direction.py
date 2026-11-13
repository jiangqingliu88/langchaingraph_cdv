"""分层依赖方向 —— 把"注意别反向 import"从注释变成**会红的测试**。

真实规则不是线性链
    注释里偶尔写成 `l1 ← l2 ← l3 ← l4 ← l5`，但**代码不是那样长的**：
    编排层（L2）必须调决策引擎（L3）、必须落库（L4）、必须读蒸馏权重（L5）
    —— 那 50 多处 `L2 → L3/L4/L5` 里绝大多数是**结构必需**，不是债。
    把它当违规去"修"，只会把装配逻辑拆成一层层回调，换来零收益。

    所以这里编码的是**能站住的那几条**，每条都有依据：

      1. **L1 不得向上 import 任何层**
         依据：`docs/design/full_project_refactoring_plan.md:193` 把
         「L1 向上 import」明确叫**依赖方向倒置**。L1 是零 AI 的确定性层，
         反了的话它就没法脱离编排/记忆层单独跑 —— 而它恰恰是最该能单独测的。

      2. **L4（记忆）不得 import L2 / L3 / L5**
         它是被全员依赖的**底座**。底座向上伸手，依赖图就会出现环。

      3. **L3（决策）不得 import L5（进化）**
         越级。决策引擎全是确定性规则，本来就不该知道"进化层"存在 ——
         经验查询是**注入**的（见 `ExperienceProvider`）。

      4. **L5（进化）不得 import L2 / L3**
         它读记忆、产权重，不驱动编排。

    L2 不限 —— 它是装配者，它的职责就是知道下面所有层。

为什么用 AST 而不是 grep
    静态 grep 会被**字符串里的模块名**骗到（注释、docstring、日志文案里
    都出现过 `src.layers.lX_...`）。AST 只看真正的 import 语句。
"""
from __future__ import annotations

from pathlib import Path

import pytest

# **规则与扫描只有一份** —— 启动期守卫（`src/layers/_bootstrap.py`）与这里
# 共用同一套（见那个模块的 docstring）。原来这套逻辑长在本文件里，于是
# 生产进程没有启动期检查：拆模块时得等 CI 跑完八百多个用例才发现漏了注入。
from src.layers._bootstrap import (
    FORBIDDEN,
    LAYER_NAMES as LAYER_RE,
    ORDER,
    default_root,
    layer_violations as _violations,
)

LAYERS = default_root() / "src" / "layers"


def test_layers_exist_as_documented():
    """层名改了这个文件就得跟着改 —— 否则下面的规则会静默失效。

    这是"守卫的守卫"：`FORBIDDEN` 的键或值拼错一个字母，
    `test_no_forbidden_imports` 会变成一条永远绿的假测试。
    """
    for name in LAYER_RE:
        assert (LAYERS / name).is_dir(), f"缺少分层目录 {name}"
    for owner, targets in FORBIDDEN.items():
        assert owner in ORDER, f"FORBIDDEN 里的 {owner!r} 不是已知层"
        for t in targets:
            assert t in ORDER, f"FORBIDDEN[{owner!r}] 里的 {t!r} 不是已知层"


def test_no_forbidden_imports():
    """违规清单为空。**不为空时逐条打印** —— 光说"有 3 处"没法定位。"""
    bad = _violations()
    if bad:
        lines = [f"  {f}:{n}  {owner} → {target}" for f, n, owner, target in bad]
        pytest.fail(
            f"{len(bad)} 处被禁的跨层 import：\n" + "\n".join(lines)
            + "\n\n修法：把被依赖的东西**注入**进来（见 GuardianAgent / "
              "InfrastructureManager / ExperienceProvider 三处先例），"
              "而不是在函数体里延迟 import 把违规藏起来。"
        )


def test_l1_is_importable_on_its_own():
    """L1 必须能在**不拖进上层**的前提下被 import。

    这条比"没有那几行 import"更本质：它保证 L1 真的能脱离 langgraph /
    agent 注册表 / SQLAlchemy 单独跑 —— 那正是"零 AI 确定性层"这句话的
    可执行含义。用子进程验，因为同进程里 `sys.modules` 已被别处污染。
    """
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import src.layers.l1_infrastructure.infrastructure\n"
        "bad = [m for m in sys.modules if m.startswith('src.layers.') "
        "and not m.startswith('src.layers.l1_')]\n"
        "print(sorted(bad))\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    assert r.returncode == 0, r.stderr
    pulled = r.stdout.strip()
    assert pulled == "[]", f"导入 L1 时拖进了上层模块：{pulled}"


class TestTheStartupGuardUsesTheSameRules:
    """启动期守卫（`src/layers/_bootstrap.py`）与这里的 pytest 检查**同一套规则**。

    ## 为什么要有它

    pytest 那条是**事后**防线：跑测试时能拦，但生产进程 import 成功就起飞了。
    拆模块时改坏了依赖方向，要等 CI 跑完八百多个用例才发现 —— 那时人早忘了
    自己动过什么。所以加一道启动期的：`python -m src.interfaces.cli...` 冷启动就扫一遍。

    ## 这里钉什么

    钉的是**两边真的共用一份逻辑**（不是各写一遍）：`layer_violations` 在
    `_bootstrap` 里，本文件的 `_violations` 就是它。这条从 import 就能看出来，
    但更要紧的是下面几条 —— 守卫**真的会拦**，且拦得准。
    """

    def _fake_repo(self, tmp_path, rel_path: str, body: str):
        """造一个最小仓库：`<root>/src/layers/l1_infrastructure/…`。"""
        target = tmp_path / "src" / "layers" / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        return tmp_path

    def test_the_real_repo_is_clean(self):
        from src.layers._bootstrap import ensure_layer_contract

        assert ensure_layer_contract() == []

    def test_a_top_level_violation_raises_with_the_file_and_line(self, tmp_path):
        from src.layers._bootstrap import LayerViolationError, ensure_layer_contract

        root = self._fake_repo(tmp_path, "l1_infrastructure/bad.py",
                               "from src.layers.l2_orchestration.graph import X\n")
        with pytest.raises(LayerViolationError) as info:
            ensure_layer_contract(root)
        assert "l1_infrastructure/bad.py:1" in str(info.value)
        assert "l1_infrastructure → l2_orchestration" in str(info.value)
        assert len(info.value.violations) == 1

    def test_a_lazy_import_inside_a_function_is_not_a_static_edge(self, tmp_path):
        """函数内的延迟 import **不算静态依赖**（与 `architecture_guard` 同口径）。

        3.0 迁移用函数内加载切断了几条 L1→L2 / L5→L3 的边（回归适配、闭环动作）。
        若启动守卫仍按整棵树扫，CLI 会在第一条命令前被自己的守卫拦死 ——
        实测踩过。判定"这是不是静态边"只看**模块级** import。
        """
        from src.layers._bootstrap import ensure_layer_contract

        root = self._fake_repo(
            tmp_path, "l1_infrastructure/sneaky.py",
            "def helper():\n"
            "    # 运行时才加载：不在模块图上形成静态边\n"
            "    from src.knowledge.lineage import LineageStore\n"
            "    return LineageStore\n")
        assert ensure_layer_contract(root) == []

    def test_a_mention_in_a_comment_is_not_a_violation(self, tmp_path):
        """注释里提一句模块名**不算** —— 这个仓库的注释特别爱举例，
        真去拦就会满屏假违规，然后没人再当它回事。"""
        from src.layers._bootstrap import ensure_layer_contract

        root = self._fake_repo(
            tmp_path, "l1_infrastructure/chatty.py",
            "# 这里**不能** import src.layers.l2_orchestration.state\n"
            '"""docstring 里也提一句 src.layers.l3_decision.decision_engine。"""\n'
            "x = 1\n")
        assert ensure_layer_contract(root) == []

    def test_the_allowed_direction_is_not_flagged(self, tmp_path):
        """**L2 是装配者**：它调 L3/L4/L5 是结构必需，不是债 —— 别把它当违规。"""
        from src.layers._bootstrap import ensure_layer_contract

        root = self._fake_repo(
            tmp_path, "l2_orchestration/assembler.py",
            "from src.layers.l3_decision.decision_engine import decide\n"
            "from src.knowledge.lineage import LineageStore\n"
            "from src.experience.distillation import distill\n")
        assert ensure_layer_contract(root) == []
