# DMA TX Interface Slice

Scope: one AXI4-Stream master output. This example covers only clock/reset validity,
one request with backpressure, and VALID/DATA stability. It does not cover TLAST,
multiple channels, CDC, reordering, or all AXI protocol rules.

Clock: aclk, rising edge. The period is 10000 ps.
Reset: aresetn, active low.
Semantic protocol: valid_ready. Interface group: dma_tx.
VALID = m_axis_tvalid, one bit, using port.protocol=valid_ready.
READY = m_axis_tready, one bit, using port.protocol=valid_ready.
DATA = m_axis_tdata, 32 bits, using port.protocol=valid_ready.
When m_axis_tvalid is high while m_axis_tready is low, m_axis_tvalid and m_axis_tdata must remain stable until the transfer is accepted.
