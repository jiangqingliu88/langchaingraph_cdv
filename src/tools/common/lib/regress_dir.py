"""regress_dir 解析 —— UVM 阶段 vs Test 阶段编译/仿真路径分离。

设计原则:
  - work library 共享: 所有阶段编译到 uvm_regress/build/work (增量编译)
  - 仿真输出分离:   UVM phase → uvm_regress/sim, regress phase → test_regress/sim

用法:
  from src.tools.common.lib.regress_dir import get_compile_dir, get_sim_dir
"""
from pathlib import Path


def _read_yaml_regress_dir(output_dir) -> str:
    """从 constraint.yaml 或 regression.yaml 读取 regress_dir 字段。"""
    import yaml
    od = Path(output_dir)

    for yaml_name in ["constraint.yaml", "regression.yaml"]:
        yaml_path = od / "inputs" / "yaml" / yaml_name
        if yaml_path.exists():
            try:
                data = yaml.safe_load(yaml_path.read_text(encoding="utf-8", errors="replace"))
                rd = data.get("constraint", data).get("regress_dir", "")
                if rd:
                    return rd
            except Exception:
                pass
    return ""


def get_compile_dir(output_dir) -> str:
    """编译 work library 路径 — 始终 uvm_regress（共享，增量编译）。

    UVM phase 编译 env → uvm_regress/build/work
    regress phase 增量编译 test cases → 同一个 uvm_regress/build/work
    """
    return "uvm_regress"


def get_sim_dir(output_dir) -> str:
    """仿真输出路径 — 根据 constraint.yaml 中的 regress_dir 决定。

    - constraint.yaml 不存在 (UVM phase) → uvm_regress (loopback 日志)
    - constraint.yaml 存在且 regress_dir=test_regress → test_regress (回归报告/ucdb)
    """
    rd = _read_yaml_regress_dir(output_dir)
    if rd:
        return rd  # test_regress (Test/regress/cover phase)
    return "uvm_regress"  # UVM phase 默认


def get_regress_dir(output_dir) -> str:
    """兼容旧接口: 返回 sim_dir（向后兼容）。"""
    return get_sim_dir(output_dir)
