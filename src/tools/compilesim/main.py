"""Compile/Simulation regression entry point.

Usage: python -m src.tools.compilesim.main [args]
"""
import sys
from .Verify_run import main as verify_main


def run_verify(argv=None):
    """Run Verify regression with command-line args."""
    if argv is None:
        argv = sys.argv[1:]
    return verify_main(argv)


if __name__ == "__main__":
    sys.exit(run_verify() or 0)
