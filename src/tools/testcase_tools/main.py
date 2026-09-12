"""Test case generation entry point.

Usage: python -m src.tools.testcase_tools.main <yaml_file> [OPTIONS]
"""
import sys
from .generator import main as gen_main


def run_testcase_gen(argv=None):
    """Run test case generation with command-line args."""
    if argv is None:
        return gen_main()
    # generator.main() reads sys.argv directly; override for programmatic use
    import sys as _sys
    old_argv = _sys.argv
    try:
        _sys.argv = ["generator.py"] + argv
        return gen_main()
    finally:
        _sys.argv = old_argv


if __name__ == "__main__":
    sys.exit(run_testcase_gen() or 0)
