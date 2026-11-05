"""分层依赖的守卫 —— **规则与扫描一处定义**，测试与启动期共用。

## 为什么要有这个文件（而不是只留在测试里）

`tests/test_layer_direction.py` 一直是这件事的事后防线：跑 pytest 时能拦住
被禁的跨层 import。但**生产进程 import 成功就起飞了** —— 开发者拆模块时，
要等到 CI 跑完八百多个用例才会发现漏了注入，而那时人早忘了自己动过什么。

所以把规则和 AST 扫描搬到这里，两边共用：

    tests/test_layer_direction.py   pytest 期（全量、含子进程那条贵检查）
    src/layers/_bootstrap.py        CLI 启动期（只做这一条，<0.5s）

**不重复造轮子**：扫描逻辑（`layer_violations`）只有这一份，测试 import 它。

## 为什么扫 AST 而不是 grep 字符串

注释、文档串里也会出现 `src.layers.lX_...`（这个仓库的注释很爱举例），
grep 会把它们当成违规。AST 只看真正的 import 语句 —— 而且**函数体里的延迟
import 不算静态依赖**（与 `config/architecture_guard.py` 同一口径）—— 3.0
迁移用函数内加载切断了几条 L1→L2 / L5→L3 的静态边；启动期守卫若按整棵树扫，
会把这些有意为之的延迟加载当成违规，把 CLI 在第一条命令前自锁。
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

#: 层目录名（按从底到顶）。
LAYER_NAMES: Tuple[str, ...] = (
    "l1_infrastructure", "l2_orchestration", "l3_decision", "l4_memory", "l5_evolution",
)

#: 层名 → 序号（1 最底）。**序号只用于报错时排序，不表达依赖方向**。
ORDER: Dict[str, int] = {name: i + 1 for i, name in enumerate(LAYER_NAMES)}

#: 每个层**不许** import 哪些层（键是「谁」，值是「不许碰谁」）。
#: 没列出来的层不受限 —— `l2_orchestration` 是**装配者**，它必须调 L3/L4/L5。
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


class LayerViolationError(RuntimeError):
    """启动期发现被禁的跨层 import。**带着清单抛** —— 光说"有 3 处"没法定位。"""

    def __init__(self, violations: List[Tuple[str, int, str, str]]):
        self.violations = violations
        lines = [f"  {f}:{n}  {owner} → {target}" for f, n, owner, target in violations]
        super().__init__(
            f"{len(violations)} 处被禁的跨层 import：\n" + "\n".join(lines)
            + "\n\n修法：把被依赖的东西**注入**进来（见 GuardianAgent / "
              "InfrastructureManager / ExperienceProvider 三处先例），"
              "而不是在函数体里延迟 import 把违规藏起来。")


def default_root() -> Path:
    """本模块所在仓库的根 —— `src/layers/_bootstrap.py` 往上三级。"""
    return Path(__file__).resolve().parents[2]


def _layer_of(path: Path, layers_root: Path) -> str:
    rel = path.relative_to(layers_root)
    return rel.parts[0] if rel.parts and rel.parts[0] in ORDER else ""


def _imported_layers(tree: ast.AST) -> Iterator[Tuple[int, str]]:
    """**模块级** `src.layers.lX_*` import → (行号, 层名)。

    同时认 `import a.b.c` 与 `from a.b import c`；本仓库统一用绝对 import。
    函数体内的延迟 import 不算静态依赖（与 `config/architecture_guard.py`
    同一口径，见模块头）。
    """
    for node in tree.body:
        mods: List[str] = []
        if isinstance(node, ast.ImportFrom) and node.module:
            mods.append(node.module)
        elif isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        for mod in mods:
            for name in LAYER_NAMES:
                if f"src.layers.{name}" in mod:
                    yield node.lineno, name


def layer_violations(root: Optional[Path] = None) -> List[Tuple[str, int, str, str]]:
    """扫一遍 `src/layers/**/*.py` → `[(文件, 行号, 归属层, 被反向依赖的层)]`。

    `root` 缺省用 `default_root()`（从本文件推仓库根）—— 所以**从任何 cwd
    调用都对**，不像原来那样依赖"恰好站在仓库根"。
    """
    base = Path(root) if root else default_root()
    layers_root = base / "src" / "layers" if (base / "src" / "layers").is_dir() else base
    out: List[Tuple[str, int, str, str]] = []
    for path in sorted(layers_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        owner = _layer_of(path, layers_root)
        if not owner or owner not in FORBIDDEN:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                       # 语法错的文件由别的测试管
            continue
        for lineno, target in _imported_layers(tree):
            if target in FORBIDDEN[owner] and target != owner:
                out.append((path.relative_to(layers_root).as_posix(),
                            lineno, owner, target))
    return out


def ensure_layer_contract(root: Optional[Path] = None) -> List[Tuple[str, int, str, str]]:
    """启动期调一次：有违规就抛 `LayerViolationError`，干净则返回空列表。

    **代价**：扫的是 `src/layers` 下约 122 个文件、29k 行，`ast.parse` 量级
    —— 单次远小于 1 秒，作为冷启动的一次性开销可接受（不做缓存：缓存失效的
    那天会变成"改了却拦不住"，比多花半秒糟得多）。

    **不做** `test_l1_is_importable_on_its_own` 那条（它拉子进程验证 L1 能单独
    import）—— 启动期跑子进程太贵，留给 pytest。
    """
    violations = layer_violations(root)
    if violations:
        raise LayerViolationError(violations)
    return violations
