// 故意的故障对照 RTL：保持 valid，却在背压期间改变 data。
// 它用于证明 monitor 能发现确定的协议违例，不是“让测试变绿”的备选模型。
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
        end else if (m_axis_tvalid && !m_axis_tready) begin
            m_axis_tdata <= m_axis_tdata + 32'd1;
        end else if (req_valid && !m_axis_tvalid) begin
            m_axis_tvalid <= 1'b1;
            m_axis_tdata <= req_data;
        end else if (m_axis_tvalid && m_axis_tready) begin
            m_axis_tvalid <= 1'b0;
        end
    end
endmodule
