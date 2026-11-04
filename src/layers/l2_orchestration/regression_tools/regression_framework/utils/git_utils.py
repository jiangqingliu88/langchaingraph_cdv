# src/regression_framework/utils/git_utils.py
import os
import subprocess
import fnmatch
from ..core.logging_config import get_logger

logger = get_logger(__name__)

def _match_pattern(changed_file: str, pattern: str) -> bool:
    """一个变更文件是否命中一条 file_pattern。

    除了常规的 fnmatch（`rtl/*.sv`），还认**以 `/` 结尾的目录写法**：`rtl/` 是
    最自然的写法，但 `fnmatch('rtl/dut.sv', 'rtl/')` 为 False —— 少一个 `*` 就
    一条都匹配不上，增量回归会静默跑空。
    """
    if pattern.endswith('/'):
        return changed_file.startswith(pattern)
    return fnmatch.fnmatch(changed_file, pattern)


def filter_by_git_changes(tests: list, repo_path: str = '.') -> list:
    """根据 Git 变更过滤测试列表"""
    if not os.path.isdir(os.path.join(repo_path, '.git')):
        logger.info("Not a git repository, skipping incremental filtering.")
        return tests
    try:
        output = subprocess.check_output(
            ["git", "-C", repo_path, "diff", "--name-only", "HEAD~1"],
            text=True
        )
        changed_files = set(output.strip().splitlines())
        if not changed_files:
            logger.info("No changed files detected.")
            return tests
        logger.info(f"Changed files: {len(changed_files)}")
        filtered = []
        for test in tests:
            patterns = test.get('file_pattern', [])
            if not patterns:
                filtered.append(test)
            elif any(_match_pattern(cf, p) for cf in changed_files for p in patterns):
                filtered.append(test)
        logger.info(f"Filtered tests: {len(tests)} -> {len(filtered)} (incremental)")
        return filtered
    except Exception as e:
        logger.warning(f"Git filtering failed: {e}, running all tests.")
        return tests