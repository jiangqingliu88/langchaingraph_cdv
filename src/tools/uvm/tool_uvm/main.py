"""tool_uvm entry point.

Usage: python -m src.tools.uvm.tool_uvm.main [args]
"""
import sys
from .gen_uvm import main as gen_main


if __name__ == "__main__":
    sys.exit(gen_main() or 0)
