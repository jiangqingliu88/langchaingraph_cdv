"""EDA 机器一键验收脚本 — 黄金模型盖章 + 真实闭环 + manifest 完整性。

在装有 QuestaSim 的机器上运行（本机无 EDA 时每一步都会如实报 EDA_MISSING）：

    python scripts/eda_verify_all.py

流程:
    1. 环境报告（vlog/vsim/vcover + .env）
    2. 黄金模型入库验证（5 个：apb_slave/uart_tx/uart_rx/fifo16/irq_gen）
       - PASS → manifest verified=true（盖章）+ model_library_import.py 更新索引
       - FAIL → 该模型不入库（禁止未验证模型）
       - EDA_MISSING → 跳过盖章，报告待办
    3. 真实闭环 e2e_check.py（规格→RTL→UVM→回归→覆盖率→签核 + 失败响亮断言）
    4. 汇总报告（exit 0=全部 PASS；1=有 FAIL；2=EDA 缺失导致部分未执行）
"""
import subprocess
import sys
from pathlib import Path

# UTF-8 强制（Windows 控制台 GBK 无法打印 subprocess 里的替换字符）
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"

GOLDEN_IPS = ["apb_slave", "uart_tx", "uart_rx", "fifo16", "irq_gen"]


def run(cmd, timeout=1800):
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)


def main() -> int:
    print("=" * 60)
    print("SignOffAI EDA 一键验收")
    print("=" * 60)

    # ── 1. 环境报告 ──
    import shutil
    eda = {t: bool(shutil.which(t)) for t in ("vlog", "vsim")}
    print(f"\n[env] vlog={eda['vlog']} vsim={eda['vsim']} "
          f".env={ (ROOT / '.env').exists() }")
    if not (eda["vlog"] and eda["vsim"]):
        print("[env] 未检测到 QuestaSim —— 后续步骤将如实报 EDA_MISSING，不会假通过")

    # ── 2. 黄金模型入库验证 ──
    print("\n" + "=" * 60)
    print("2. 黄金模型入库验证")
    print("=" * 60)
    results = {}
    for ip in GOLDEN_IPS:
        print(f"\n--- {ip} v1 ---")
        rc, out = run([str(PYTHON), "scripts/model_library_verify.py", ip, "v1"])
        print(out.strip()[-600:])
        if rc == 0:
            # 盖章成功 → 入索引
            rc2, out2 = run([str(PYTHON), "scripts/model_library_import.py", ip, "v1"])
            print(out2.strip()[-300:])
            results[ip] = "VERIFIED"
        elif rc == 2:
            results[ip] = "EDA_MISSING"
        else:
            results[ip] = "FAIL"
            print(f"[{ip}] 验证 FAIL —— 该模型禁止入索引（入库必须验证）")

    # ── 3. 真实闭环（两个规格：apb_uart 基础 + apb_uart_regs 复合参考模型路径）──
    print("\n" + "=" * 60)
    print("3. 真实 EDA 闭环验收")
    print("=" * 60)
    e2e_status = "PASS"
    for spec_rel in ("specs/apb_uart/apb_uart_spec.md",
                     "specs/apb_uart_regs/apb_uart_regs_spec.md"):
        print(f"\n--- e2e: {spec_rel} ---")
        rc, out = run([str(PYTHON), "scripts/e2e_check.py", spec_rel])
        print(out.strip()[-900:])
        st = "PASS" if rc == 0 else ("FAIL" if rc == 1 else "EDA_MISSING")
        e2e_status = st if e2e_status == "PASS" else e2e_status
        if st == "FAIL":
            e2e_status = "FAIL"

    # ── 4. 汇总 ──
    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    for ip, st in results.items():
        print(f"  {ip:12s} {st}")
    print(f"  e2e_check    {e2e_status}")
    n_missing = sum(1 for s in results.values() if s == "EDA_MISSING")
    n_fail = sum(1 for s in results.values() if s == "FAIL")
    print(f"\n结论: 盖章 {5 - n_missing - n_fail}/5, 失败 {n_fail}, EDA 缺失 {n_missing}, 闭环 {e2e_status}")
    if n_fail > 0 or e2e_status == "FAIL":
        print("有 FAIL —— 请按上方详细输出排查（黄金模型语义或闭环路径问题）")
        return 1
    if n_missing > 0 or e2e_status == "EDA_MISSING":
        print("EDA 缺失 —— 安装 QuestaSim 并加入 PATH 后重跑（未盖章/未闭环不构成假通过）")
        return 2
    print("全部 PASS —— 黄金模型已盖章，闭环验收通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
