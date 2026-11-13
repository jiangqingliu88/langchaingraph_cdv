"""tool_uvm entry point.

Usage: python -m src.generation_plane.uvm_tools.tool_uvm.main [args]
"""
import sys
from ..tool_uvm.generators.cli import main as gen_main


if __name__ == "__main__":
    sys.exit(gen_main() or 0)
