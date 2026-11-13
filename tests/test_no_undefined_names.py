"""静态查「用到了却既没定义也没 import」的名字 —— 拆文件的专属陷阱。

为什么需要这条
    把 `graph.py` 拆成 `nodes/` + `routers.py` + `runtime.py` 之后，有一类 bug
    **整个测试套件都抓不到**：

        routers.py  里 `r_after_round_bump` 调 `_have_rounds_left`
        rounds.py   里才定义它
        → 忘了 import ⇒ `NameError`

    为什么测试抓不到：
      · `NODE_FUNCS` / `NODE_NAMES` 导入正常（那只是**收集**函数对象）
      · 单元测试**构造**图也不碰这些函数体
      · 这些名字只在**图真的跑起来**、走到那个节点/条件边时才求值

    实测就是这么发现的 —— 跑 `vagent verify` 端到端，跑到 `round_bump` 才炸。
    Python 的 NameError 是运行期的，而"拆文件漏 import"是**静态**问题，
    所以用静态检查堵它，比对每个分支写一条端到端用例便宜得多。

为什么不用 grep
    会被注释和 docstring 里的名字骗到（这个仓库里真的出现过）。

覆盖范围
    `graph.py` 拆出来的那几个模块。**新拆出来的文件请加进 `WATCHED`** ——
    不监控的文件，这条测试对它等于不存在。
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path
from typing import List, Set, Tuple

import pytest

ROOT = Path("src/runtime_plane/l2_orchestration")

#: 要监控的模块 —— `graph.py` 拆出来的那几个（以及 graph.py 自己）
WATCHED: Tuple[Path, ...] = (
    ROOT / "graph.py",
    ROOT / "routers.py",
    ROOT / "runtime.py",
    ROOT / "nodes" / "pure" / "lifecycle.py",
    ROOT / "nodes" / "pure" / "rounds.py",
    ROOT / "nodes" / "pure" / "converge.py",
    ROOT / "nodes" / "pure" / "approval.py",
    ROOT / "nodes" / "pure" / "apply.py",
    ROOT / "nodes" / "agent" / "build.py",
    ROOT / "nodes" / "agent" / "run.py",
    ROOT / "nodes" / "agent" / "fix.py",
    ROOT / "nodes" / "agent" / "signoff.py",
)

_BUILTINS = set(dir(builtins))


def _module_dir(path: Path) -> Path:
    return path.parent


def _sibling_names(path: Path) -> Set[str]:
    """同目录兄弟模块里定义的名字 —— 给报错时提示"是不是该 import 它"。"""
    names: Set[str] = set()
    for other in _module_dir(path).glob("*.py"):
        if other == path or other.name == "__init__.py":
            continue
        try:
            tree = ast.parse(other.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
    return names


def _bound_names(tree: ast.AST) -> Set[str]:
    """本文件里**所有层级**上被绑定过的名字：import / 赋值 / 参数 / 类与函数名。

    必须扫全层级 —— 这个仓库大量用函数内延迟 import，只看模块级会把它们
    全判成"缺失"（第一版就误报了四十多条）。
    只出现一次就算绑定：**重复绑定不是这里的关注点**（那是 linter 的事）。
    """
    bound: Set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                bound.add(a.asname or a.name.split(".")[0])
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            bound.add(n.id)
        elif isinstance(n, ast.ClassDef):
            bound.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(n.name)
            _add_args(n.args, bound)
        elif isinstance(n, ast.Lambda):
            _add_args(n.args, bound)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.withitem,)) and n.optional_vars is not None:
            for x in ast.walk(n.optional_vars):
                if isinstance(x, ast.Name):
                    bound.add(x.id)
        elif isinstance(n, (ast.comprehension,)) and isinstance(n.target, ast.Name):
            bound.add(n.target.id)
    return bound


def _add_args(args: ast.arguments, bound: Set[str]) -> None:
    for a in (args.args + args.posonlyargs + args.kwonlyargs):
        bound.add(a.arg)
    if args.vararg:
        bound.add(args.vararg.arg)
    if args.kwarg:
        bound.add(args.kwarg.arg)


def _annotation_only_names(tree: ast.AST) -> Set[str]:
    """只出现在**注解**里的名字。

    `from __future__ import annotations` 之下注解不求值 —— 缺 import 也不会
    运行期炸，所以单独报、不算失败（但会提示该修）。
    """
    out: Set[str] = set()
    for n in ast.walk(tree):
        ann = None
        if isinstance(n, ast.arg):
            ann = n.annotation
        elif isinstance(n, ast.AnnAssign):
            ann = n.annotation
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ann = n.returns
        if ann is not None:
            for x in ast.walk(ann):
                if isinstance(x, ast.Name):
                    out.add(x.id)
    return out


def _undefined(path: Path) -> Tuple[List[str], List[str]]:
    """→ (运行时会炸的缺失名, 仅注解的缺失名)。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bound = _bound_names(tree) | _BUILTINS
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    missing = used - bound
    annot = _annotation_only_names(tree) & missing
    return sorted(missing - annot), sorted(annot)


@pytest.mark.parametrize("path", WATCHED, ids=lambda p: p.name)
def test_no_undefined_names(path: Path):
    """每个被监控的模块里，不许有"用了却没绑定"的名字。"""
    if not path.exists():
        pytest.skip(f"{path} 不存在（模块被挪走了？请同步 WATCHED）")

    real, annot_only = _undefined(path)
    if real:
        hints = []
        for name in real:
            if name in _sibling_names(path):
                hints.append(f"{name}（同目录兄弟模块里有同名定义 —— 是不是该 import 它？）")
            else:
                hints.append(name)
        pytest.fail(
            f"{path} 里 {len(real)} 个名字用到了却没定义/没 import：\n  "
            + "\n  ".join(hints)
            + "\n\n拆文件时最容易漏这个：**单元测试构造图不碰函数体**，"
              "要等图真的跑到那个节点才 NameError。"
        )
    # 仅注解的：不求值、无害，但多半也是漏 import —— 记一条不在失败里报
    if annot_only:
        pytest.skip(f"{path}: 仅注解里缺失（无害，但建议补 import）：{annot_only}")


def test_the_watched_list_actually_covers_the_split():
    """守卫的守卫：拆出来的模块必须都在 `WATCHED` 里。

    漏一个，这条测试对那个文件就等于不存在 —— 那正是它要防的。
    """
    on_disk = {ROOT / "routers.py", ROOT / "runtime.py"}
    on_disk |= set((ROOT / "nodes").rglob("*.py"))
    watched = {p for p in WATCHED}
    missing = {p for p in on_disk if p.name != "__init__.py"} - watched
    assert not missing, (
        f"这些模块没被监控：{sorted(str(p) for p in missing)}\n"
        f"把它们加进 WATCHED —— 不监控 = 这条测试对它们不存在。"
    )
