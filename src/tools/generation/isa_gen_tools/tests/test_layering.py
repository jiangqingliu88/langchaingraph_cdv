"""分层守卫 —— 把仓库的硬规矩变成**会红的测试**，而不是注释里的愿望。

规矩（`docs/design/tool_layer_architecture.md` §4.1）：

    1. `src/tools/**` 不得 import langchain / PySide6 / src.layers / src.agents
    2. `src/tools/X_tools/` 不得 import `src/tools/Y_tools/`（Y ≠ X）
    3. 每个工具只有一个公开实现入口：`api.py` 的 `run_*`
    4. 面不许包含语义

第 1、2 条用子进程真 import 一次来验 —— 静态 grep 会被字符串里的名字骗到。
第 3 条在 M6（api 落地）时补。

**为什么必须机械化**：这套规矩在仓库里写在三处注释里，而此前只有一个包
（旧建模引擎）真的守住了它。注释不会在半年后拦住谁，测试会。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
PACKAGE = "src.tools.generation.isa_gen_tools"


def _import_probe(code: str) -> str:
    """在**子进程**里 import 一次，打印出混进来的模块名。

    子进程而不是当前进程：一旦 import 成功，模块就留在 `sys.modules` 里，
    同一次 pytest 会话里后面的用例看到的都是污染过的状态。
    """
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=str(REPO_ROOT),
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


class TestHardRule1NoHeavyImports:
    @pytest.mark.parametrize("forbidden", ["langchain", "PySide6", "src.layers",
                                           "src.agents"])
    def test_importing_domain_pulls_in_nothing_heavy(self, forbidden):
        """领域层必须能在不装 Qt / 不装 langchain 的环境里单独跑。

        这不是洁癖：工具层要能被脚本、别的工具、CI 直接 import，
        而它一旦拖进 LLM 客户端或界面框架，就再也脱不开了。
        """
        code = (
            "import sys\n"
            f"import {PACKAGE}.domain\n"
            "bad = [m for m in sys.modules if m.startswith('{}')]\n"
            "print(bad)\n").format(forbidden)
        assert _import_probe(code) == "[]"

    def test_importing_the_package_itself_is_light(self):
        """包根也不许有副作用 import —— `__init__` 只能 re-export。"""
        code = (
            "import sys\n"
            f"import {PACKAGE}\n"
            "bad = [m for m in sys.modules\n"
            "       if m.startswith(('langchain', 'PySide6', 'src.layers',\n"
            "                         'src.agents'))]\n"
            "print(bad)\n")
        assert _import_probe(code) == "[]"


class TestHardRule2NoCrossToolImports:
    def test_domain_does_not_import_another_tool(self):
        """工具之间只能有文件格式契约，不能有 import。

        真依赖上了的话，"换一个工具"会变成"改一堆工具" —— 这个仓库
        已经出现过（`cmodel_tools` import `uvm_tools.gen_uvm`）。
        """
        board = PACKAGE.rsplit(".", 1)[0]      # src.tools.generation
        code = (
            "import sys\n"
            f"import {PACKAGE}.domain\n"
            "bad = [m for m in sys.modules if m.startswith('src.tools.')\n"
            f"       and not m.startswith('{PACKAGE}')\n"
            f"       and m != '{board}']\n"      # 板块父包是合法前缀
            "print(bad)\n")
        assert _import_probe(code) == "[]"


class TestNoForbiddenSourcePatterns:
    """源码级的守卫：有些东西不该出现在任何文件里。"""

    @staticmethod
    def _python_files():
        """被测的源码文件。

        **排除本文件自己** —— 它必须写出那些被禁的名字才能检索它们
        （否则等于用一个空的针去找刺）。守卫只管**发出去的那个包**，
        测试里提到 "PySide6" 这个词本身不是问题。
        """
        root = REPO_ROOT / "src" / "tools" / "generation" / "isa_gen_tools"
        return [p for p in root.rglob("*.py")
                if "__pycache__" not in p.parts and p.name != "test_layering.py"]

    #: 不许出现在 import 里的顶层模块名
    FORBIDDEN_MODULES = ("PySide6", "langchain", "langchain_core",
                         "langchain_openai", "langchain_community")

    @classmethod
    def _imports_of(cls, path: Path):
        """文件里**真正 import 了**哪些模块 —— 走 AST，不做字符串匹配。

        用字符串匹配会栽在一个很日常的地方：**文档字符串里提到某个名字
        不算 import**。第一版就是这么写的，于是 `api.py` 的第一句话
        "不 import langchain / ToolHub / Qt" 把守卫自己触发了。
        守卫要查的是行为，不是字面量。
        """
        import ast
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                found.add(node.module)
        return found

    def test_no_qt_or_llm_imports_in_source(self):
        offenders = []
        for path in self._python_files():
            for module in self._imports_of(path):
                root = module.split(".")[0]
                if root in self.FORBIDDEN_MODULES:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {module}")
        assert not offenders, "工具层不许出现界面/LLM 依赖：\n" + "\n".join(offenders)

    def test_the_guard_would_actually_catch_something(self):
        """守卫本身要验一下 —— 一条永远返回空的检查比没有检查更糟。

        临时造一个带违禁 import 的文件，确认它会被抓出来，然后删掉。
        """
        root = REPO_ROOT / "src" / "tools" / "generation" / "isa_gen_tools"
        bait = root / "_layering_bait.py"
        bait.write_text("import PySide6  # 故意违规\n", encoding="utf-8")
        try:
            caught = [m for m in self._imports_of(bait)
                      if m.split(".")[0] in self.FORBIDDEN_MODULES]
            assert caught == ["PySide6"]
        finally:
            bait.unlink()

    def test_a_mention_in_a_docstring_is_not_an_import(self, tmp_path):
        """回归：守卫曾经把文档字符串里的一句话当成违规 import。"""
        bait = tmp_path / "bait.py"
        bait.write_text('"""本工具不 import langchain，也不用 PySide6。"""\n',
                        encoding="utf-8")
        assert not [m for m in self._imports_of(bait)
                    if m.split(".")[0] in self.FORBIDDEN_MODULES]

    def test_no_hardcoded_absolute_paths(self):
        """硬编码本机路径会毁掉可复现性（仓库里已经有三处 questasim 的硬编码）。"""
        import re
        pattern = re.compile(r"[A-Za-z]:[\\/](?:python|questasim|Users)", re.I)
        offenders = [str(p.relative_to(REPO_ROOT)) for p in self._python_files()
                     if pattern.search(p.read_text(encoding="utf-8"))]
        assert not offenders, f"硬编码本机路径：{offenders}"


class TestPackageShape:
    """§4.2 模板要求的目录 —— 缺了就是没按模板来。"""

    def test_required_directories_exist(self):
        root = REPO_ROOT / "src" / "tools" / "generation" / "isa_gen_tools"
        for name in ("domain", "schema", "tests"):
            assert (root / name).is_dir(), f"缺目录 {name}/"

    def test_domain_has_no_upward_imports(self):
        """`domain` 不 import 本包其它层 —— 这是 domain/__init__.py 里写的规矩。"""
        domain = REPO_ROOT / "src" / "tools" / "generation" / "isa_gen_tools" / "domain"
        offenders = []
        for path in domain.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for layer in (".repository", ".compile", ".analysis", "repository.",
                          "compile.", "analysis."):
                if f"from ..{layer}" in text or f"from .{layer}" in text:
                    offenders.append(f"{path.name}: {layer}")
        assert not offenders, f"domain 往上 import 了：{offenders}"
