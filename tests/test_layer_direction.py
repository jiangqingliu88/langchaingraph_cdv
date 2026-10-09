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

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Tuple

import pytest

LAYERS = Path("src/layers")
LAYER_RE = "l1_infrastructure", "l2_orchestration", "l3_decision", "l4_memory", "l5_evolution"

#: 层名 → 序号（1 最底）。**序号只用于报错时排序，不表达依赖方向**。
ORDER: Dict[str, int] = {name: i + 1 for i, name in enumerate(LAYER_RE)}

#: 每个层**不许**import 哪些层（键是"谁"，值是"不许碰谁"）。
#: 没列出来的层不受限 —— 见模块头。
FORBIDDEN: Dict[str, Tuple[str, ...]] = {
    # L1 是底，不能向上伸手
    "l1_infrastructure": ("l2_orchestration", "l3_decision", "l4_memory", "l5_evolution"),
    # 记忆层是底座
    "l4_memory": ("l2_orchestration", "l3_decision", "l5_evolution"),
    # 决策层不得越级到进化层（经验查询走注入）
    "l3_decision": ("l5_evolution",),
    # 进化层读记忆、产权重，不驱动编排
    "l5_evolution": ("l2_orchestration", "l3_decision"),
    # l2_orchestration 不限：它是装配者
}


def _layer_of(path: Path) -> str:
    parts = path.relative_to(LAYERS).parts
    return parts[0] if parts and parts[0] in ORDER else ""


def _imported_layers(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """文件里出现的 `src.layers.lX_*` import → (行号, 层名)。

    同时认 `import a.b.c` 与 `from a.b import c`；也认相对 import 之外的
    绝对形式（本仓库统一用绝对 import）。
    """
    for node in ast.walk(tree):
        mods: List[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        for mod in mods:
            for name in LAYER_RE:
                if f"src.layers.{name}" in mod:
                    yield node.lineno, name


def _violations() -> List[Tuple[str, int, str, str]]:
    """[(文件, 行号, 归属层, 被反向依赖的层)]。"""
    out: List[Tuple[str, int, str, str]] = []
    for path in sorted(LAYERS.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        owner = _layer_of(path)
        if not owner or owner not in FORBIDDEN:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                       # 语法错的文件由别的测试管
            continue
        for lineno, target in _imported_layers(tree):
            if target in FORBIDDEN[owner] and target != owner:
                rel = path.relative_to(LAYERS).as_posix()
                out.append((rel, lineno, owner, target))
    return out


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
