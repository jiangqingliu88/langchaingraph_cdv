"""UVM 模板注册表 —— 只描述「模板 → 目标文件名」，不渲染。

从 `tool_uvm/gen_uvm.py` 搬出；调用方直接从这里导入（门面已删）。
新增模板在这里登记，渲染与业务判断仍在生成器侧。
"""
from __future__ import annotations


# AXI-VIP 风格：编号分层目录 + master/slave 完全分离
INTERFACE_TEMPLATES = [
    ("interface_templates/interface.sv.j2", "1_interface/{agent_name}_if.sv"),
    ("interface_templates/interface_system.j2", "1_interface/{agent_name}_system_if.sv"),

    # 单类合并模板（不区分 master/slave）
    ("interface_templates/port_config.sv.j2", "2_config/{agent_name}_port_config.sv"),

    # base 必须排在 master/slave 之前：派生类要引用基类的 xact_type_e / 字段，
    # SystemVerilog 要求先声明后使用。
    ("interface_templates/sequence_item_base.sv.j2", "3_transaction_sequencer/{agent_name}_base_seq_item.sv"),
    ("interface_templates/seq_item_master.sv.j2", "3_transaction_sequencer/{agent_name}_master_seq_item.sv"),
    ("interface_templates/seq_item_slave.sv.j2",  "3_transaction_sequencer/{agent_name}_slave_seq_item.sv"),
    ("interface_templates/sequencer_master.sv.j2", "3_transaction_sequencer/{agent_name}_master_sequencer.sv"),
    ("interface_templates/sequencer_slave.sv.j2",  "3_transaction_sequencer/{agent_name}_slave_sequencer.sv"),

    ("interface_templates/driver_master.sv.j2", "4_driver_monitor/{agent_name}_master_driver.sv"),
    ("interface_templates/driver_slave.sv.j2",  "4_driver_monitor/{agent_name}_slave_driver.sv"),
    ("interface_templates/port_monitor.sv.j2", "4_driver_monitor/{agent_name}_port_monitor.sv"),

    ("interface_templates/agent_master.sv.j2", "5_agent/{agent_name}_master_agent.sv"),
    ("interface_templates/agent_slave.sv.j2",  "5_agent/{agent_name}_slave_agent.sv"),
    ("interface_templates/config_system.sv.j2", "5_agent/{agent_name}_system_config.sv"),
    # vsqr 必须在 system_env 之前：env 持有 vsqr 句柄，vsqr 不引用 env（单向依赖，
    # 见模板头部说明），故先声明 vsqr 才能让 env 使用它的类型。
    ("interface_templates/interface_system_vsqr.sv.j2", "5_agent/{agent_name}_system_vsqr.sv"),
    ("interface_templates/interface_system_monitor.sv.j2", "5_agent/{agent_name}_system_monitor.sv"),
    ("interface_templates/interface_system_env.j2", "5_agent/{agent_name}_system_env.sv"),

    ("interface_templates/sequence_master.sv.j2", "7_sequence/{agent_name}_master_sequence.sv"),
    ("interface_templates/sequence_slave.sv.j2",  "7_sequence/{agent_name}_slave_sequence.sv"),

    ("interface_templates/reg_adapter.sv.j2", "8_ral/{agent_name}_reg_adapter.sv"),

    ("interface_templates/agent_parameters_pkg.sv.j2", "{agent_name}_parameters_pkg.sv"),
    ("interface_templates/agent_typedefs_pkg.sv.j2", "{agent_name}_typedefs_pkg.sv"),
    ("interface_templates/agent_pkg.sv.j2", "{agent_name}_pkg.sv"),
    ("interface_templates/agent_filelist.sv.j2", "filelist.f"),
    ("interface_templates/agent_Makefile.sv.j2", "Makefile"),
]

def _split_template_entry(entry) -> tuple:
    """模板注册表条目 → (template_path, target_pattern, context_overrides)。

    兼容 2 元组（无覆盖）与 3 元组（第 3 元素为渲染上下文覆盖，如 {"port": "master"}）。
    """
    return entry[0], entry[1], (entry[2] if len(entry) > 2 else {})


# Agent 自闭环测试套件（master-drive → slave-monitor 闭环，独立编译运行）
AGENT_LOOPBACK_TEMPLATES = [
    ("interface_templates/agent_loopback_env.sv.j2",  "{agent_name}_loopback_env.sv"),
    ("interface_templates/agent_loopback_scb.sv.j2",  "{agent_name}_loopback_scb.sv"),
    ("interface_templates/agent_loopback_test.sv.j2", "{agent_name}_loopback_test.sv"),
    ("interface_templates/agent_loopback_tb.sv.j2",   "{agent_name}_loopback_tb.sv"),
]

ENVIRONMENT_ROOT_TEMPLATES = [
    ("environment_templates/env_parameters_pkg.sv.j2", "{env_name}_parameters_pkg.sv"),
    ("environment_templates/env_config.sv.j2", "{env_name}_config.sv"),
    ("environment_templates/environment.sv.j2", "{env_name}.sv"),
    ("environment_templates/env_cov.sv.j2", "{env_name}_coverage.sv"),
    ("environment_templates/sim_end.sv.j2", "{env_name}_sim_end.sv"),
    ("environment_templates/env_pkg.sv.j2", "{env_name}_pkg.sv"),
]

ENVIRONMENT_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_pkg.sv.j2", "{env_name}_test_pkg.sv"),
    ("environment_templates/test_templates/test_base.sv.j2", "{env_name}_base_test.sv"),
    ("environment_templates/test_templates/test_directed.sv.j2", "{env_name}_direct_test.sv"),
    ("environment_templates/test_templates/gen_test_sv.j2", "{env_name}_gen_test.sv"),
]

#: 属性测试（**一条 environment.tests = 一个 UVM_TEST = 一个属性取值**）。
#: 单独一张表而不是并进上面那张：那张是「无条件产出的四个文件」，
#: 它被既有测试逐字钉着；这张**只在 tests 非空时渲染**，产物也只有一个文件。
ENVIRONMENT_ATTR_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_attr.sv.j2", "{env_name}_attr_test.sv"),
]

#: 批次测试（**一条 environment.batches = 一个 UVM_TEST = 一个批次/专题**）。
#: 与属性测试同形（都在 `tests`/`batches` 非空时才产），但产物不同 ——
#: 这一份出的是"这一批打哪几个维度、用什么方法"的 test 类，名字由 case 模型的
#: `themes[].test` 给定。**没有它，回归里 `+UVM_TESTNAME=<批次>` 会撞
#: UVM_FATAL(INVTST)，而那条路径被记成 pass**（见 `_sim_run_cmd` 的注释）。
ENVIRONMENT_BATCH_TEST_TEMPLATES = [
    ("environment_templates/test_templates/test_batch.sv.j2", "{env_name}_batch_test.sv"),
]

#: 寄存器（CSR）自带序列测试 —— 每个都是**薄薄一层**：实例化一个 UVM 官方
#: 寄存器序列（hw_reset / bit_bash / access）并 start。
#: **只在环境配了 register_model（且有 reg_block）时才产**：没配的环境连寄存器
#: 模型都没有，产出来就是一堆编译不过的文件。
ENVIRONMENT_REG_TEST_TEMPLATES = [
    ("environment_templates/test_templates/csr_hw_reset_test.sv.j2",
     "{env_name}_reg_hw_reset_test.sv"),
    ("environment_templates/test_templates/csr_bit_bash_test.sv.j2",
     "{env_name}_reg_bit_bash_test.sv"),
    ("environment_templates/test_templates/csr_access_test.sv.j2",
     "{env_name}_reg_access_test.sv"),
]


ENVIRONMENT_SEQ_TEMPLATES = [
    ("environment_templates/virtual_sequencer.sv.j2", "{env_name}_virtual_sequencer.sv"),
    ("environment_templates/seq_templates/virtual_sequence_base.sv.j2", "{env_name}_virtual_base_seq.sv"),
    ("environment_templates/seq_templates/seq_pkg.sv.j2", "{env_name}_seq_pkg.sv"),
]

ENV_CONSTRAINT_TEMPLATES = [
    (
        "environment_templates/env_cons_coordinated_sequence.j2",
        "{env_name}_coordinated_sequence.sv",
    ),
    (
        "environment_templates/env_cons_policy_base.sv.j2",
        "{env_name}_constraint_policy.sv",
    ),
    (
        "environment_templates/env_cons_policies.sv.j2",
        "{env_name}_constraint_policies.sv",
    ),
    (
        "environment_templates/env_cons_policy_combinator.j2",
        "{env_name}_policy_combinator.sv",
    ),
    (
        "environment_templates/env_cons_policy_factory.j2",
        "{env_name}_policy_factory.sv",
    ),
]

BENCH_TEMPLATES = [
    ("bench_templates/tb_top.sv.j2", "{bench_name}_tb_top.sv"),
]

HARNESS_TEMPLATES = [
    ("bench_templates/harness.sv.j2", "{name}.sv"),
]

CMODEL_TEMPLATES = [
    ("environment_templates/cmodel_predictor.sv.j2", "{module_name}_cmodel_predictor.sv"),
    ("environment_templates/cmodel_dpi.cpp.j2", "{module_name}_dpi_wrapper.cpp"),
]
