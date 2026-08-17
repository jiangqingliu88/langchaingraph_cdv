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
        (td / "filelist.f").write_text(
            f"{td / (ip + '.sv')}\n{td / (tb_name + '.sv')}\n", encoding="utf-8")

        work = td / "work"
        work.mkdir()
        r = subprocess.run(
            ["vlog", "-work", str(work), "-sv", "-f", str(td / "filelist.f")],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(td), timeout=180)
        if r.returncode != 0:
            print(f"[FAIL] 编译失败:\n{r.stdout[-800:]}{r.stderr[-800:]}")
            return 1

        r = subprocess.run(
            ["vsim", "-c", "-work", str(work), tb_name, "-do", "run -all; quit -f"],
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
        print(f"[{'PASS' if passed else 'FAIL'}] {ip} v{version}: "
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
