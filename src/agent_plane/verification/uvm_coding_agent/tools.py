"""UVM tools gated by explicit bounded output."""

from pathlib import Path

from src.agent_plane.reaction.sdk_tools import sdk_unavailable_tool


def build_uvm_tools(workspace_root: Path, output_root: str):
    from src.generation_plane.uvm_tools.agent_tools import (
        _uvm_ctx,
        check_static,
        find_spec_yaml,
        jinja_render,
        read_file,
        write_file,
    )

    if not output_root:
        return [
            sdk_unavailable_tool(n, "需要显式受限output_root")
            for n in ("find_spec_yaml", "jinja_render", "check_static", "read_file", "write_file")
        ]
    _uvm_ctx.set(output_dir=Path(output_root), agents=[], env_name=f"{Path(output_root).stem}_env")
    for candidate in (jinja_render, write_file):
        setattr(candidate, "requires_approval", True)
    return [find_spec_yaml, jinja_render, check_static, read_file, write_file]


__all__ = ["build_uvm_tools"]
