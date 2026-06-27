"""UVM generation tools entry point.

Delegates to tool_uvm for UVM code generation.

Usage: python -m src.tools.uvm_tools.main [args]
"""
import sys
from .tool_uvm.gen_uvm import main as uvm_main


def run_uvm(argv=None):
    """Run UVM code generation."""
    if argv is None:
        argv = sys.argv[1:]
    return uvm_main(argv)


if __name__ == "__main__":
    sys.exit(run_uvm() or 0)
