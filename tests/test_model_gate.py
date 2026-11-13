"""参考模型的本地编译门禁（`ModelExecutor._verify_model`）。

**为什么在根 `tests/` 而不是 `src/generation/design/cmodel/tests/`**：`src/engine/stages/` 下没有
tests 目录，agent 的测试一直放在根 `tests/`（见 `tests/test_agents.py`）。

**环境守卫**：`src/layers/l2_orchestration/executors/base.py` 在模块级 import
langchain，所以只要 langchain 栈不完整，这个文件根本 import 不进来 —— 那会让整套
测试变成 collection error 而不是一条清楚的 skip。下面用 `importorskip` 挡住。

钉的是三件事：
  · **编不过 ≠ 判不了**：vlog 缺失时是 BLOCKED_EDA_MISSING（如实标注、照常推进），
    不是 FAIL（那会把没装 EDA 的环境里每一步模型生成都误杀）；
  · 非 HDL 模型（python / cpp）各有各的说法，**不冒充通过**；
  · python 走 stdlib 语法检查，坏了就报行号。
"""
from __future__ import annotations

import pytest

pytest.importorskip("langchain_classic", reason="langchain 栈不完整，agent 模块无法导入")

from src.generation.design.cmodel.main import ModelExecutor  # noqa: E402

_V = ModelExecutor._verify_model


class TestPythonModels:
    def test_valid_python_passes(self, tmp_path):
        result = _V(tmp_path, "dut", "python", "class R:\n    def reset(self):\n        return 0\n")
        assert result["status"] == "PASS"

    def test_syntax_error_fails_with_line_number(self, tmp_path):
        result = _V(tmp_path, "dut", "python", "def broken(:\n")
        assert result["status"] == "FAIL"
        assert "行" in result["detail"]


class TestNonHdlModels:
    def test_cpp_is_skipped_not_passed(self, tmp_path):
        """cpp 没有保证存在的本地编译器 —— 如实标 SKIPPED，不说"通过"。"""
        result = _V(tmp_path, "dut", "cpp", "int f(){return 0;}")
        assert result["status"] == "SKIPPED"
        assert "不冒充通过" in result["detail"]


class TestHdlModels:
    def test_missing_eda_is_blocked_not_failed(self, tmp_path, monkeypatch):
        """本机没装 vlog 时**判不了** —— 必须是 BLOCKED，不能是 FAIL。"""
        import shutil
        monkeypatch.setattr(shutil, "which", lambda name: None)
        result = _V(tmp_path, "dut", "systemverilog", "module m; endmodule\n")
        assert result["status"] == "BLOCKED_EDA_MISSING"
        assert "vlog" in result["detail"]
        assert result["errors"] == 0

    def test_verilog_uses_the_same_gate(self, tmp_path, monkeypatch):
        import shutil
        monkeypatch.setattr(shutil, "which", lambda name: None)
        result = _V(tmp_path, "dut", "verilog", "module m; endmodule\n")
        assert result["status"] == "BLOCKED_EDA_MISSING"

    def test_compiler_rejection_is_a_failure(self, tmp_path, monkeypatch):
        """有 vlog 且编译不过 → FAIL（这一步就是失败的）。"""
        import shutil

        class _FakeInfra:
            def __init__(self, root): pass

            def compile(self, filelist, coverage=True):
                return {"status": "FAIL", "errors": 3}

        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vlog")
        monkeypatch.setattr(
            "src.layers.l1_infrastructure.infrastructure.InfrastructureManager",
            _FakeInfra)
        result = _V(tmp_path, "dut", "systemverilog", "module m; endmodule\n")
        assert result["status"] == "FAIL"
        assert result["errors"] == 3

    def test_clean_compile_passes(self, tmp_path, monkeypatch):
        import shutil

        class _FakeInfra:
            def __init__(self, root): pass

            def compile(self, filelist, coverage=True):
                return {"status": "PASS", "errors": 0}

        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vlog")
        monkeypatch.setattr(
            "src.layers.l1_infrastructure.infrastructure.InfrastructureManager",
            _FakeInfra)
        result = _V(tmp_path, "dut", "systemverilog", "module m; endmodule\n")
        assert result["status"] == "PASS"

    def test_backend_exception_is_a_failure_not_a_silent_pass(self, tmp_path, monkeypatch):
        """校验过程本身炸了 —— 也算失败（失败响亮），绝不静默当成通过。"""
        import shutil

        class _BoomInfra:
            def __init__(self, root): pass

            def compile(self, filelist, coverage=True):
                raise RuntimeError("license 掉线")

        monkeypatch.setattr(shutil, "which", lambda name: "/usr/bin/vlog")
        monkeypatch.setattr(
            "src.layers.l1_infrastructure.infrastructure.InfrastructureManager",
            _BoomInfra)
        result = _V(tmp_path, "dut", "systemverilog", "module m; endmodule\n")
        assert result["status"] == "FAIL"
        assert "license" in result["detail"]
