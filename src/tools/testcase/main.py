"""Test case generation entry point.

Usage: python -m src.tools.testcase.main <yaml_file> [OPTIONS]
"""
import sys
from .generator import main as gen_main


def run_testcase_gen(argv=None):
    """Run test case generation with command-line args."""
    if argv is None:
        argv = sys.argv[1:]
    return gen_main(argv)


if __name__ == "__main__":
    sys.exit(run_testcase_gen() or 0)
