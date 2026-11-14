// Generated from TIM-1656bf13a392dab3c885269c. Only declared identifiers are injected.
module monitor_r_valid_data_stable (
    input wire aclk, input wire aresetn,
    input wire m_axis_tvalid, input wire m_axis_tready,
    input wire [31:0] m_axis_tdata,

    output reg [31:0] violations,
    output reg [31:0] handshakes,
    output reg [31:0] blocked_samples,
    output reg [31:0] unknown_samples
);
    reg prev_valid, prev_ready;
    reg [31:0] prev_0;

    initial begin
        violations = 0; handshakes = 0; blocked_samples = 0;
        unknown_samples = 0; prev_valid = 0; prev_ready = 0;
    end

    always @(posedge aclk) begin
        if (aresetn === 1'b0) begin
            violations <= 0; handshakes <= 0; blocked_samples <= 0;
            unknown_samples <= 0; prev_valid <= 0; prev_ready <= 0;
        end else begin
            // 上一周期 VALID=1/READY=0 时，本周期仍要保持声明信号稳定。
            if (prev_valid && !prev_ready && ((m_axis_tvalid !== prev_valid) || ((m_axis_tdata !== prev_0)))) begin
                $display("TIMING_VIOLATION rule=R-VALID-DATA-STABLE cycle=%0t payload_changed_or_valid_dropped", $time);
                violations <= violations + 1;
            end
            if ((m_axis_tvalid !== 1'b0 && m_axis_tvalid !== 1'b1) || (m_axis_tvalid === 1'b1 && (m_axis_tready !== 1'b0 && m_axis_tready !== 1'b1))) begin
                unknown_samples <= unknown_samples + 1;
            end
            if (m_axis_tvalid === 1'b1 && ((^m_axis_tdata === 1'bx)))
                unknown_samples <= unknown_samples + 1;
            if (m_axis_tvalid === 1'b1 && m_axis_tready === 1'b1)
                handshakes <= handshakes + 1;
            if (m_axis_tvalid === 1'b1 && m_axis_tready === 1'b0)
                blocked_samples <= blocked_samples + 1;
            prev_valid <= m_axis_tvalid; prev_ready <= m_axis_tready;
        prev_0 <= m_axis_tdata;
        end
    end
endmodule
