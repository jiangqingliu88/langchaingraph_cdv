"""默认参考模型 —— **DUT 级**的 TLM 1.0 事务级模型，种进 `model_registry.db`。

## 建的是谁：**DUT 级，不是子模块级**

参考模型建模的是 **DUT 的事务级行为** —— 从它的**总线/接口**进去，看应该得到什么。
DUT 内部的子模块（FIFO、中断发生器、UART 收发）**不单独建模**：它们没有自己的
事务接口，把它们摆进库里等于把"实现"当"规格"。

## 这 5 个从哪来的、为什么现在只剩 1 个

原 `model_library/` 里有 5 个（`apb_slave` / `fifo16` / `irq_gen` /
`uart_tx` / `uart_rx`，**已删除**，语义可从
`git show HEAD:model_library/<ip>/v1/model.sv` 抬头捞回）。它们全是**信号级 RTL**：

    module uart_tx_golden #(DATA_BITS, BAUD_DIV) (
        input logic clk, rst_n, tx_start, ...   // 引脚级
    );  always_ff @(posedge clk) ...            // 带时钟的时序逻辑

两处都不对：**抽象层错**（信号级 ≠ 参考模型），**颗粒度也错**（`uart_tx` /
`uart_rx` / `fifo16` / `irq_gen` 是 DUT 的内部件）。所以只留 DUT 级的那个。

## ⚠️ 事务级比对不覆盖周期级指标

spec 里这两条 ——

    UART 发送：9600-115200 波特率下误差 ≤ 2%
    中断输出：中断延迟 ≤ 2 个时钟周期

—— 是**时序属性**，DUT 级事务模型给不出，要靠断言 / 波形另验。
**别把回归里的 PASS 读成这两条也过了。**
（原先给 uart_tx / irq_gen 建信号级模型，图的正是这两条；现在不建子模块模型，
这两条就**只剩断言/波形这一条路**，不能再指望参考模型兜着。）
"""
from __future__ import annotations

from typing import Any, Dict, List

#: 每个模型：语义 + 事务级 body + 参数
#: `body` 会渲染进 `util_comp.sv.j2` 的 `process_<port>`（见该模板的 `body` 分支）
DEFAULT_MODELS: List[Dict[str, Any]] = [
    {
        # 模型是**这个 DUT** 的，不是某个协议的通用镜像。
        # 名字 = DUT 名；语义 = 它两侧接口之间的事务映射。
        "name": "apb_uart",
        "protocol": "apb",
        # APB 侧进来一条事务 → UART 侧应该出现什么。跨接口，这才是 DUT 级。
        "trans_in": "apb_master_seq_item", "trans_out": "uart_master_seq_item",
        "semantics": "APB 写 -> TX FIFO -> 按序从 tx 串出（满则丢弃）；"
                     "rx 收到的字节直通为 APB 读数据；paddr 不参与译码",
        # ⚠️ 这份语义是**照着 RTL 的数据通路**写的，不是"常规 UART"的想当然：
        #   `rtl/apb_uart.sv` 里 ——
        #     请求  fifo_wr_en = psel&penable&pwrite&~fifo_full; wr_data = pwdata
        #           → async_fifo → tx_data = fifo_rd_data, tx_valid = ~fifo_empty
        #           → uart_tx → tx          （FIFO 型：**按序**、**可满**）
        #     响应  rx → uart_rx → rx_data → `assign prdata = rx_data`
        #                                       （**直通**，不经 FIFO/寄存器）
        #     地址  paddr **不参与任何判断** —— 没有译码、没有寄存器文件
        #     中断  irq_in = {31'b0, rx_valid}, irq_en = 32'h0000_0001  ← 硬编码
        # 改这条通路时，这里必须跟着改 —— 否则模型验的就不是这个 DUT。
        "body": """    // 请求侧（TX）：APB 写 -> TX FIFO -> 按序串出。**有排队语义**。
    //   注意 `fifo_wr_en` 带 `~fifo_full`：**满时写入被丢弃**，模型要照做。
    if (tr.pwrite) begin
      if (tx_q.size() < DEPTH) tx_q.push_back(tr.pwdata);
      // 满了就丢 —— 这是 RTL 的行为，不是"我们没实现"
    end else begin
      // 响应侧（RX）：rx 收到的字节**直通** prdata。
      //   **不排队**（RTL 里是 `assign prdata = rx_data`），
      //   **不看 paddr**（地址不参与译码）。
      tr.prdata = last_rx;
    end""",
    },
]


def seed(registry, *, status: str = "draft") -> int:
    """把 `DEFAULT_MODELS` 种进库；**已存在的 name 不覆盖**（升版本要走 `register`）。

    返回新登记的条数。幂等：重复调用不会重复登记。
    """
    n = 0
    for m in DEFAULT_MODELS:
        if registry.latest_version(m["name"]) is not None:
            continue
        registry.register(m["name"], protocol=m["protocol"],
                          trans_in=m["trans_in"], trans_out=m["trans_out"],
                          semantics=m["semantics"], body=m["body"],
                          status=status)
        n += 1
    return n


#: 曾经的子模块模型 —— **明确作废**，别再建回来。
#: 留着这个名字是为了让"为什么没有它们"有一个可搜索的落点：
#: 建模建的是 DUT 的事务级行为，子模块没有自己的事务接口。
RETIRED_SUBMODULE_MODELS = ("fifo16", "irq_gen", "uart_tx", "uart_rx")
