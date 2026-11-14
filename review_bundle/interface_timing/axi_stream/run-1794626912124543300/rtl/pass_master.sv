// 合规对照 RTL：在等待握手时保持 valid 与 data。
// 只用于验证 monitor 和证据链，不代表完整 DUT 的所有功能已验证。
module stream_master_model (
    input wire aclk,
    input wire aresetn,
    input wire m_axis_tready,
    input wire req_valid,
    input wire [31:0] req_data,
    output reg m_axis_tvalid,
    output reg [31:0] m_axis_tdata
);
    always @(posedge aclk) begin
        if (!aresetn) begin
            m_axis_tvalid <= 1'b0;
            m_axis_tdata <= 32'b0;
        end else if (req_valid && !m_axis_tvalid) begin
            m_axis_tvalid <= 1'b1;
            m_axis_tdata <= req_data;
        end else if (m_axis_tvalid && m_axis_tready) begin
            m_axis_tvalid <= 1'b0;
        end
    end
endmodule
