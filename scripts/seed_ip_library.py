"""统一预置 IP 库 —— 一次性注册 229 个常用 IP。

覆盖四层：积木级（算术/计数/编解码/同步/协议/安全/电源/数据通路/状态机）
+ 外设级（UART/SPI/I2C/GPIO/Timer/FIFO）+ 总线级（APB/AXI/Wishbone）
+ 算法级（DSP/数学）+ 接口级（PCIe/USB/DDR/以太网）+ 互连级（AXI/AHB/NoC）。

用法:
    python scripts/seed_ip_library.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.knowledge_plane.ip_registry import IpRegistry


def _arith(width=32):
    return [{"name": "a", "dir": "input", "width": width},
            {"name": "b", "dir": "input", "width": width},
            {"name": "result", "dir": "output", "width": width}]


def _cmp(width=32):
    return [{"name": "a", "dir": "input", "width": width},
            {"name": "b", "dir": "input", "width": width},
            {"name": "eq", "dir": "output", "width": 1},
            {"name": "gt", "dir": "output", "width": 1},
            {"name": "lt", "dir": "output", "width": 1}]


def _cnt(width=16):
    return [{"name": "clk", "dir": "input", "width": 1},
            {"name": "rst_n", "dir": "input", "width": 1},
            {"name": "en", "dir": "input", "width": 1},
            {"name": "count", "dir": "output", "width": width},
            {"name": "terminal", "dir": "output", "width": 1}]


def _codec(in_w, out_w):
    return [{"name": "data_in", "dir": "input", "width": in_w},
            {"name": "data_out", "dir": "output", "width": out_w},
            {"name": "valid_in", "dir": "input", "width": 1},
            {"name": "valid_out", "dir": "output", "width": 1}]


def _sync():
    return [{"name": "clk", "dir": "input", "width": 1},
            {"name": "rst_n", "dir": "input", "width": 1},
            {"name": "data_in", "dir": "input", "width": 32},
            {"name": "data_out", "dir": "output", "width": 32}]


def _ctrl():
    return [{"name": "clk", "dir": "input", "width": 1},
            {"name": "rst_n", "dir": "input", "width": 1},
            {"name": "en", "dir": "input", "width": 1},
            {"name": "out", "dir": "output", "width": 1}]



def _dsp(width=16):
    return [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
            {"name":"data_in","dir":"input","width":width},{"name":"data_out","dir":"output","width":width},
            {"name":"valid_in","dir":"input","width":1},{"name":"valid_out","dir":"output","width":1}]


def _math(width=32):
    return [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
            {"name":"data_in","dir":"input","width":width},{"name":"data_out","dir":"output","width":width},
            {"name":"valid_in","dir":"input","width":1},{"name":"valid_out","dir":"output","width":1}]


def _dp(width=32):
    return [{"name":"data_in","dir":"input","width":width},{"name":"data_out","dir":"output","width":width}]


def _fsm():
    return [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
            {"name":"data_in","dir":"input","width":8},{"name":"detected","dir":"output","width":1}]


def _iface():
    return [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
            {"name":"data_in","dir":"input","width":32},{"name":"data_out","dir":"output","width":32},
            {"name":"valid","dir":"input","width":1},{"name":"ready","dir":"output","width":1}]


def _net():
    return [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
            {"name":"addr","dir":"input","width":32},{"name":"wdata","dir":"input","width":32},
            {"name":"rdata","dir":"output","width":32},{"name":"valid","dir":"input","width":1},
            {"name":"ready","dir":"output","width":1}]



ALL_IPS_0 = [
    ("apb_slave", "bus", [{'name': 'pclk', 'dir': 'input', 'width': 1}, {'name': 'preset_n', 'dir': 'input', 'width': 1}, {'name': 'paddr', 'dir': 'input', 'width': 8}, {'name': 'pwdata', 'dir': 'input', 'width': 8}, {'name': 'prdata', 'dir': 'output', 'width': 8}, {'name': 'pwrite', 'dir': 'input', 'width': 1}, {'name': 'psel', 'dir': 'input', 'width': 1}, {'name': 'penable', 'dir': 'input', 'width': 1}, {'name': 'pready', 'dir': 'output', 'width': 1}, {'name': 'pslverr', 'dir': 'output', 'width': 1}], "APB 从设备接口：寄存器读写，含 ready/error 响应"),
    ("apb_master", "bus", [{'name': 'pclk', 'dir': 'input', 'width': 1}, {'name': 'preset_n', 'dir': 'input', 'width': 1}, {'name': 'paddr', 'dir': 'output', 'width': 8}, {'name': 'pwdata', 'dir': 'output', 'width': 8}, {'name': 'prdata', 'dir': 'input', 'width': 8}, {'name': 'pwrite', 'dir': 'output', 'width': 1}, {'name': 'psel', 'dir': 'output', 'width': 1}, {'name': 'penable', 'dir': 'output', 'width': 1}], "APB 主设备接口：发起寄存器读写事务"),
    ("axi_lite_slave", "bus", [{'name': 'aclk', 'dir': 'input', 'width': 1}, {'name': 'areset_n', 'dir': 'input', 'width': 1}, {'name': 'awaddr', 'dir': 'input', 'width': 32}, {'name': 'awvalid', 'dir': 'input', 'width': 1}, {'name': 'awready', 'dir': 'output', 'width': 1}, {'name': 'wdata', 'dir': 'input', 'width': 32}, {'name': 'wvalid', 'dir': 'input', 'width': 1}, {'name': 'wready', 'dir': 'output', 'width': 1}, {'name': 'araddr', 'dir': 'input', 'width': 32}, {'name': 'arvalid', 'dir': 'input', 'width': 1}, {'name': 'arready', 'dir': 'output', 'width': 1}, {'name': 'rdata', 'dir': 'output', 'width': 32}, {'name': 'rvalid', 'dir': 'output', 'width': 1}, {'name': 'rready', 'dir': 'input', 'width': 1}], "AXI-Lite 从设备接口：轻量级 AXI4 读写"),
    ("wishbone_slave", "bus", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'adr', 'dir': 'input', 'width': 32}, {'name': 'dat_i', 'dir': 'input', 'width': 32}, {'name': 'dat_o', 'dir': 'output', 'width': 32}, {'name': 'we', 'dir': 'input', 'width': 1}, {'name': 'stb', 'dir': 'input', 'width': 1}, {'name': 'cyc', 'dir': 'input', 'width': 1}, {'name': 'ack', 'dir': 'output', 'width': 1}], "Wishbone 从设备接口：经典点对点总线"),
    ("uart_tx", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'tx', 'dir': 'output', 'width': 1}, {'name': 'data', 'dir': 'input', 'width': 8}, {'name': 'valid', 'dir': 'input', 'width': 1}, {'name': 'ready', 'dir': 'output', 'width': 1}, {'name': 'baud_div', 'dir': 'input', 'width': 16}], "UART 串行发送：起始位+数据位+校验位+停止位"),
    ("uart_rx", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'rx', 'dir': 'input', 'width': 1}, {'name': 'data', 'dir': 'output', 'width': 8}, {'name': 'valid', 'dir': 'output', 'width': 1}, {'name': 'baud_div', 'dir': 'input', 'width': 16}, {'name': 'frame_err', 'dir': 'output', 'width': 1}], "UART 串行接收：过采样恢复字节"),
    ("spi_master", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'sclk', 'dir': 'output', 'width': 1}, {'name': 'mosi', 'dir': 'output', 'width': 1}, {'name': 'miso', 'dir': 'input', 'width': 1}, {'name': 'cs_n', 'dir': 'output', 'width': 1}, {'name': 'data', 'dir': 'input', 'width': 8}, {'name': 'valid', 'dir': 'input', 'width': 1}], "SPI 主机：4 线串行外设接口"),
    ("spi_slave", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'sclk', 'dir': 'input', 'width': 1}, {'name': 'mosi', 'dir': 'input', 'width': 1}, {'name': 'miso', 'dir': 'output', 'width': 1}, {'name': 'cs_n', 'dir': 'input', 'width': 1}, {'name': 'data', 'dir': 'output', 'width': 8}], "SPI 从机：被动收发 8bit 数据"),
    ("i2c_master", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'scl', 'dir': 'output', 'width': 1}, {'name': 'sda', 'dir': 'inout', 'width': 1}, {'name': 'start', 'dir': 'input', 'width': 1}, {'name': 'stop', 'dir': 'input', 'width': 1}, {'name': 'busy', 'dir': 'output', 'width': 1}], "I2C 主机：START/STOP/ACK 时序"),
    ("i2c_slave", "serial", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'scl', 'dir': 'input', 'width': 1}, {'name': 'sda', 'dir': 'inout', 'width': 1}, {'name': 'addr', 'dir': 'input', 'width': 7}], "I2C 从机：地址匹配 + 收发"),
    ("gpio", "peripheral", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'gpio_in', 'dir': 'input', 'width': 32}, {'name': 'gpio_out', 'dir': 'output', 'width': 32}, {'name': 'gpio_oe', 'dir': 'output', 'width': 32}], "通用 IO：方向控制 + 输出使能"),
    ("timer", "peripheral", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'load', 'dir': 'input', 'width': 32}, {'name': 'enable', 'dir': 'input', 'width': 1}, {'name': 'count', 'dir': 'output', 'width': 32}, {'name': 'expired', 'dir': 'output', 'width': 1}], "定时器/计数器：递减到 0 触发"),
    ("pwm", "peripheral", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'period', 'dir': 'input', 'width': 16}, {'name': 'duty', 'dir': 'input', 'width': 16}, {'name': 'enable', 'dir': 'input', 'width': 1}, {'name': 'pwm_out', 'dir': 'output', 'width': 1}], "脉宽调制：可配周期/占空比"),
    ("watchdog", "peripheral", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'kick', 'dir': 'input', 'width': 1}, {'name': 'timeout', 'dir': 'input', 'width': 32}, {'name': 'wdg_irq', 'dir': 'output', 'width': 1}, {'name': 'wdg_reset', 'dir': 'output', 'width': 1}], "看门狗定时器：喂狗超时触发"),
    ("interrupt_controller", "peripheral", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'irq_in', 'dir': 'input', 'width': 32}, {'name': 'irq_en', 'dir': 'input', 'width': 32}, {'name': 'irq_out', 'dir': 'output', 'width': 1}, {'name': 'irq_id', 'dir': 'output', 'width': 5}], "中断控制器：优先级仲裁 + 中断号输出"),
    ("sync_fifo", "memory", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'wr_en', 'dir': 'input', 'width': 1}, {'name': 'wr_data', 'dir': 'input', 'width': 8}, {'name': 'rd_en', 'dir': 'input', 'width': 1}, {'name': 'rd_data', 'dir': 'output', 'width': 8}, {'name': 'full', 'dir': 'output', 'width': 1}, {'name': 'empty', 'dir': 'output', 'width': 1}], "同步 FIFO：单时钟域"),
    ("async_fifo", "memory", [{'name': 'wr_clk', 'dir': 'input', 'width': 1}, {'name': 'rd_clk', 'dir': 'input', 'width': 1}, {'name': 'wr_en', 'dir': 'input', 'width': 1}, {'name': 'rd_en', 'dir': 'input', 'width': 1}, {'name': 'wr_data', 'dir': 'input', 'width': 8}, {'name': 'rd_data', 'dir': 'output', 'width': 8}, {'name': 'full', 'dir': 'output', 'width': 1}, {'name': 'empty', 'dir': 'output', 'width': 1}], "异步 FIFO：双时钟域格雷码指针"),
    ("dual_port_ram", "memory", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'wr_en', 'dir': 'input', 'width': 1}, {'name': 'wr_addr', 'dir': 'input', 'width': 8}, {'name': 'wr_data', 'dir': 'input', 'width': 32}, {'name': 'rd_addr', 'dir': 'input', 'width': 8}, {'name': 'rd_data', 'dir': 'output', 'width': 32}], "双口 RAM：独立读写端口"),
    ("register_file", "memory", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'wr_en', 'dir': 'input', 'width': 1}, {'name': 'wr_addr', 'dir': 'input', 'width': 5}, {'name': 'wr_data', 'dir': 'input', 'width': 32}, {'name': 'rd_addr', 'dir': 'input', 'width': 5}, {'name': 'rd_data', 'dir': 'output', 'width': 32}], "寄存器文件：多寄存器读写"),
    ("shift_register", "memory", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'load', 'dir': 'input', 'width': 1}, {'name': 'data_in', 'dir': 'input', 'width': 8}, {'name': 'shift_en', 'dir': 'input', 'width': 1}, {'name': 'data_out', 'dir': 'output', 'width': 1}], "移位寄存器：并行载入串行移出"),
    ("arbiter", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'req', 'dir': 'input', 'width': 4}, {'name': 'grant', 'dir': 'output', 'width': 4}], "固定优先级仲裁器"),
    ("round_robin_arbiter", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'req', 'dir': 'input', 'width': 4}, {'name': 'grant', 'dir': 'output', 'width': 4}], "轮询仲裁器：公平轮转"),
    ("handshake_sync", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'valid', 'dir': 'input', 'width': 1}, {'name': 'ready', 'dir': 'input', 'width': 1}, {'name': 'data_in', 'dir': 'input', 'width': 32}, {'name': 'data_out', 'dir': 'output', 'width': 32}], "Ready/Valid 握手同步器"),
    ("edge_detector", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'sig_in', 'dir': 'input', 'width': 1}, {'name': 'pos_edge', 'dir': 'output', 'width': 1}, {'name': 'neg_edge', 'dir': 'output', 'width': 1}], "边沿检测：上升/下降沿脉冲"),
    ("cdc_sync", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'sig_in', 'dir': 'input', 'width': 1}, {'name': 'sig_out', 'dir': 'output', 'width': 1}], "跨时钟域同步器：两级触发器"),
    ("clock_divider", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'div', 'dir': 'input', 'width': 16}, {'name': 'clk_out', 'dir': 'output', 'width': 1}], "时钟分频器：整数分频"),
    ("gray_counter", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'en', 'dir': 'input', 'width': 1}, {'name': 'count', 'dir': 'output', 'width': 4}], "格雷码计数器：FIFO 指针用"),
    ("crc", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'data', 'dir': 'input', 'width': 8}, {'name': 'valid', 'dir': 'input', 'width': 1}, {'name': 'crc_out', 'dir': 'output', 'width': 32}], "CRC-32 校验"),
    ("priority_encoder", "control", [{'name': 'req', 'dir': 'input', 'width': 8}, {'name': 'idx', 'dir': 'output', 'width': 3}, {'name': 'valid', 'dir': 'output', 'width': 1}], "优先级编码器：最高位优先"),
    ("pulse_stretcher", "control", [{'name': 'clk', 'dir': 'input', 'width': 1}, {'name': 'rst_n', 'dir': 'input', 'width': 1}, {'name': 'pulse_in', 'dir': 'input', 'width': 1}, {'name': 'stretch', 'dir': 'input', 'width': 16}, {'name': 'pulse_out', 'dir': 'output', 'width': 1}], "脉冲展宽：窄脉冲展宽"),
]

ALL_IPS_1 = [
    # ── 算术 arithmetic（20）──
    ("adder", "arithmetic", _arith(32), "加法器：a+b 无进位"),
    ("adder_cin", "arithmetic", _arith(32), "加法器：a+b+cin 带进位输入"),
    ("subtractor", "arithmetic", _arith(32), "减法器：a-b"),
    ("adder_subtractor", "arithmetic", _arith(32), "加减法器：add_sub 选择加/减"),
    ("multiplier", "arithmetic", _arith(16), "乘法器：a*b 组合逻辑"),
    ("multiplier_pipeline", "arithmetic", _arith(16), "流水线乘法器：多级流水"),
    ("divider", "arithmetic", _arith(32), "除法器：a/b 恢复余数法"),
    ("alu", "arithmetic", [{"name":"a","dir":"input","width":32},{"name":"b","dir":"input","width":32},
                           {"name":"op","dir":"input","width":4},{"name":"result","dir":"output","width":32},
                           {"name":"zero","dir":"output","width":1},{"name":"negative","dir":"output","width":1}],
     "算术逻辑单元：加/减/与/或/异或/移位"),
    ("mac", "arithmetic", [{"name":"a","dir":"input","width":16},{"name":"b","dir":"input","width":16},
                           {"name":"acc_in","dir":"input","width":32},{"name":"acc_out","dir":"output","width":32}],
     "乘累加器：acc += a*b"),
    ("comparator", "arithmetic", _cmp(32), "比较器：eq/gt/lt"),
    ("magnitude_comparator", "arithmetic", _cmp(32), "数值比较器：无符号比较"),
    ("signed_comparator", "arithmetic", _cmp(32), "有符号比较器"),
    ("barrel_shifter", "arithmetic", [{"name":"data","dir":"input","width":32},{"name":"shift","dir":"input","width":5},
                                      {"name":"dir","dir":"input","width":1},{"name":"result","dir":"output","width":32}],
     "桶形移位器：任意移位量"),
    ("shifter", "arithmetic", [{"name":"data","dir":"input","width":32},{"name":"shift","dir":"input","width":5},
                               {"name":"mode","dir":"input","width":2},{"name":"result","dir":"output","width":32}],
     "移位器：逻辑/算术/循环移位"),
    ("absolute_value", "arithmetic", _arith(32), "绝对值：|a|"),
    ("min_max", "arithmetic", [{"name":"a","dir":"input","width":32},{"name":"b","dir":"input","width":32},
                               {"name":"min","dir":"output","width":32},{"name":"max","dir":"output","width":32}],
     "最小值/最大值"),
    ("saturating_adder", "arithmetic", _arith(32), "饱和加法器：溢出钳位"),
    ("carry_lookahead_adder", "arithmetic", _arith(32), "超前进位加法器"),
    ("ripple_carry_adder", "arithmetic", _arith(32), "行波进位加法器"),
    ("bcd_adder", "arithmetic", _arith(8), "BCD 加法器：十进制校正"),

    # ── 计数器 counter（15）──
    ("binary_counter", "counter", _cnt(16), "二进制计数器"),
    ("up_down_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                    {"name":"up","dir":"input","width":1},{"name":"down","dir":"input","width":1},
                                    {"name":"count","dir":"output","width":16}], "可逆计数器"),
    ("johnson_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                    {"name":"q","dir":"output","width":8}], "约翰逊计数器：2n 状态"),
    ("ring_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                 {"name":"q","dir":"output","width":8}], "环形计数器：单热移位"),
    ("mod_n_counter", "counter", _cnt(16), "模 N 计数器：到 N 清零"),
    ("bcd_counter", "counter", _cnt(8), "BCD 计数器：0-9"),
    ("decade_counter", "counter", _cnt(8), "十进制计数器"),
    ("loadable_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                     {"name":"load","dir":"input","width":1},{"name":"data","dir":"input","width":16},
                                     {"name":"count","dir":"output","width":16}], "可加载计数器"),
    ("enable_counter", "counter", _cnt(16), "使能计数器"),
    ("free_run_counter", "counter", _cnt(32), "自由运行计数器：循环计数"),
    ("prescaler", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                              {"name":"div","dir":"input","width":16},{"name":"clk_out","dir":"output","width":1}],
     "预分频器：时钟分频"),
    ("divide_by_n", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                {"name":"n","dir":"input","width":16},{"name":"clk_out","dir":"output","width":1}],
     "N 分频器"),
    ("frequency_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                      {"name":"gate","dir":"input","width":1},{"name":"count","dir":"output","width":32}],
     "频率计数器：闸门内计数"),
    ("pulse_counter", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                  {"name":"pulse","dir":"input","width":1},{"name":"count","dir":"output","width":32}],
     "脉冲计数器：计数脉冲数"),
    ("programmable_timer", "counter", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                       {"name":"reload","dir":"input","width":32},{"name":"expired","dir":"output","width":1}],
     "可编程定时器"),

    # ── 编码解码 codec（15）──
    ("encoder_8to3", "codec", _codec(8, 3), "8-3 编码器"),
    ("decoder_3to8", "codec", _codec(3, 8), "3-8 解码器"),
    ("priority_encoder", "codec", _codec(8, 3), "优先级编码器：最高位优先"),
    ("bcd_to_7seg", "codec", _codec(4, 7), "BCD 到 7 段显示"),
    ("binary_to_gray", "codec", _codec(8, 8), "二进制转格雷码"),
    ("gray_to_binary", "codec", _codec(8, 8), "格雷码转二进制"),
    ("bcd_to_binary", "codec", _codec(8, 8), "BCD 转二进制"),
    ("binary_to_bcd", "codec", _codec(8, 12), "二进制转 BCD：double dabble"),
    ("thermometer_decoder", "codec", _codec(4, 15), "温度计码解码器"),
    ("one_hot_encoder", "codec", _codec(8, 3), "独热码编码器"),
    ("one_hot_decoder", "codec", _codec(3, 8), "独热码解码器"),
    ("manchester_encoder", "codec", _codec(1, 1), "曼彻斯特编码器"),
    ("manchester_decoder", "codec", _codec(1, 1), "曼彻斯特解码器"),
    ("scrambler", "codec", _codec(8, 8), "扰码器：LFSR 加扰"),
    ("descrambler", "codec", _codec(8, 8), "解扰器：LFSR 解扰"),

    # ── 同步 sync（10）──
    ("bit_sync", "sync", _sync(), "单 bit 同步器：两级触发器"),
    ("bus_sync", "sync", _sync(), "总线同步器：多位数据跨时钟域"),
    ("pulse_sync", "sync", _sync(), "脉冲同步器：跨时钟域脉冲传递"),
    ("reset_sync", "sync", [{"name":"clk","dir":"input","width":1},{"name":"rst_n_in","dir":"input","width":1},
                            {"name":"rst_n_out","dir":"output","width":1}], "复位同步器：异步复位同步释放"),
    ("level_sync", "sync", _sync(), "电平同步器"),
    ("edge_sync", "sync", _sync(), "边沿同步器"),
    ("async_reset_sync", "sync", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                  {"name":"rst_n_sync","dir":"output","width":1}], "异步复位同步器"),
    ("fifo_pointer_sync", "sync", [{"name":"clk","dir":"input","width":1},{"name":"ptr","dir":"input","width":4},
                                   {"name":"ptr_sync","dir":"output","width":4}], "FIFO 格雷码指针同步"),
    ("data_sync", "sync", _sync(), "数据同步器"),
    ("clock_domain_crossing", "sync", _sync(), "跨时钟域传输"),

    # ── 协议 protocol（10）──
    ("valid_ready_reg", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                     {"name":"valid_in","dir":"input","width":1},{"name":"ready_in","dir":"input","width":1},
                                     {"name":"data_in","dir":"input","width":32},{"name":"valid_out","dir":"output","width":1},
                                     {"name":"ready_out","dir":"output","width":1},{"name":"data_out","dir":"output","width":32}],
     "Valid/Ready 流水线寄存器"),
    ("pipeline_reg", "protocol", _sync(), "流水线寄存器：单级打拍"),
    ("skid_buffer", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                 {"name":"valid_in","dir":"input","width":1},{"name":"ready_in","dir":"input","width":1},
                                 {"name":"data_in","dir":"input","width":32},{"name":"valid_out","dir":"output","width":1},
                                 {"name":"ready_out","dir":"output","width":1},{"name":"data_out","dir":"output","width":32}],
     "Skid Buffer：防反压丢数据"),
    ("mux_2to1", "protocol", [{"name":"a","dir":"input","width":32},{"name":"b","dir":"input","width":32},
                              {"name":"sel","dir":"input","width":1},{"name":"y","dir":"output","width":32}],
     "2 选 1 多路选择器"),
    ("mux_4to1", "protocol", [{"name":"d","dir":"input","width":128},{"name":"sel","dir":"input","width":2},
                              {"name":"y","dir":"output","width":32}], "4 选 1 多路选择器"),
    ("demux_1to2", "protocol", [{"name":"d","dir":"input","width":32},{"name":"sel","dir":"input","width":1},
                                {"name":"y0","dir":"output","width":32},{"name":"y1","dir":"output","width":32}],
     "1 分 2 解复用器"),
    ("arbiter_rr", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                {"name":"req","dir":"input","width":4},{"name":"grant","dir":"output","width":4}],
     "轮询仲裁器"),
    ("matrix_arbiter", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                    {"name":"req","dir":"input","width":4},{"name":"grant","dir":"output","width":4}],
     "矩阵仲裁器：并行请求"),
    ("token_arbiter", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                   {"name":"req","dir":"input","width":4},{"name":"grant","dir":"output","width":4}],
     "令牌仲裁器"),
    ("credit_counter", "protocol", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                    {"name":"credit_inc","dir":"input","width":1},{"name":"credit_dec","dir":"input","width":1},
                                    {"name":"credit","dir":"output","width":8}], "信用计数器：流控"),

    # ── 安全 security（10）──
    ("lfsr", "security", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                          {"name":"en","dir":"input","width":1},{"name":"out","dir":"output","width":16}],
     "线性反馈移位寄存器：伪随机序列"),
    ("prng", "security", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                          {"name":"en","dir":"input","width":1},{"name":"random","dir":"output","width":32}],
     "伪随机数发生器"),
    ("crc8", "security", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                          {"name":"data","dir":"input","width":8},{"name":"valid","dir":"input","width":1},
                          {"name":"crc","dir":"output","width":8}], "CRC-8 校验"),
    ("crc16", "security", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                           {"name":"data","dir":"input","width":8},{"name":"valid","dir":"input","width":1},
                           {"name":"crc","dir":"output","width":16}], "CRC-16 校验"),
    ("parity_gen", "security", [{"name":"data","dir":"input","width":8},{"name":"parity","dir":"output","width":1}],
     "奇偶校验生成器"),
    ("parity_check", "security", [{"name":"data","dir":"input","width":8},{"name":"parity","dir":"input","width":1},
                                  {"name":"error","dir":"output","width":1}], "奇偶校验检查器"),
    ("hamming_encode", "security", _codec(4, 7), "汉明编码：4->7"),
    ("hamming_decode", "security", _codec(7, 4), "汉明解码：纠错"),
    ("aes_sbox", "security", _codec(8, 8), "AES S-Box 替换"),
    ("des_round", "security", [{"name":"data","dir":"input","width":64},{"name":"key","dir":"input","width":48},
                               {"name":"result","dir":"output","width":64}], "DES 单轮"),

    # ── 电源 power（10）──
    ("clock_gate", "power", [{"name":"clk_in","dir":"input","width":1},{"name":"en","dir":"input","width":1},
                             {"name":"clk_out","dir":"output","width":1}], "时钟门控：门控时钟"),
    ("clock_gate_latch", "power", [{"name":"clk_in","dir":"input","width":1},{"name":"en","dir":"input","width":1},
                                   {"name":"clk_out","dir":"output","width":1}], "带锁存时钟门控"),
    ("power_gate", "power", [{"name":"clk","dir":"input","width":1},{"name":"sleep","dir":"input","width":1},
                             {"name":"isolation","dir":"input","width":1},{"name":"pwr_state","dir":"output","width":2}],
     "电源门控：sleep/isolation 控制"),
    ("level_shifter", "power", [{"name":"data_in","dir":"input","width":1},{"name":"vdd_low","dir":"input","width":1},
                                {"name":"data_out","dir":"output","width":1}], "电平转换器"),
    ("isolation_cell", "power", [{"name":"data_in","dir":"input","width":1},{"name":"isolate","dir":"input","width":1},
                                 {"name":"data_out","dir":"output","width":1}], "隔离单元"),
    ("retention_flop", "power", [{"name":"clk","dir":"input","width":1},{"name":"save","dir":"input","width":1},
                                 {"name":"restore","dir":"input","width":1},{"name":"d","dir":"input","width":1},
                                 {"name":"q","dir":"output","width":1}], "保持寄存器"),
    ("pulse_generator", "power", [{"name":"clk","dir":"input","width":1},{"name":"trigger","dir":"input","width":1},
                                  {"name":"pulse","dir":"output","width":1}], "脉冲发生器"),
    ("one_shot", "power", [{"name":"clk","dir":"input","width":1},{"name":"trigger","dir":"input","width":1},
                           {"name":"pulse","dir":"output","width":1}], "单稳态：触发输出单脉冲"),
    ("debouncer", "power", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                            {"name":"sig_in","dir":"input","width":1},{"name":"sig_out","dir":"output","width":1}],
     "去抖器：按键去抖"),
    ("glitch_filter", "power", [{"name":"clk","dir":"input","width":1},{"name":"sig_in","dir":"input","width":1},
                                {"name":"sig_out","dir":"output","width":1}], "毛刺滤波器"),

    # ── 存储扩展 memory_ext（10）──
    ("rom", "memory", [{"name":"addr","dir":"input","width":10},{"name":"data","dir":"output","width":32}],
     "ROM：只读存储器"),
    ("stack", "memory", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                         {"name":"push","dir":"input","width":1},{"name":"pop","dir":"input","width":1},
                         {"name":"data_in","dir":"input","width":32},{"name":"data_out","dir":"output","width":32},
                         {"name":"empty","dir":"output","width":1},{"name":"full","dir":"output","width":1}],
     "栈：LIFO"),
    ("queue", "memory", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                         {"name":"enq","dir":"input","width":1},{"name":"deq","dir":"input","width":1},
                         {"name":"data_in","dir":"input","width":32},{"name":"data_out","dir":"output","width":32},
                         {"name":"empty","dir":"output","width":1},{"name":"full","dir":"output","width":1}],
     "队列：FIFO"),
    ("cam", "memory", [{"name":"clk","dir":"input","width":1},{"name":"key","dir":"input","width":32},
                       {"name":"match","dir":"output","width":1},{"name":"addr","dir":"output","width":8}],
     "内容寻址存储器"),
    ("reg_bank", "memory", [{"name":"clk","dir":"input","width":1},{"name":"we","dir":"input","width":1},
                            {"name":"addr","dir":"input","width":5},{"name":"data_in","dir":"input","width":32},
                            {"name":"data_out","dir":"output","width":32}], "寄存器组"),
    ("dual_clock_fifo", "memory", [{"name":"wr_clk","dir":"input","width":1},{"name":"rd_clk","dir":"input","width":1},
                                   {"name":"wr_en","dir":"input","width":1},{"name":"rd_en","dir":"input","width":1},
                                   {"name":"wr_data","dir":"input","width":8},{"name":"rd_data","dir":"output","width":8},
                                   {"name":"full","dir":"output","width":1},{"name":"empty","dir":"output","width":1}],
     "双时钟 FIFO"),
    ("latch_array", "memory", [{"name":"en","dir":"input","width":1},{"name":"addr","dir":"input","width":4},
                               {"name":"data_in","dir":"input","width":32},{"name":"data_out","dir":"output","width":32}],
     "锁存器阵列"),
    ("sram_controller", "memory", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                   {"name":"we","dir":"input","width":1},{"name":"addr","dir":"input","width":16},
                                   {"name":"wdata","dir":"input","width":32},{"name":"rdata","dir":"output","width":32}],
     "SRAM 控制器"),
    ("content_addressable", "memory", [{"name":"clk","dir":"input","width":1},{"name":"key","dir":"input","width":32},
                                       {"name":"match","dir":"output","width":1},{"name":"index","dir":"output","width":8}],
     "内容可寻址查找"),
    ("circular_buffer", "memory", [{"name":"clk","dir":"input","width":1},{"name":"rst_n","dir":"input","width":1},
                                   {"name":"wr_en","dir":"input","width":1},{"name":"rd_en","dir":"input","width":1},
                                   {"name":"data_in","dir":"input","width":8},{"name":"data_out","dir":"output","width":8}],
     "环形缓冲区"),
]



ALL_IPS_2 = [
    # ── DSP 信号处理（20）──
    ("fir_filter", "dsp", _dsp(16), "FIR 滤波器：有限冲激响应，N 阶抽头"),
    ("iir_filter", "dsp", _dsp(16), "IIR 滤波器：无限冲激响应，反馈结构"),
    ("fft", "dsp", _dsp(16), "FFT：快速傅里叶变换（基 2 蝶形）"),
    ("ifft", "dsp", _dsp(16), "IFFT：快速傅里叶逆变换"),
    ("convolution", "dsp", _dsp(16), "卷积运算：滑动窗口乘累加"),
    ("interpolator", "dsp", _dsp(16), "插值器：上采样 + 滤波"),
    ("decimator", "dsp", _dsp(16), "抽取器：下采样 + 抗混叠滤波"),
    ("cordic", "dsp", _dsp(32), "CORDIC：坐标旋转数字计算（三角/向量）"),
    ("nco", "dsp", _dsp(32), "NCO：数控振荡器（相位累加）"),
    ("sine_generator", "dsp", _dsp(16), "正弦波发生器：查表或 CORDIC"),
    ("accumulator", "dsp", _dsp(32), "累加器：连续累加求和"),
    ("differentiator", "dsp", _dsp(16), "差分器：相邻样本差值"),
    ("absolute_diff", "dsp", _dsp(16), "绝对差：|a-b|"),
    ("limiter", "dsp", _dsp(16), "限幅器：钳位到上下限"),
    ("moving_average", "dsp", _dsp(16), "滑动平均：N 点均值滤波"),
    ("dot_product", "dsp", _dsp(32), "点积：两向量乘累加"),
    ("matrix_mult", "dsp", _dsp(32), "矩阵乘法：A*B"),
    ("quantizer", "dsp", _dsp(16), "量化器：定点量化"),
    ("rounder", "dsp", _dsp(16), "舍入器：四舍五入/截断"),
    ("clipper", "dsp", _dsp(16), "裁剪器：饱和裁剪"),

    # ── 数学 math（15）──
    ("sqrt", "math", _math(32), "平方根：逐位/牛顿迭代"),
    ("logarithm", "math", _math(32), "对数：log2 近似"),
    ("exponent", "math", _math(32), "指数：2^x 近似"),
    ("sine", "math", _math(32), "正弦函数"),
    ("cosine", "math", _math(32), "余弦函数"),
    ("tangent", "math", _math(32), "正切函数"),
    ("float_adder", "math", _math(32), "浮点加法器：IEEE754"),
    ("float_multiplier", "math", _math(32), "浮点乘法器：IEEE754"),
    ("float_divider", "math", _math(32), "浮点除法器：IEEE754"),
    ("fixed_to_float", "math", _math(32), "定点转浮点"),
    ("float_to_fixed", "math", _math(32), "浮点转定点"),
    ("reciprocal", "math", _math(32), "倒数：1/x"),
    ("reciprocal_sqrt", "math", _math(32), "倒数平方根：1/sqrt(x)"),
    ("power", "math", _math(32), "幂运算：x^y"),
    ("modulo", "math", _math(32), "模运算：a mod b"),

    # ── 数据通路 datapath（15）──
    ("register", "datapath", _dp(32), "寄存器：D 触发器"),
    ("latch", "datapath", _dp(32), "锁存器：电平敏感"),
    ("tri_state_buffer", "datapath", _dp(32), "三态缓冲器：高阻输出"),
    ("bit_extend", "datapath", _dp(32), "位扩展：零/符号扩展"),
    ("bit_select", "datapath", _dp(32), "位选择：提取指定位段"),
    ("bit_reverse", "datapath", _dp(32), "位反转：bit 顺序颠倒"),
    ("bit_count", "datapath", _dp(32), "位计数：popcount（1 的个数）"),
    ("leading_zero_count", "datapath", _dp(32), "前导零计数：CLZ"),
    ("trailing_zero_count", "datapath", _dp(32), "尾随零计数：CTZ"),
    ("sign_extend", "datapath", _dp(32), "符号扩展：按符号位扩展"),
    ("zero_extend", "datapath", _dp(32), "零扩展：高位补零"),
    ("parity_tree", "datapath", _dp(32), "奇偶校验树：多输入 XOR"),
    ("priority_tree", "datapath", _dp(32), "优先级树：最高有效位"),
    ("bit_rotate", "datapath", _dp(32), "位循环移位"),
    ("bit_swap", "datapath", _dp(32), "位交换：字节/半字交换"),

    # ── 状态机 fsm（10）──
    ("moore_fsm", "fsm", _fsm(), "Moore 状态机：输出仅依赖状态"),
    ("mealy_fsm", "fsm", _fsm(), "Mealy 状态机：输出依赖状态+输入"),
    ("sequence_detector", "fsm", _fsm(), "序列检测器：检测特定位序列"),
    ("pulse_sync_fsm", "fsm", _fsm(), "脉冲同步状态机：跨时钟脉冲"),
    ("arbiter_fsm", "fsm", _fsm(), "仲裁状态机：请求仲裁"),
    ("handshake_fsm", "fsm", _fsm(), "握手状态机：valid/ready 握手"),
    ("counter_fsm", "fsm", _fsm(), "计数状态机：状态计数"),
    ("state_register", "fsm", _fsm(), "状态寄存器：状态保持"),
    ("state_decoder", "fsm", _fsm(), "状态解码器：状态→输出"),
    ("state_transition", "fsm", _fsm(), "状态转换逻辑：次态逻辑"),

    # ── 高级接口 interface（20）──
    ("pcie_interface", "interface", _iface(), "PCIe 接口：串行高速互连"),
    ("usb_interface", "interface", _iface(), "USB 接口：通用串行总线"),
    ("ddr_controller", "interface", _iface(), "DDR 控制器：SDRAM 时序"),
    ("ethernet_mac", "interface", _iface(), "以太网 MAC：帧收发"),
    ("sd_card_interface", "interface", _iface(), "SD 卡接口：存储卡协议"),
    ("hdmi_interface", "interface", _iface(), "HDMI 接口：音视频传输"),
    ("vga_controller", "interface", _iface(), "VGA 控制器：显示时序"),
    ("can_controller", "interface", _iface(), "CAN 控制器：车载总线"),
    ("lin_controller", "interface", _iface(), "LIN 控制器：低速车身总线"),
    ("jtag_interface", "interface", _iface(), "JTAG 接口：边界扫描"),
    ("sdram_controller", "interface", _iface(), "SDRAM 控制器：刷新/突发"),
    ("flash_controller", "interface", _iface(), "Flash 控制器：NOR/NAND"),
    ("eeprom_interface", "interface", _iface(), "EEPROM 接口：I2C 存储器"),
    ("temp_sensor_interface", "interface", _iface(), "温度传感器接口：采样"),
    ("adc_interface", "interface", _iface(), "ADC 接口：模数转换"),
    ("dac_interface", "interface", _iface(), "DAC 接口：数模转换"),
    ("stepper_motor_controller", "interface", _iface(), "步进电机控制器：相位控制"),
    ("quadrature_decoder", "interface", _iface(), "正交解码器：编码器计数"),
    ("pwm_controller", "interface", _iface(), "PWM 控制器：多通道"),
    ("audio_codec", "interface", _iface(), "音频编解码器：I2S"),

    # ── 网络互连 network（20）──
    ("axi4_full", "network", _net(), "AXI4 Full：完整读写通道"),
    ("axi_stream", "network", _net(), "AXI Stream：流式数据传输"),
    ("ahb", "network", _net(), "AHB：AMBA 高性能总线"),
    ("ahb_lite", "network", _net(), "AHB-Lite：轻量级 AHB"),
    ("apb_bridge", "network", _net(), "APB 桥：AXI/AHB 转 APB"),
    ("axi_bridge", "network", _net(), "AXI 桥：协议转换"),
    ("axi_interconnect", "network", _net(), "AXI 互连：多主多从路由"),
    ("crossbar", "network", _net(), "交叉开关：全连接互连"),
    ("noc_router", "network", _net(), "NoC 路由器：片上网络路由"),
    ("fifo_variant", "network", _net(), "FIFO 变体：可配深度/宽度"),
    ("arbiter_variant", "network", _net(), "仲裁器变体：多种仲裁策略"),
    ("pipeline_variant", "network", _net(), "流水线变体：多级流水"),
    ("backpressure", "network", _net(), "背压控制：反压传播"),
    ("credit_flow_control", "network", _net(), "信用流控：基于信用的流控"),
    ("reorder_buffer", "network", _net(), "重排序缓冲：乱序恢复"),
    ("dedup", "network", _net(), "去重：重复数据删除"),
    ("compressor", "network", _net(), "压缩器：数据压缩"),
    ("decompressor", "network", _net(), "解压器：数据解压"),
    ("packet_parser", "network", _net(), "报文解析器：协议解析"),
    ("packet_builder", "network", _net(), "报文构造器：协议封装"),
]




def main():
    reg = IpRegistry()
    all_ips = ALL_IPS_0 + ALL_IPS_1 + ALL_IPS_2
    added = 0
    for ip in all_ips:
        if len(ip) >= 4:
            reg.register_ip(ip[0], ip[1], ip[2], ip[3])
            added += 1
    reg.close()
    print(f"统一预置完成：{added} 个 IP")
    reg = IpRegistry()
    print("统计:", reg.stats())
    reg.close()


if __name__ == "__main__":
    main()
