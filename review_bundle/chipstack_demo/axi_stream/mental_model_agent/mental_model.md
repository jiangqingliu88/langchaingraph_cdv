# dma_tx_stream — bounded mental model

这是从确认的结构化语义生成的共享理解，不是 LLM 已理解全部设计的声明。
Binding: `VALIDATED`
Specification: `VALIDATED`

- Protocol: `axi4_stream`
- Interface group: `dma_tx`
- Status: `CONFIRMED`
- Input mode: `structured_authoring`
- Clock: `aclk`, period_ps=`10000`

## Signal bindings
- `VALID` → `m_axis_tvalid` (width=1, CONFIRMED)
- `READY` → `m_axis_tready` (width=1, CONFIRMED)
- `DATA` → `m_axis_tdata` (width=32, CONFIRMED)

## Rules and provenance
- `R-VALID-DATA-STABLE`: valid_ready_stable
  - valid=`m_axis_tvalid`, ready=`m_axis_tready`
  - stable_signals=['m_axis_tvalid', 'm_axis_tdata']
  - source=`source/spec.md`:13-13
  - quote: When m_axis_tvalid is high while m_axis_tready is low, m_axis_tvalid and m_axis_tdata must remain stable until the transfer is accepted.

## Explicit unknowns

超出这个接口与规则子集的内容没有被推断为已证明。
