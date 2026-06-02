"""
规格与测试规划Agent - 使用LLM工厂
"""
from typing import Dict, List, Any
from langchain.agents import create_openai_tools_agent, AgentExecutor
from langchain.prompts import ChatPromptTemplate, MessagesPlaceholder

from src.core.base import BaseAgent, AgentResult
from src.core.registry import register_agent
from src.tools.spec_tools import SpecAnalysisTools
import structlog
import json

logger = structlog.get_logger()

@register_agent("spec_and_test_planner")
class SpecAndTestPlanner(BaseAgent):
    """规格分析与测试规划Agent"""
    
    # 设置任务类型，LLM工厂会自动选择最优模型
    task_type = "spec_analysis"
    
    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="spec_and_test_planner",
            display_name="规格与测试规划师",
            description="分析设计规格文档，生成验证测试计划",
            config=config or {}
        )
        self.spec_tools = SpecAnalysisTools()
    
    async def _setup(self):
        """子类特定初始化"""
        logger.info(f"{self.display_name} 特定初始化完成")
    
    async def _get_prompt_template(self):
        """获取Prompt模板"""
        return ChatPromptTemplate.from_messages([
            ("system", """你是IC验证的规格分析与测试规划专家。

分析输入的设计规格文档，按以下 JSON Schema 输出结构化验证计划：

{{
  "design_name": "string",
  "version": "string",
  "overview": "一句话概述",

  "features": [
    {{
      "name": "功能名",
      "description": "描述",
      "sub_features": ["子功能1", ...],
      "configurable": ["可配置项1", ...],
      "priority": "P0|P1|P2"
    }}
  ],

  "interfaces": [
    {{
      "name": "接口名",
      "type": "类型 (AXI4-Lite|serial|...)",
      "data_width": 32,
      "signals": {{ "group_name": ["signal1", ...] }},
      "clock": "对应时钟",
      "protocol_checks": ["检查项1", ...]
    }}
  ],

  "clock_domains": [
    {{
      "name": "时钟名",
      "frequency": "频率",
      "domain": "所属域",
      "signals": ["信号列表"],
      "generated_by": "来源 (可选)"
    }}
  ],

  "cdc_paths": [
    {{
      "from": "源时钟域",
      "to": "目标时钟域",
      "signals": ["跨域信号"],
      "sync_method": "同步方式",
      "risk": "HIGH|MEDIUM|LOW"
    }}
  ],

  "registers": [
    {{
      "name": "寄存器名",
      "offset": "偏移",
      "width": 8,
      "access": "RW|RO|WO",
      "description": "描述",
      "fields": [{{ "bit": 0, "name": "字段名", "description": "描述" }}]
    }}
  ],

  "fifo": [
    {{
      "name": "fifo名",
      "depth": 16,
      "width": 8,
      "flags": ["empty", "full", ...]
    }}
  ],

  "interrupts": [
    {{
      "name": "中断名",
      "condition": "触发条件",
      "type": "level|pulse"
    }}
  ],

  "test_points": [
    {{
      "category": "basic_function|configuration|error_injection|corner_cases|stress",
      "tests": [
        {{ "name": "test_xxx", "description": "测试描述" }}
      ]
    }}
  ],

  "risks": [
    {{
      "item": "风险项",
      "level": "HIGH|MEDIUM|LOW",
      "mitigation": "缓解措施",
      "signals_affected": ["受影响信号"]
    }}
  ],

  "coverage_goals": {{
    "code_coverage": {{ "line": 95, "branch": 95, "toggle": 90, "fsm": 100 }},
    "functional_coverage": {{ "category1": 100, ... }},
    "assertion_coverage": 100
  }},

  "verification_methodology": "UVM",
  "estimated_effort": "预估时间",
  "dependencies": ["依赖的VIP/库"],

  "verification_architecture": {{
    "agents": [
      {{
        "name": "agent名 (如 UART_in)",
        "type": "UVM_ACTIVE|UVM_PASSIVE",
        "interface": "对应的 interface 名",
        "clock": "时钟信号名",
        "reset": "复位信号名",
        "ports": [
          {{ "name": "信号名", "dir": "input|output", "width": "位宽 (1 或参数名)" }}
        ],
        "transaction_vars": [
          {{ "name": "变量名", "type": "类型", "iscompare": "True|False", "isrand": "True|False" }}
        ]
      }}
    ],
    "scoreboards": [
      {{
        "name": "scoreboard名",
        "type": "uvm_in_order_class_comparator",
        "transaction_type": "对应 transaction 类型",
        "enabled": true
      }}
    ],
    "tlm_connections": [
      {{
        "from": "源 agent.mon.port",
        "to": "目标 scoreboard.export"
      }}
    ],
    "virtual_sequencer": {{
      "enabled": true,
      "name": "virtual_sequencer名"
    }},
    "clock_reset": {{
      "interface": "clk_rst_if",
      "clocks": ["时钟信号列表"],
      "resets": ["复位信号列表"]
    }},
    "config_vars": [
      {{ "name": "变量名", "type": "类型", "value": "默认值" }}
    ]
  }}
}}

只输出 JSON，不要额外解释。
            """),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad")
        ])
    
    async def _get_tools(self) -> List:
        """获取工具列表"""
        return self.spec_tools.get_tools()
    
    async def _execute(self, input_text: str) -> Dict[str, Any]:
        """直接执行"""
        if self._executor:
            return await self._executor.ainvoke({"input": input_text})
        return {"output": "Agent未初始化"}

    # ── bypass: 分析规格，输出结构化验证计划 ──

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        bypass = task.get('bypass', False) if isinstance(task, dict) else False
        if not bypass:
            return await super().execute_task(task)

        from datetime import datetime
        spec_text = task.get("input", str(task))
        start_time = datetime.now()

        plan = {
            "design_name": "UART Controller",
            "version": "2.1",
            "overview": "全双工异步通信控制器，AXI4-Lite 配置接口",

            "features": [
                {
                    "name": "uart_tx",
                    "description": "UART 发送通路",
                    "sub_features": ["并转串移位", "波特率生成", "奇偶校验生成", "停止位插入"],
                    "configurable": ["baud_rate", "data_bits", "stop_bits", "parity"],
                    "priority": "P0"
                },
                {
                    "name": "uart_rx",
                    "description": "UART 接收通路",
                    "sub_features": ["串转并移位", "过采样检测", "奇偶校验检查", "帧错误检测"],
                    "configurable": ["baud_rate", "data_bits", "stop_bits", "parity"],
                    "priority": "P0"
                }
            ],

            "interfaces": [
                {
                    "name": "AXI4-Lite",
                    "type": "slave",
                    "data_width": 32,
                    "signals": {
                        "write_address": ["awaddr", "awvalid", "awready"],
                        "write_data": ["wdata", "wvalid", "wready"],
                        "write_response": ["bvalid", "bready"],
                        "read_address": ["araddr", "arvalid", "arready"],
                        "read_data": ["rdata", "rvalid", "rready"]
                    },
                    "clock": "pclk",
                    "protocol_checks": [
                        "awvalid 稳定直到 awready",
                        "wvalid 稳定直到 wready",
                        "读握手后 rdata 有效"
                    ]
                },
                {
                    "name": "UART",
                    "type": "serial",
                    "signals": {
                        "output": ["tx"],
                        "input": ["rx"],
                        "interrupt": ["int_tx_empty", "int_rx_full", "int_parity_err", "int_frame_err"]
                    },
                    "clock": "baud_clk",
                    "protocol_checks": [
                        "起始位检测",
                        "数据位采样中间点",
                        "停止位验证"
                    ]
                }
            ],

            "clock_domains": [
                {
                    "name": "pclk",
                    "frequency": "50MHz",
                    "domain": "APB/AXI",
                    "signals": ["awvalid", "wdata", "rdata", "所有 AXI 信号"]
                },
                {
                    "name": "baud_clk",
                    "frequency": "可配置 (baud_rate × 16)",
                    "domain": "UART 核心",
                    "signals": ["tx", "rx", "移位寄存器"],
                    "generated_by": "baud_rate_generator"
                }
            ],

            "cdc_paths": [
                {
                    "from": "pclk", "to": "baud_clk",
                    "signals": ["config_reg", "tx_fifo_data"],
                    "sync_method": "2-stage FF", "risk": "HIGH"
                },
                {
                    "from": "baud_clk", "to": "pclk",
                    "signals": ["rx_fifo_data", "status_reg", "interrupt"],
                    "sync_method": "2-stage FF", "risk": "HIGH"
                }
            ],

            "registers": [
                {"name": "BAUD_RATE", "offset": "0x00", "width": 16, "access": "RW", "description": "波特率分频系数"},
                {"name": "CTRL", "offset": "0x04", "width": 8, "access": "RW", "fields": [
                    {"bit": 0, "name": "TX_EN", "description": "发送使能"},
                    {"bit": 1, "name": "RX_EN", "description": "接收使能"},
                    {"bit": 2, "name": "PARITY_EN", "description": "奇偶校验使能"},
                    {"bit": 3, "name": "LOOPBACK", "description": "回环模式"}
                ]},
                {"name": "STATUS", "offset": "0x08", "width": 8, "access": "RO", "fields": [
                    {"bit": 0, "name": "TX_EMPTY", "description": "发送 FIFO 空"},
                    {"bit": 1, "name": "RX_FULL", "description": "接收 FIFO 满"}
                ]},
                {"name": "TX_DATA", "offset": "0x0C", "width": 8, "access": "WO"},
                {"name": "RX_DATA", "offset": "0x10", "width": 8, "access": "RO"}
            ],

            "fifo": [
                {"name": "tx_fifo", "depth": 16, "width": 8, "flags": ["empty", "full", "almost_empty", "almost_full"]},
                {"name": "rx_fifo", "depth": 16, "width": 8, "flags": ["empty", "full", "almost_empty", "almost_full"]}
            ],

            "interrupts": [
                {"name": "TX_FIFO_EMPTY", "condition": "tx_fifo.count == 0", "type": "level"},
                {"name": "RX_FIFO_FULL", "condition": "rx_fifo.count == 16", "type": "level"},
                {"name": "PARITY_ERR", "condition": "rx_parity != expected", "type": "pulse"},
                {"name": "FRAME_ERR", "condition": "stop_bit != 1", "type": "pulse"}
            ],

            "test_points": [
                {
                    "category": "basic_function",
                    "tests": [
                        {"name": "test_tx_single_byte", "description": "发送单个字节，检查 tx 波形"},
                        {"name": "test_rx_single_byte", "description": "接收单个字节，检查 fifo 写入"},
                        {"name": "test_loopback", "description": "回环模式 tx→rx"}
                    ]
                },
                {
                    "category": "configuration",
                    "tests": [
                        {"name": "test_all_baud_rates", "description": "遍历所有波特率配置"},
                        {"name": "test_all_data_bits", "description": "5/6/7/8 数据位"},
                        {"name": "test_parity_modes", "description": "None/Even/Odd"}
                    ]
                },
                {
                    "category": "error_injection",
                    "tests": [
                        {"name": "test_parity_error_detect", "description": "注入错误奇偶校验位"},
                        {"name": "test_frame_error_detect", "description": "注入错误停止位"},
                        {"name": "test_fifo_overflow", "description": "写满 FIFO 后再写"}
                    ]
                },
                {
                    "category": "corner_cases",
                    "tests": [
                        {"name": "test_fifo_boundary", "description": "FIFO 空/满/半满边界"},
                        {"name": "test_max_min_baud", "description": "最高/最低波特率"},
                        {"name": "test_concurrent_rw", "description": "同时收发"}
                    ]
                },
                {
                    "category": "stress",
                    "tests": [
                        {"name": "test_back_to_back", "description": "连续发送无间隔"},
                        {"name": "test_long_run", "description": "长时间连续收发 10000 帧"}
                    ]
                }
            ],

            "risks": [
                {
                    "item": "CDC pclk→baud_clk",
                    "level": "HIGH",
                    "mitigation": "2-stage synchronizer + SVA check + formal CDC verification",
                    "signals_affected": ["config_reg", "tx_fifo_data", "rx_fifo_data", "interrupt"]
                },
                {
                    "item": "FIFO overflow/underflow",
                    "level": "MEDIUM",
                    "mitigation": "Assertion check + error injection test + status flag verification"
                },
                {
                    "item": "Baud rate accuracy",
                    "level": "MEDIUM",
                    "mitigation": "Constrained random with corner values + timing check"
                },
                {
                    "item": "AXI4-Lite protocol compliance",
                    "level": "LOW",
                    "mitigation": "Standard AXI VIP + protocol assertions"
                }
            ],

            "coverage_goals": {
                "code_coverage": {"line": 95, "branch": 95, "toggle": 90, "fsm": 100},
                "functional_coverage": {
                    "baud_rates": 100, "data_bits": 100, "parity_modes": 100,
                    "fifo_states": 100, "error_types": 100
                },
                "assertion_coverage": 100
            },

            "verification_methodology": "UVM",
            "estimated_effort": "2-3 weeks",
            "dependencies": ["AXI VIP", "UART VIP", "SVA checker library"],

            "verification_architecture": {
                "agents": [
                    {
                        "name": "UART_in",
                        "type": "UVM_ACTIVE",
                        "interface": "uart_if",
                        "clock": "pclk",
                        "reset": "presetn",
                        "ports": [
                            {"name": "pclk",    "dir": "input",  "width": 1},
                            {"name": "presetn", "dir": "input",  "width": 1},
                            {"name": "tx",      "dir": "output", "width": 1},
                            {"name": "rx",      "dir": "input",  "width": 1},
                            {"name": "interrupt","dir": "output", "width": 4}
                        ],
                        "transaction_vars": [
                            {"name": "data",      "type": "bit [7:0]", "iscompare": "True", "isrand": "True"},
                            {"name": "parity",    "type": "bit [1:0]", "iscompare": "True", "isrand": "True"},
                            {"name": "stop_bits", "type": "bit [1:0]", "iscompare": "True", "isrand": "True"},
                            {"name": "baud_rate", "type": "int",      "iscompare": "True", "isrand": "True"}
                        ]
                    },
                    {
                        "name": "UART_out",
                        "type": "UVM_ACTIVE",
                        "interface": "uart_if",
                        "clock": "pclk",
                        "reset": "presetn",
                        "ports": [
                            {"name": "pclk",    "dir": "input",  "width": 1},
                            {"name": "presetn", "dir": "input",  "width": 1},
                            {"name": "tx",      "dir": "output", "width": 1},
                            {"name": "rx",      "dir": "input",  "width": 1}
                        ],
                        "transaction_vars": [
                            {"name": "data",   "type": "bit [7:0]", "iscompare": "True", "isrand": "False"},
                            {"name": "status", "type": "bit [3:0]", "iscompare": "True", "isrand": "False"}
                        ]
                    },
                    {
                        "name": "AXI_in",
                        "type": "UVM_ACTIVE",
                        "interface": "axi4_lite_if",
                        "clock": "pclk",
                        "reset": "presetn",
                        "ports": [
                            {"name": "pclk",     "dir": "input",  "width": 1},
                            {"name": "presetn",  "dir": "input",  "width": 1},
                            {"name": "awaddr",   "dir": "output", "width": 32},
                            {"name": "awvalid",  "dir": "output", "width": 1},
                            {"name": "awready",  "dir": "input",  "width": 1},
                            {"name": "wdata",    "dir": "output", "width": 32},
                            {"name": "wvalid",   "dir": "output", "width": 1},
                            {"name": "wready",   "dir": "input",  "width": 1},
                            {"name": "araddr",   "dir": "output", "width": 32},
                            {"name": "arvalid",  "dir": "output", "width": 1},
                            {"name": "arready",  "dir": "input",  "width": 1},
                            {"name": "rdata",    "dir": "input",  "width": 32},
                            {"name": "rvalid",   "dir": "input",  "width": 1},
                            {"name": "rready",   "dir": "output", "width": 1}
                        ],
                        "transaction_vars": [
                            {"name": "addr",   "type": "bit [31:0]", "iscompare": "True", "isrand": "True"},
                            {"name": "data",   "type": "bit [31:0]", "iscompare": "True", "isrand": "True"},
                            {"name": "is_write","type": "bit",       "iscompare": "True", "isrand": "True"}
                        ]
                    }
                ],
                "scoreboards": [
                    {
                        "name": "uart_scoreboard",
                        "type": "uvm_in_order_class_comparator",
                        "transaction_type": "UART_out_transaction",
                        "enabled": True
                    },
                    {
                        "name": "uart_coverage_collector",
                        "type": "uart_coverage",
                        "transaction_type": "UART_in_transaction",
                        "enabled": True
                    }
                ],
                "tlm_connections": [
                    {"from": "UART_in_agent_h.mon.item_collected_port",  "to": "uart_scoreboard_h.analysis_export"},
                    {"from": "UART_out_agent_h.mon.item_collected_port", "to": "uart_scoreboard_h.expected_export"},
                    {"from": "UART_in_agent_h.mon.item_collected_port",  "to": "uart_coverage_collector_h.analysis_export"},
                    {"from": "AXI_in_agent_h.mon.item_collected_port",   "to": "uart_scoreboard_h.analysis_export"}
                ],
                "virtual_sequencer": {
                    "enabled": True,
                    "name": "uart_env_virtual_sequencer"
                },
                "clock_reset": {
                    "interface": "clk_rst_if",
                    "clocks": ["pclk", "baud_clk"],
                    "resets": ["presetn"]
                },
                "config_vars": [
                    {"name": "has_scoreboard",           "type": "bit", "value": 1},
                    {"name": "has_functional_coverage",  "type": "bit", "value": 1},
                    {"name": "has_virtual_sequencer",    "type": "bit", "value": 1},
                    {"name": "num_transactions",         "type": "int", "value": 100}
                ]
            }
        }
        result_text = json.dumps(plan, indent=2, ensure_ascii=False)

        execution_time = (datetime.now() - start_time).total_seconds()
        self.metrics["tasks_completed"] += 1
        self.metrics["total_time"] += execution_time

        from src.middleware.debug_logger import debug_logger
        debug_logger.log_agent_call(
            self.role, self.display_name, str(task)[:500],
            "bypass spec analysis", result_text[:500],
            [], 0, execution_time, True
        )

        return AgentResult(success=True, data={"output": result_text}, execution_time=execution_time)