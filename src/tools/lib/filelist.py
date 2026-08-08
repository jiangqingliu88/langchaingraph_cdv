"""
Filelist 构建 —— 生成 QuestaSim vlog 兼容的 filelist.f

用法:
    from src.tools.lib.filelist import build_filelist_for_tb, build_loopback_filelist
    fl = build_filelist_for_tb(output_dir, agents, "dut_env")
    lb_fl = build_loopback_filelist(output_dir, "agent_name")
"""
from pathlib import Path


def build_filelist_for_tb(output_dir: Path, agents: list, env_name: str,
                          filelist_name: str = "filelist.f") -> Path:
    """构建全环境编译 filelist。"""
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl_path = fl_dir / filelist_name
    lines = []
    for a in agents:
        name = a["name"]
        lines.append(str(output_dir.resolve() / f"agents/{name}/{name}_interface.sv"))
    for a in agents:
        name = a["name"]
        lines.append(f"+incdir+{output_dir.resolve()}/agents/{name}")
        lines.append(str(output_dir.resolve() / f"agents/{name}/{name}_pkg.sv"))
    lines += [
        f"+incdir+{output_dir.resolve()}/env",
        str(output_dir.resolve() / f"env/{env_name}_pkg.sv"),
        f"+incdir+{output_dir.resolve()}/env/seqs",
        str(output_dir.resolve() / f"env/seqs/{env_name}_seq_pkg.sv"),
        f"+incdir+{output_dir.resolve()}/env/tests",
        str(output_dir.resolve() / f"env/tests/{env_name}_test_pkg.sv"),
    ]
    fl_path.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl_path


def build_loopback_filelist(output_dir: Path, agent_name: str) -> Path:
    """构建单 agent loopback 编译 filelist。"""
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl = fl_dir / f"filelist_{agent_name}_lb.f"
    agent_dir = output_dir / "agents" / agent_name
    lines = [
        f"+define+{agent_name}_loop_back_test",
        f"+incdir+{agent_dir.resolve()}",
        f"+incdir+{agent_dir.resolve()}/loopback",
        str(agent_dir.resolve() / f"{agent_name}_interface.sv"),
        str(agent_dir.resolve() / f"{agent_name}_pkg.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_scb.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_env.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_test.sv"),
        str(agent_dir.resolve() / f"loopback/{agent_name}_loopback_tb.sv"),
    ]
    fl.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl
