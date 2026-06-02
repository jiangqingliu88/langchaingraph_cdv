"""
UVM工具集 - 使用Jinja2模板引擎生成UVM代码
"""
from langchain.tools import tool, BaseTool
from typing import Dict, List, Any, Optional, Type
from pydantic import BaseModel, Field
import json
import structlog

from src.tools.templates import render_template, TemplateLoader

logger = structlog.get_logger()

class UVMTools:
    """UVM代码生成工具集"""
    
    def __init__(self):
        self.template_loader = TemplateLoader.get_instance()
    
    def get_all_tools(self) -> List[BaseTool]:
        """获取所有UVM工具"""
        return [
            self.generate_uvm_architecture,
            self.generate_uvm_driver,
            self.generate_uvm_monitor,
            self.generate_uvm_agent,
            self.generate_uvm_scoreboard,
            self.generate_uvm_environment,
            self.generate_uvm_test,
            self.generate_uvm_transaction,
            self.generate_uvm_sequence,
            self.generate_uvm_virtual_sequence,
            self.generate_uvm_coverage_collector,
            self.generate_uvm_tb_top,
            self.generate_uvm_interface,
            self.generate_uvm_package,
        ]
    
    def get_sequence_tools(self) -> List[BaseTool]:
        """获取序列相关工具"""
        return [
            self.generate_uvm_sequence,
            self.generate_uvm_virtual_sequence,
            self.generate_uvm_sequence_library,
        ]
    
    def get_component_tools(self) -> List[BaseTool]:
        """获取组件生成工具"""
        return [
            self.generate_uvm_driver,
            self.generate_uvm_monitor,
            self.generate_uvm_agent,
            self.generate_uvm_scoreboard,
        ]
    
    def get_environment_tools(self) -> List[BaseTool]:
        """获取环境生成工具"""
        return [
            self.generate_uvm_environment,
            self.generate_uvm_test,
            self.generate_uvm_tb_top,
            self.generate_uvm_package,
        ]
    
    @tool("generate_uvm_architecture")
    def generate_uvm_architecture(self, specs: str) -> str:
        """生成UVM验证环境架构文档"""
        try:
            spec_data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            spec_data = {"design_name": "dut", "protocols": ["generic"]}
        
        architecture = {
            "architecture_name": f"{spec_data.get('design_name', 'dut')}_verification_env",
            "methodology": "UVM",
            "components": {
                "testbench_top": {
                    "file": "tb/tb_top.sv",
                    "description": "Testbench top module"
                },
                "environment": {
                    "name": f"{spec_data.get('design_name', 'dut')}_env",
                    "file": "env/env.sv"
                },
                "agents": [
                    {
                        "name": "active_agent",
                        "type": "UVM_ACTIVE",
                        "file": "agents/active_agent.sv",
                        "components": ["sequencer", "driver", "monitor"]
                    },
                    {
                        "name": "passive_agent",
                        "type": "UVM_PASSIVE",
                        "file": "agents/passive_agent.sv",
                        "components": ["monitor"]
                    }
                ],
                "scoreboard": {
                    "name": "scoreboard",
                    "file": "scoreboard/scoreboard.sv",
                    "sub_components": ["predictor", "comparator"]
                },
                "coverage": {
                    "name": "coverage_collector",
                    "file": "coverage/coverage_collector.sv"
                },
                "sequences": {
                    "base_sequence": "sequences/base_sequence.sv",
                    "virtual_sequence": "sequences/virtual_sequence.sv",
                    "sequence_library": "sequences/sequence_library.sv"
                },
                "tests": {
                    "base_test": "tests/base_test.sv",
                    "test_library": "tests/test_library.sv"
                }
            },
            "tlm_connections": [
                {"from": "active_agent.monitor", "to": "scoreboard", "port": "analysis_port"},
                {"from": "passive_agent.monitor", "to": "scoreboard", "port": "analysis_port"},
                {"from": "active_agent.monitor", "to": "coverage_collector", "port": "analysis_port"}
            ],
            "file_structure": [
                "tb/",
                "env/",
                "agents/",
                "scoreboard/",
                "coverage/",
                "sequences/",
                "tests/",
                "common/"
            ]
        }
        return json.dumps(architecture, indent=2)
    
    @tool("generate_uvm_driver")
    def generate_uvm_driver(self, specs: str) -> str:
        """
        生成UVM Driver代码
        
        参数:
        specs: JSON格式的Driver规格
        {
            "driver_name": "uart_driver",
            "interface_type": "uart_if",
            "transaction_type": "uart_transaction",
            "agent_config_type": "uart_agent_config",
            "drive_phases": [
                {
                    "name": "address",
                    "description": "Address phase",
                    "code": "vif.addr <= tr.addr;\nvif.write <= tr.write;\n@(posedge vif.clk);"
                },
                {
                    "name": "data",
                    "description": "Data phase", 
                    "code": "vif.data <= tr.data;\nvif.valid <= 1'b1;\n@(posedge vif.clk);\nvif.valid <= 1'b0;"
                }
            ]
        }
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_driver_spec()
        
        context = {
            "driver_name": data.get("driver_name", "default_driver"),
            "interface_type": data.get("interface_type", "virtual_if"),
            "transaction_type": data.get("transaction_type", "transaction"),
            "agent_config_type": data.get("agent_config_type", "agent_config"),
            "description": data.get("description", ""),
            "has_analysis_port": data.get("has_analysis_port", False),
            "reset_sequence": data.get("reset_sequence", True),
            "reset_signal": data.get("reset_signal", "rst_n"),
            "drive_phases": data.get("drive_phases", []),
            "additional_methods": data.get("additional_methods", [])
        }
        
        try:
            return render_template("driver/driver.j2", **context)
        except Exception as e:
            logger.error(f"Driver模板渲染失败", error=str(e))
            return f"// Error generating driver: {str(e)}"
    
    @tool("generate_uvm_monitor")
    def generate_uvm_monitor(self, specs: str) -> str:
        """
        生成UVM Monitor代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_monitor_spec()
        
        context = {
            "monitor_name": data.get("monitor_name", "default_monitor"),
            "interface_type": data.get("interface_type", "virtual_if"),
            "transaction_type": data.get("transaction_type", "transaction"),
            "agent_config_type": data.get("agent_config_type", "agent_config"),
            "description": data.get("description", ""),
            "has_coverage": data.get("has_coverage", False),
            "has_protocol_checker": data.get("has_protocol_checker", False),
            "protocol_checker_name": data.get("protocol_checker_name", "protocol_checker"),
            "collect_steps": data.get("collect_steps", [
                {
                    "description": "Sample data",
                    "code": "@(posedge vif.clk);\nif(vif.valid) begin\n    trans_collected.data = vif.data;\nend"
                }
            ])
        }
        
        try:
            return render_template("monitor/monitor.j2", **context)
        except Exception as e:
            logger.error(f"Monitor模板渲染失败", error=str(e))
            return f"// Error generating monitor: {str(e)}"
    
    @tool("generate_uvm_agent")
    def generate_uvm_agent(self, specs: str) -> str:
        """
        生成UVM Agent代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_agent_spec()
        
        agent_code = f"""
// ============================================
// {data.get('agent_name', 'default_agent')}
// UVM Agent Component
// ============================================

class {data.get('agent_name', 'default_agent')} extends uvm_agent;
    `uvm_component_utils({data.get('agent_name', 'default_agent')})
    
    // Components
    {data.get('sequencer_name', 'sequencer')} sequencer;
    {data.get('driver_name', 'driver')} driver;
    {data.get('monitor_name', 'monitor')} monitor;
    
    // Configuration
    {data.get('config_type', 'agent_config')} cfg;
    
    // Constructor
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    
    // Build Phase
    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        
        if(!uvm_config_db #{data.get('config_type', 'agent_config')}::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "Agent configuration not found")
        
        monitor = {data.get('monitor_name', 'monitor')}::type_id::create("monitor", this);
        
        if(cfg.is_active == UVM_ACTIVE) begin
            sequencer = {data.get('sequencer_name', 'sequencer')}::type_id::create("sequencer", this);
            driver = {data.get('driver_name', 'driver')}::type_id::create("driver", this);
        end
    endfunction
    
    // Connect Phase
    function void connect_phase(uvm_phase phase);
        super.connect_phase(phase);
        if(cfg.is_active == UVM_ACTIVE) begin
            driver.seq_item_port.connect(sequencer.seq_item_export);
        end
    endfunction
    
endclass : {data.get('agent_name', 'default_agent')}
        """
        return agent_code
    
    @tool("generate_uvm_scoreboard")
    def generate_uvm_scoreboard(self, specs: str) -> str:
        """
        生成UVM Scoreboard代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_scoreboard_spec()
        
        context = {
            "scoreboard_name": data.get("scoreboard_name", "default_scoreboard"),
            "transaction_type": data.get("transaction_type", "transaction"),
            "scoreboard_config_type": data.get("config_type", "scoreboard_config"),
            "description": data.get("description", ""),
            "input_ports": data.get("input_ports", [
                {"name": "actual", "transaction_type": "transaction"},
                {"name": "expected", "transaction_type": "transaction"}
            ]),
            "predictor_name": data.get("predictor_name", "predictor"),
            "has_logger": data.get("has_logger", False),
            "logger_name": data.get("logger_name", "scoreboard_logger"),
            "compare_tasks": data.get("compare_tasks", [
                {
                    "name": "compare_transactions",
                    "description": "Main comparison task",
                    "input_var": "actual",
                    "expected_var": "expected",
                    "actual_fifo": "actual_fifo",
                    "error_message": "Scoreboard mismatch detected"
                }
            ])
        }
        
        try:
            return render_template("scoreboard/scoreboard.j2", **context)
        except Exception as e:
            logger.error(f"Scoreboard模板渲染失败", error=str(e))
            return f"// Error generating scoreboard: {str(e)}"
    
    @tool("generate_uvm_environment")
    def generate_uvm_environment(self, specs: str) -> str:
        """
        生成UVM Environment代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_env_spec()
        
        context = {
            "env_name": data.get("env_name", "default_env"),
            "env_config_type": data.get("config_type", "env_config"),
            "description": data.get("description", ""),
            "agents": data.get("agents", [
                {
                    "class_name": "agent",
                    "instance_name": "m_agent",
                    "config_type": "agent_config",
                    "config_name": "agent_cfg"
                }
            ]),
            "has_scoreboard": data.get("has_scoreboard", True),
            "scoreboard_name": data.get("scoreboard_name", "scoreboard"),
            "scoreboard_config_type": data.get("scoreboard_config_type", "scoreboard_config"),
            "has_coverage": data.get("has_coverage", True),
            "coverage_collector_name": data.get("coverage_collector_name", "coverage_collector"),
            "has_virtual_sequencer": data.get("has_virtual_sequencer", True),
            "virtual_sequencer_name": data.get("virtual_sequencer_name", "virtual_sequencer"),
            "connections": data.get("connections", [
                {
                    "description": "Monitor to Scoreboard",
                    "source": "m_agent.monitor",
                    "source_port": "item_collected_port",
                    "target": "scoreboard",
                    "target_port": "actual_export"
                }
            ]),
            "virtual_sequencer_connections": data.get("virtual_sequencer_connections", [
                {"handle_name": "agent_sequencer", "agent_path": "m_agent"}
            ])
        }
        
        try:
            return render_template("environment/environment.j2", **context)
        except Exception as e:
            logger.error(f"Environment模板渲染失败", error=str(e))
            return f"// Error generating environment: {str(e)}"
    
    @tool("generate_uvm_test")
    def generate_uvm_test(self, specs: str) -> str:
        """
        生成UVM Test代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_test_spec()
        
        test_code = f"""
// ============================================
// {data.get('test_name', 'base_test')}
// UVM Test
// ============================================

class {data.get('test_name', 'base_test')} extends uvm_test;
    `uvm_component_utils({data.get('test_name', 'base_test')})
    
    // Environment
    {data.get('env_name', 'env')} env;
    
    // Virtual Sequencer
    {data.get('virtual_sequencer_name', 'virtual_sequencer')} vsequencer;
    
    // Configuration
    {data.get('env_config_type', 'env_config')} env_cfg;
    
    // Constructor
    function new(string name = "{data.get('test_name', 'base_test')}", uvm_component parent = null);
        super.new(name, parent);
    endfunction
    
    // Build Phase
    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        
        // Create and configure environment
        env_cfg = {data.get('env_config_type', 'env_config')}::type_id::create("env_cfg");
        
        // Configure agents
        env_cfg.{data.get('active_agent_cfg', 'active_agent_cfg')}.is_active = UVM_ACTIVE;
        env_cfg.{data.get('passive_agent_cfg', 'passive_agent_cfg')}.is_active = UVM_PASSIVE;
        
        // Set configuration
        uvm_config_db #({data.get('env_config_type', 'env_config')})::set(this, "env.*", "cfg", env_cfg);
        
        // Create environment
        env = {data.get('env_name', 'env')}::type_id::create("env", this);
    endfunction
    
    // End of Elaboration Phase
    function void end_of_elaboration_phase(uvm_phase phase);
        super.end_of_elaboration_phase(phase);
        uvm_top.print_topology();
    endfunction
    
    // Run Phase
    virtual task run_phase(uvm_phase phase);
        {data.get('sequence_type', 'base_sequence')} seq;
        
        phase.raise_objection(this);
        
        seq = {data.get('sequence_type', 'base_sequence')}::type_id::create("seq");
        
        // Randomize sequence
        if(!seq.randomize()) begin
            `uvm_fatal("TEST", "Sequence randomization failed")
        end
        
        // Start sequence
        seq.start(env.{data.get('virtual_sequencer_path', 'virtual_sequencer')});
        
        // Wait for sequence completion
        #100ns;
        
        phase.drop_objection(this);
    endtask
    
    // Report Phase
    function void report_phase(uvm_phase phase);
        super.report_phase(phase);
        
        // Test summary
        `uvm_info("{data.get('test_name', 'base_test')}", 
            "Test completed", UVM_MEDIUM)
    endfunction
    
endclass : {data.get('test_name', 'base_test')}
        """
        return test_code
    
    @tool("generate_uvm_transaction")
    def generate_uvm_transaction(self, specs: str) -> str:
        """
        生成UVM Transaction代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_transaction_spec()
        
        transaction_code = f"""
// ============================================
// {data.get('name', 'transaction')}
// UVM Transaction Item
// ============================================

class {data.get('name', 'transaction')} extends uvm_sequence_item;
    `uvm_object_utils({data.get('name', 'transaction')})
    
    // Data fields
    {';'.join(data.get('fields', ['rand bit [31:0] data']))};
    
    // Constraints
    {';'.join(data.get('constraints', []))}
    
    // Constructor
    function new(string name = "{data.get('name', 'transaction')}");
        super.new(name);
    endfunction
    
    // Utility methods
    function string convert2string();
        return $sformatf("{data.get('name', 'transaction')}: %p", this);
    endfunction
    
    function bit do_compare(uvm_object rhs, uvm_comparer comparer);
        {data.get('name', 'transaction')} compared;
        bit status;
        
        if(!$cast(compared, rhs)) begin
            return 0;
        end
        
        {'status = 1;' if data.get('fields') else ''}
        {'status &= (data == compared.data);' if 'data' in str(data.get('fields', [])) else ''}
        
        return status;
    endfunction
    
    function void do_copy(uvm_object rhs);
        {data.get('name', 'transaction')} copied;
        if(!$cast(copied, rhs)) return;
        
        {'data = copied.data;' if 'data' in str(data.get('fields', [])) else ''}
    endfunction
    
endclass : {data.get('name', 'transaction')}
        """
        return transaction_code
    
    @tool("generate_uvm_sequence")
    def generate_uvm_sequence(self, specs: str) -> str:
        """
        生成UVM Sequence代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_sequence_spec()
        
        context = {
            "sequence_name": data.get("name", "default_sequence"),
            "item_type": data.get("item_type", "transaction"),
            "description": data.get("description", ""),
            "random_vars": data.get("random_vars", [
                {"type": "int unsigned", "name": "num_transactions", "default": 10}
            ]),
            "constraints": data.get("constraints", [
                {"name": "num_transactions_c", "body": "num_transactions inside {[1:100]};"}
            ]),
            "loop_variable": data.get("loop_variable", "num_transactions"),
            "pre_body_code": data.get("pre_body_code", ""),
            "post_body_code": data.get("post_body_code", ""),
            "randomization_constraints": data.get("randomization_constraints", []),
            "post_randomize_code": data.get("post_randomize_code", ""),
            "inter_item_delay": data.get("inter_item_delay", ""),
            "additional_tasks": data.get("additional_tasks", [])
        }
        
        try:
            return render_template("sequence/sequence.j2", **context)
        except Exception as e:
            logger.error(f"Sequence模板渲染失败", error=str(e))
            return f"// Error generating sequence: {str(e)}"
    
    @tool("generate_uvm_virtual_sequence")
    def generate_uvm_virtual_sequence(self, specs: str) -> str:
        """
        生成Virtual Sequence代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_vsequence_spec()
        
        vseq_code = f"""
// ============================================
// {data.get('name', 'virtual_sequence')}
// Virtual Sequence
// ============================================

class {data.get('name', 'virtual_sequence')} extends uvm_sequence;
    `uvm_object_utils({data.get('name', 'virtual_sequence')})
    
    // Sequencer handles
    {';'.join(data.get('sequencer_handles', []))};
    
    // Constructor
    function new(string name = "{data.get('name', 'virtual_sequence')}");
        super.new(name);
    endfunction
    
    // Body
    virtual task body();
        {chr(10).join(data.get('sequence_code', ['// No sequence logic defined']))}
    endtask
    
endclass : {data.get('name', 'virtual_sequence')}
        """
        return vseq_code
    
    @tool("generate_uvm_coverage_collector")
    def generate_uvm_coverage_collector(self, specs: str) -> str:
        """
        生成Coverage Collector代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_coverage_spec()
        
        context = {
            "coverage_collector_name": data.get("name", "coverage_collector"),
            "transaction_type": data.get("transaction_type", "transaction"),
            "description": data.get("description", ""),
            "covergroups": data.get("covergroups", [
                {
                    "name": "data_cg",
                    "coverpoints": [
                        {
                            "name": "data_cp",
                            "signal": "data",
                            "bins": [
                                {"name": "low", "values": ["[0:63]"]},
                                {"name": "mid", "values": ["[64:191]"]},
                                {"name": "high", "values": ["[192:255]"]}
                            ]
                        }
                    ],
                    "crosses": []
                }
            ])
        }
        
        try:
            return render_template("coverage/coverage_collector.j2", **context)
        except Exception as e:
            logger.error(f"Coverage模板渲染失败", error=str(e))
            return f"// Error generating coverage collector: {str(e)}"
    
    @tool("generate_uvm_tb_top")
    def generate_uvm_tb_top(self, specs: str) -> str:
        """
        生成Testbench Top代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_tb_top_spec()
        
        tb_code = f"""
// ============================================
// Testbench Top
// ============================================

module {data.get('name', 'tb_top')};
    
    // Clock and Reset
    reg clk;
    reg rst_n;
    
    // Clock generation
    initial begin
        clk = 0;
        forever #5ns clk = ~clk;
    end
    
    // Reset generation
    initial begin
        rst_n = 0;
        repeat(10) @(posedge clk);
        rst_n = 1;
    end
    
    // Interfaces
    {';'.join(data.get('interfaces', []))};
    
    // DUT instance
    {';'.join(data.get('dut_instance', []))}
    
    // Interface connections
    {';'.join(data.get('interface_connections', []))}
    
    // UVM test
    initial begin
        // Set interfaces in config DB
        {';'.join(data.get('config_db_sets', []))}
        
        // Run test
        run_test("{data.get('test_name', 'base_test')}");
    end
    
    // Waveform dumping
    initial begin
        $dumpfile("{data.get('dump_file', 'waves.vcd')}");
        $dumpvars(0, {data.get('name', 'tb_top')});
    end
    
endmodule : {data.get('name', 'tb_top')}
        """
        return tb_code
    
    @tool("generate_uvm_interface")
    def generate_uvm_interface(self, specs: str) -> str:
        """
        生成SystemVerilog Interface代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_interface_spec()
        
        interface_code = f"""
// ============================================
// {data.get('name', 'interface')}
// SystemVerilog Interface
// ============================================

interface {data.get('name', 'interface')} (
    input logic clk,
    input logic rst_n
);
    
    // Signals
    {';'.join(data.get('signals', ['logic [31:0] data', 'logic valid', 'logic ready']))};
    
    // Clocking blocks
    clocking cb @(posedge clk);
        {';'.join(data.get('clocking_signals', ['output data', 'output valid', 'input ready']))};
    endclocking
    
    // Modports
    {';'.join(data.get('modports', []))}
    
    // Assertions
    {';'.join(data.get('assertions', []))}
    
endinterface : {data.get('name', 'interface')}
        """
        return interface_code
    
    @tool("generate_uvm_package")
    def generate_uvm_package(self, specs: str) -> str:
        """
        生成UVM Package代码
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_package_spec()
        
        package_code = f"""
// ============================================
// {data.get('name', 'uvm_package')}
// UVM Package
// ============================================

package {data.get('name', 'uvm_package')};
    
    // UVM imports
    import uvm_pkg::*;
    `include "uvm_macros.svh"
    
    // Common imports
    {chr(10).join(data.get('imports', []))}
    
    // Include files
    {chr(10).join(data.get('includes', []))}
    
endpackage : {data.get('name', 'uvm_package')}
        """
        return package_code
    
    @tool("generate_uvm_sequence_library")
    def generate_uvm_sequence_library(self, specs: str) -> str:
        """
        生成Sequence Library
        """
        try:
            data = json.loads(specs) if isinstance(specs, str) else specs
        except json.JSONDecodeError:
            data = self._get_default_seq_library_spec()
        
        library = {
            "library_name": data.get("name", "sequence_library"),
            "sequences": data.get("sequences", [
                {"name": "base_sequence", "type": "base"},
                {"name": "random_sequence", "type": "random"},
                {"name": "stress_sequence", "type": "stress"}
            ]),
            "selection_mode": data.get("selection_mode", "UVM_SEQ_LIB_RAND"),
            "min_random_count": data.get("min_random_count", 10),
            "max_random_count": data.get("max_random_count", 50)
        }
        return json.dumps(library, indent=2)
    
    # ==================== 默认规格定义 ====================
    
    def _get_default_driver_spec(self) -> Dict:
        return {
            "driver_name": "default_driver",
            "interface_type": "virtual_if",
            "transaction_type": "transaction",
            "agent_config_type": "agent_config",
            "has_analysis_port": False,
            "reset_sequence": True,
            "reset_signal": "rst_n",
            "drive_phases": [
                {
                    "name": "main",
                    "description": "Main drive phase",
                    "code": "@(posedge vif.clk);\nvif.data <= tr.data;\nvif.valid <= 1'b1;\n@(posedge vif.clk);\nvif.valid <= 1'b0;"
                }
            ]
        }
    
    def _get_default_monitor_spec(self) -> Dict:
        return {
            "monitor_name": "default_monitor",
            "interface_type": "virtual_if",
            "transaction_type": "transaction",
            "agent_config_type": "agent_config",
            "has_coverage": False,
            "has_protocol_checker": False,
            "collect_steps": [
                {
                    "description": "Sample data",
                    "code": "@(posedge vif.clk);\nif(vif.valid) begin\n    trans_collected.data = vif.data;\nend"
                }
            ]
        }
    
    def _get_default_agent_spec(self) -> Dict:
        return {
            "agent_name": "default_agent",
            "sequencer_name": "sequencer",
            "driver_name": "driver",
            "monitor_name": "monitor",
            "config_type": "agent_config"
        }
    
    def _get_default_scoreboard_spec(self) -> Dict:
        return {
            "scoreboard_name": "default_scoreboard",
            "transaction_type": "transaction",
            "config_type": "scoreboard_config",
            "input_ports": [
                {"name": "actual", "transaction_type": "transaction"},
                {"name": "expected", "transaction_type": "transaction"}
            ],
            "predictor_name": "predictor",
            "compare_tasks": [
                {
                    "name": "compare_transactions",
                    "description": "Main comparison task",
                    "input_var": "actual",
                    "expected_var": "expected",
                    "actual_fifo": "actual_fifo",
                    "error_message": "Scoreboard mismatch detected"
                }
            ]
        }
    
    def _get_default_env_spec(self) -> Dict:
        return {
            "env_name": "default_env",
            "config_type": "env_config",
            "agents": [
                {
                    "class_name": "agent",
                    "instance_name": "m_agent",
                    "config_type": "agent_config",
                    "config_name": "agent_cfg"
                }
            ],
            "has_scoreboard": True,
            "scoreboard_name": "scoreboard",
            "has_coverage": True,
            "coverage_collector_name": "coverage_collector",
            "has_virtual_sequencer": True,
            "virtual_sequencer_name": "virtual_sequencer",
            "connections": [
                {
                    "description": "Monitor to Scoreboard",
                    "source": "m_agent.monitor",
                    "source_port": "item_collected_port",
                    "target": "scoreboard",
                    "target_port": "actual_export"
                }
            ],
            "virtual_sequencer_connections": [
                {"handle_name": "agent_sequencer", "agent_path": "m_agent"}
            ]
        }
    
    def _get_default_test_spec(self) -> Dict:
        return {
            "test_name": "base_test",
            "env_name": "env",
            "virtual_sequencer_name": "virtual_sequencer",
            "env_config_type": "env_config",
            "active_agent_cfg": "active_agent_cfg",
            "passive_agent_cfg": "passive_agent_cfg",
            "sequence_type": "base_sequence",
            "virtual_sequencer_path": "virtual_sequencer"
        }
    
    def _get_default_transaction_spec(self) -> Dict:
        return {
            "name": "transaction",
            "fields": ["rand bit [31:0] data", "rand bit [3:0] id"],
            "constraints": ["data inside {[0:255]}", "id inside {[0:15]}"]
        }
    
    def _get_default_sequence_spec(self) -> Dict:
        return {
            "name": "default_sequence",
            "item_type": "transaction",
            "random_vars": [
                {"type": "int unsigned", "name": "num_transactions", "default": 10}
            ],
            "constraints": [
                {"name": "num_transactions_c", "body": "num_transactions inside {[1:100]};"}
            ],
            "loop_variable": "num_transactions"
        }
    
    def _get_default_vsequence_spec(self) -> Dict:
        return {
            "name": "default_virtual_sequence",
            "sequencer_handles": [
                "agent_sequencer m_sequencer;"
            ],
            "sequence_code": [
                "base_sequence seq;",
                "seq = base_sequence::type_id::create(\"seq\");",
                "seq.start(m_sequencer);"
            ]
        }
    
    def _get_default_coverage_spec(self) -> Dict:
        return {
            "name": "default_coverage_collector",
            "transaction_type": "transaction",
            "covergroups": [
                {
                    "name": "data_cg",
                    "coverpoints": [
                        {
                            "name": "data_cp",
                            "signal": "data",
                            "bins": [
                                {"name": "low", "values": ["[0:63]"]},
                                {"name": "mid", "values": ["[64:191]"]},
                                {"name": "high", "values": ["[192:255]"]}
                            ]
                        }
                    ],
                    "crosses": []
                }
            ]
        }
    
    def _get_default_tb_top_spec(self) -> Dict:
        return {
            "name": "tb_top",
            "interfaces": ["virtual_if vif(clk, rst_n)"],
            "dut_instance": ["dut u_dut(.clk(clk), .rst_n(rst_n))"],
            "interface_connections": [],
            "config_db_sets": [
                "uvm_config_db #(virtual virtual_if)::set(null, \"*\", \"vif\", vif)"
            ],
            "test_name": "base_test",
            "dump_file": "waves.vcd"
        }
    
    def _get_default_interface_spec(self) -> Dict:
        return {
            "name": "default_interface",
            "signals": [
                "logic [31:0] data",
                "logic valid",
                "logic ready",
                "logic [3:0] id"
            ],
            "clocking_signals": [
                "output data",
                "output valid",
                "output id",
                "input ready"
            ]
        }
    
    def _get_default_package_spec(self) -> Dict:
        return {
            "name": "default_package",
            "imports": [],
            "includes": [
                "`include \"transaction.sv\"",
                "`include \"agent.sv\"",
                "`include \"env.sv\"",
                "`include \"base_test.sv\""
            ]
        }
    
    def _get_default_seq_library_spec(self) -> Dict:
        return {
            "name": "default_sequence_library",
            "sequences": [
                {"name": "base_sequence", "type": "base"},
                {"name": "random_sequence", "type": "random"}
            ],
            "selection_mode": "UVM_SEQ_LIB_RAND"
        }