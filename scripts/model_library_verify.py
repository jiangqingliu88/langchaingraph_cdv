"""黄金模型入库验证 — 定向仿真验证模型语义（matched==N && mismatched==0 才允许入库）。

用法:
    python scripts/model_library_verify.py apb_slave v1

行为:
    1. 探测 EDA（vlog/vsim）；缺失 → 如实报告 EDA_MISSING（exit 2，manifest 保持 verified=false）
    2. 生成自检 TB（写回读回 + 边界），vlog 编译 + vsim 仿真
    3. scoreboard 断言：total==matched && mismatched==0 && total>0
    4. PASS → 更新 manifest.json（sha256 + verified=true + 验证证据）；FAIL → exit 1
"""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
LIB = ROOT / "model_library"

# 各黄金模型的自检 TB（module 名/参数化实例化 + scoreboard 计数）
_TBS = {
    "apb_slave": r"""// 自检 TB：写回读回 + 越界边界
module tb_apb_slave;
    logic clk = 0, rst_n = 0;
    logic [7:0] paddr; logic [7:0] pwdata, prdata;
    logic pwrite, psel, penable;
    int total = 0, matched = 0, mismatched = 0;

    apb_slave_golden #(.NREGS(16), .ADDR_W(8), .DATA_W(8)) dut (.*);

    always #5 clk = ~clk;

    task apb_write(input logic [7:0] a, input logic [7:0] d);
        @(posedge clk); paddr = a; pwdata = d; pwrite = 1; psel = 1; penable = 0;
        @(posedge clk); penable = 1;
        @(posedge clk); psel = 0; penable = 0;
    endtask

    task apb_read(input logic [7:0] a, output logic [7:0] r);
        @(posedge clk); paddr = a; pwrite = 0; psel = 1; penable = 0;
        @(posedge clk); penable = 1;
        @(posedge clk); r = prdata; psel = 0; penable = 0;
    endtask

    task check(input logic [7:0] a, input logic [7:0] exp);
        logic [7:0] got;
        apb_read(a, got);
        total++;
        if (got === exp) matched++; else mismatched++;
    endtask

    initial begin
        repeat (2) @(posedge clk); rst_n = 1;
        // 写读回环
        apb_write(8'h00, 8'hA5); check(8'h00, 8'hA5);
        apb_write(8'h05, 8'h3C); check(8'h05, 8'h3C);
        apb_write(8'h0F, 8'hFF); check(8'h0F, 8'hFF);
        apb_write(8'h00, 8'h00); check(8'h00, 8'h00);
        // 越界读回 0（NREGS=16 → paddr>=16 回 0）
        check(8'h10, 8'h00);
        check(8'hFF, 8'h00);
        // 越界写被忽略：写 paddr=16 后读回应为 0
        apb_write(8'h10, 8'h55); check(8'h10, 8'h00);
        repeat (2) @(posedge clk);
        $display("SCOREBOARD: total=%0d matched=%0d mismatched=%0d", total, matched, mismatched);
        $finish;
    end
endmodule
""",
    "uart_tx": r"""// 自检 TB：8N1 LSB-first 位流逐位比对（BAUD_DIV=4 快速仿真）
module tb_uart_tx;
    localparam BAUD_DIV = 4;
    logic clk = 0, rst_n = 0;
    logic tx_start = 0;
    logic [7:0] tx_data = 0;
    logic tx, tx_busy;
    int total = 0, matched = 0, mismatched = 0;

    uart_tx_golden #(.DATA_BITS(8), .BAUD_DIV(BAUD_DIV)) dut (.*);

    always #5 clk = ~clk;

    task check_bit(input logic exp);
        total++;
        if (dut.tx === exp) matched++; else mismatched++;
    endtask

    initial begin
        repeat (2) @(posedge clk); rst_n = 1;
        @(posedge clk); tx_start = 1; tx_data = 8'b1010_0101;  // 0xA5, LSB first
        @(posedge clk); tx_start = 0;
        repeat (BAUD_DIV / 2) @(posedge clk);
        check_bit(1'b0);                      // start = 0
        for (int i = 0; i < 8; i++) begin
            repeat (BAUD_DIV) @(posedge clk);
            check_bit(tx_data[i]);            // 数据位 LSB first
        end
        repeat (BAUD_DIV) @(posedge clk);
        check_bit(1'b1);                      // stop = 1
        repeat (2) @(posedge clk);
        check_bit(1'b1);                      // idle 保持 1
        repeat (2) @(posedge clk);
        $display("SCOREBOARD: total=%0d matched=%0d mismatched=%0d", total, matched, mismatched);
        $finish;
    end
endmodule
""",
    "uart_rx": r"""// 自检 TB：驱动位流 → 验证 rx_data 恢复 + rx_valid（BAUD_DIV=4 快速仿真）
module tb_uart_rx;
    localparam BAUD_DIV = 4;
    logic clk = 0, rst_n = 0;
    logic rx = 1;
    logic [7:0] rx_data;
    logic rx_valid;
    int total = 0, matched = 0, mismatched = 0;

    uart_rx_golden #(.DATA_BITS(8), .BAUD_DIV(BAUD_DIV)) dut (.*);

    always #5 clk = ~clk;

    task drive_bit(input logic v);
        repeat (BAUD_DIV) @(posedge clk);
        rx = v;
    endtask

    initial begin
        repeat (2) @(posedge clk); rst_n = 1;
        repeat (2) @(posedge clk);
        // 第一帧 0xA5：start(0) + LSB-first 数据 + stop(1)
        drive_bit(1'b0);
        for (int i = 0; i < 8; i++) drive_bit(8'b1010_0101[i]);
        drive_bit(1'b1);
        repeat (20) @(posedge clk);
        total++;
        if (dut.rx_data === 8'b1010_0101 && dut.rx_valid) matched++; else mismatched++;
        // 第二帧 0x3C
        repeat (4) @(posedge clk);
        drive_bit(1'b0);
        for (int i = 0; i < 8; i++) drive_bit(8'b0011_1100[i]);
        drive_bit(1'b1);
        repeat (20) @(posedge clk);
        total++;
        if (dut.rx_data === 8'b0011_1100 && dut.rx_valid) matched++; else mismatched++;
        $display("SCOREBOARD: total=%0d matched=%0d mismatched=%0d", total, matched, mismatched);
        $finish;
    end
endmodule
""",
    "fifo16": r"""// 自检 TB：先入先出顺序 + 满/空/overflow 标志
module tb_fifo16;
    logic clk = 0, rst_n = 0;
    logic wr_en = 0, rd_en = 0;
    logic [7:0] wdata = 0, rdata;
    logic full, empty, overflow;
    int total = 0, matched = 0, mismatched = 0;

    fifo16_golden #(.DEPTH(16), .DATA_W(8)) dut (.*);

    always #5 clk = ~clk;

    task push(input logic [7:0] d);
        @(posedge clk); wr_en = 1; wdata = d;
        @(posedge clk); wr_en = 0;
    endtask

    task pop(output logic [7:0] d);
        @(posedge clk); rd_en = 1;
        @(posedge clk); d = dut.rdata; rd_en = 0;
    endtask

    task check(input string what, input logic cond);
        total++;
        if (cond) matched++; else mismatched++;
    endtask

    initial begin
        logic [7:0] d;
        repeat (2) @(posedge clk); rst_n = 1;
        // 1. 空标志
        check("empty_initial", dut.empty === 1);
        // 2. 推 3 弹 3，顺序一致
        push(8'h11); push(8'h22); push(8'h33);
        pop(d); check("fifo_order_1", d === 8'h11);
        pop(d); check("fifo_order_2", d === 8'h22);
        pop(d); check("fifo_order_3", d === 8'h33);
        check("empty_after_pop", dut.empty === 1);
        // 3. 推满 16 → full
        for (int i = 0; i < 16; i++) push(8'(i));
        check("full_flag", dut.full === 1);
        // 4. 满时再写 → overflow 脉冲
        @(posedge clk); wr_en = 1; wdata = 8'hFF;
        @(posedge clk); wr_en = 0;
        check("overflow_pulse", dut.overflow === 1);
        // 5. 弹空 → empty
        for (int i = 0; i < 16; i++) begin
            @(posedge clk); rd_en = 1;
            @(posedge clk); rd_en = 0;
        end
        check("empty_after_drain", dut.empty === 1);
        repeat (2) @(posedge clk);
        $display("SCOREBOARD: total=%0d matched=%0d mismatched=%0d", total, matched, mismatched);
        $finish;
    end
endmodule
""",
    "irq_gen": r"""// 自检 TB：源置位 + 使能门控 + 清除
module tb_irq_gen;
    logic clk = 0, rst_n = 0;
    logic [3:0] irq_src = 0, irq_en = 0;
    logic irq_clear = 0;
    logic irq;
    logic [3:0] irq_pending;
    int total = 0, matched = 0, mismatched = 0;

    irq_gen_golden #(.N_SRC(4)) dut (.*);

    always #5 clk = ~clk;

    task check(string what, input logic cond);
        total++;
        if (cond) matched++; else mismatched++;
    endtask

    initial begin
        repeat (2) @(posedge clk); rst_n = 1;
        repeat (2) @(posedge clk);
        // 1. 未使能时源事件不产生 irq（pending 仍记录）
        irq_src = 4'b0001; irq_en = 4'b0000;
        @(posedge clk); irq_src = 0;
        check("pending_set", dut.irq_pending[0] === 1'b1);
        check("irq_gated_off", dut.irq === 1'b0);
        // 2. 使能后 irq 拉高
        irq_en = 4'b0001;
        @(posedge clk);
        check("irq_on_when_enabled", dut.irq === 1'b1);
        // 3. 清除 → pending 清零、irq 拉低
        irq_clear = 1;
        @(posedge clk); irq_clear = 0;
        check("irq_after_clear", dut.irq === 1'b0);
        check("pending_after_clear", dut.irq_pending === 4'b0000);
        // 4. 第二源
        irq_src = 4'b0010; irq_en = 4'b0010;
        @(posedge clk); irq_src = 0;
        check("src1_irq", dut.irq === 1'b1);
        check("src1_pending", dut.irq_pending[1] === 1'b1);
        repeat (2) @(posedge clk);
        $display("SCOREBOARD: total=%0d matched=%0d mismatched=%0d", total, matched, mismatched);
        $finish;
    end
endmodule
""",
}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    ip, version = sys.argv[1], sys.argv[2]
    model_path = LIB / ip / version / "model.sv"
    manifest_path = LIB / ip / version / "manifest.json"
    if not model_path.exists():
        print(f"[FAIL] 模型不存在: {model_path}")
        return 1
    if ip not in _TBS:
        print(f"[FAIL] 未定义 {ip} 的自检 TB（先在 scripts/model_library_verify.py 的 _TBS 添加）")
        return 1

    # ── EDA 可用性（失败响亮：无 EDA 不假装验证通过）──
    if not (shutil.which("vlog") and shutil.which("vsim")):
        print(f"[EDA_MISSING] 未检测到 vlog/vsim，无法验证 {ip} {version}。"
              f"请安装 QuestaSim 并加入 PATH 后重跑（manifest 保持 verified=false）。")
        return 2

    # ── 生成自检工程并仿真 ──
    with tempfile.TemporaryDirectory(prefix="golden_verify_") as tmp:
        td = Path(tmp)
        (td / f"{ip}.sv").write_text(model_path.read_text(encoding="utf-8"), encoding="utf-8")
        tb_name = f"tb_{ip}"
        (td / f"{tb_name}.sv").write_text(_TBS[ip], encoding="utf-8")
        # **路径一律 `.as_posix()`**：Questa 的参数解析把反斜杠当转义，`-work`
        # 收到 Windows 路径时会把库路径和后面的顶层模块名粘成一个参数 ——
        # 实测报 `(vopt-2253) No module name found in command-line argument
        # "...\work.tb_apb_slave"`，于是五个黄金模型一个都验不过（全卡在
        # `verified=false`，`model_real` 门谁都过不了）。
        # 仓库里能跑通的几处（`filelist.py`、`tool_check_env_arch`）本来就是
        # 全程 `.as_posix()`，这里跟上。
        (td / "filelist.f").write_text(
            f"{(td / (ip + '.sv')).as_posix()}\n"
            f"{(td / (tb_name + '.sv')).as_posix()}\n", encoding="utf-8")

        work = td / "work"
        work.mkdir()
        r = subprocess.run(
            ["vlog", "-work", work.as_posix(), "-sv", "-f", (td / "filelist.f").as_posix()],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(td), timeout=180)
        if r.returncode != 0:
            print(f"[FAIL] 编译失败:\n{r.stdout[-800:]}{r.stderr[-800:]}")
            return 1

        r = subprocess.run(
            ["vsim", "-c", "-work", work.as_posix(), tb_name, "-do", "run -all; quit -f"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(td), timeout=180)
        out = r.stdout + r.stderr
        import re
        m = re.search(r"SCOREBOARD:\s*total=(\d+)\s*matched=(\d+)\s*mismatched=(\d+)", out)
        if not m:
            print(f"[FAIL] 未找到 scoreboard 结果（仿真可能崩溃）:\n{out[-800:]}")
            return 1
        total, matched, mismatched = int(m.group(1)), int(m.group(2)), int(m.group(3))
        passed = total > 0 and matched == total and mismatched == 0
        # 版本号本身就带 `v`（清单里是 `v1`），别再拼一个 —— 原来打出来是 `vv1`
        print(f"[{'PASS' if passed else 'FAIL'}] {ip} {version}: "
              f"total={total} matched={matched} mismatched={mismatched}")

        if not passed:
            return 1

    # ── PASS → 更新 manifest（sha256 + verified + 证据）──
    sha = hashlib.sha256(model_path.read_bytes()).hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest.update({
        "ip": ip, "version": version,
        "sha256": sha, "verified": True,
        "verified_by": {"test": f"tb_{ip}", "scoreboard": {"total": total, "matched": matched,
                                                           "mismatched": mismatched}},
    })
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[PASS] manifest 已更新: {manifest_path} (sha256={sha[:12]}...)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
