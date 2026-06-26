# src/regression_framework/utils/git_utils.py
import os
import subprocess
import fnmatch
from ..core.logging_config import get_logger

logger = get_logger(__name__)

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
            else:
                for cf in changed_files:
                    for pattern in patterns:
                        if fnmatch.fnmatch(cf, pattern):
                            filtered.append(test)
                            break
                    else:
                        continue
                    break
        logger.info(f"Filtered tests: {len(tests)} -> {len(filtered)} (incremental)")
        return filtered
    except Exception as e:
        logger.warning(f"Git filtering failed: {e}, running all tests.")
        return tests