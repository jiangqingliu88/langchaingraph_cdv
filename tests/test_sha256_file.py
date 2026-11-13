"""`sha256_file` 的边界 —— 空路径必须是空哈希，不能是异常。

这条是一次实测事故的回归测试：覆盖率节点写审计条目时是这么调的：

    sha256_file(data.get("log_path", ""))[:16]

仿真/编译没跑起来时 `log_path` 就是空串，而 `Path("")` 会变成 `Path(".")` ——
它在 `exists()` 上**是真的**（当前目录），于是 `open(".")` 抛
`PermissionError: [Errno 13] Permission denied: '.'`。
后果不是"这一步没日志"，是**整次运行崩掉**：一个本该降级为"无哈希"的情况
被升级成了致命错误。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.runtime_plane.infrastructure.infrastructure import sha256_file


class TestEmptyAndMissing:
    @pytest.mark.parametrize("path", ["", "   ", None])
    def test_empty_path_is_an_empty_hash_not_an_error(self, path):
        assert sha256_file(path) == ""

    def test_dot_is_not_treated_as_a_readable_file(self):
        """`Path("")` 就是 `"."` —— 目录不能当文件读。"""
        assert sha256_file(".") == ""

    def test_a_directory_is_an_empty_hash(self, tmp_path):
        assert sha256_file(tmp_path) == ""

    def test_a_missing_file_is_an_empty_hash(self, tmp_path):
        assert sha256_file(tmp_path / "nope.log") == ""

    def test_slicing_the_result_is_safe(self):
        """调用方会直接 `[:16]` —— 空哈希也得能切片，不能抛。"""
        assert sha256_file("")[:16] == ""


class TestRealFiles:
    def test_hashes_a_real_file(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hi", encoding="utf-8")
        digest = sha256_file(f)
        assert len(digest) == 64 and digest[:16] == "8f434346648f6b96"

    def test_empty_file_has_the_known_empty_digest(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert sha256_file(f) == (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")

    def test_chunking_does_not_change_the_digest(self, tmp_path):
        """分块读和大块读必须同结果 —— ucdb 几十 GB，分块是必需的。"""
        f = tmp_path / "big.bin"
        f.write_bytes(b"x" * 5000)
        assert sha256_file(f, chunk_size=7) == sha256_file(f, chunk_size=65536)

    def test_accepts_str_and_path_alike(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hi", encoding="utf-8")
        assert sha256_file(str(f)) == sha256_file(Path(f))
