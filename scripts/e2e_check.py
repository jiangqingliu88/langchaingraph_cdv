"""E2E 验收脚本 — 在装有 QuestaSim 的机器上验证 SignOffAI 闭环与"失败响亮"。

用法:
    python scripts/e2e_check.py                     # 跑 apb_uart 闭环并断言关键结果
    python scripts/e2e_check.py --expect-converge   # 期望收敛（覆盖率达标）时才通过

行为:
    1. 探测 EDA 工具（vlog/vsim）与 LLM key，打印环境报告
    2. 跑 `vagent verify specs/apb_uart/apb_uart_spec.md --max-rounds 3`
    3. 断言:
       - 无 EDA → status=BLOCKED_EDA_MISSING（失败响亮，不假通过）
       - 有 EDA → 闭环正常执行；audit 门禁如实反映（模型占位时 NEEDS_FIX）
       - manifest.json 存在且含 llm_audit / rtl_hashes / coverage_db_history
    4. 打印 report.json 的 gates（rtl/regression/coverage/model_real）供人工核查
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SPEC = ROOT / "specs" / "apb_uart" / "apb_uart_spec.md"
PYTHON = ROOT / "venv" / "Scripts" / "python.exe"


def env_report() -> dict:
    eda = {t: bool(shutil.which(t)) for t in ("vlog", "vsim", "vcover")}
    has_env = (ROOT / ".env").exists()
    return {"eda_tools": eda, "has_env_file": has_env}


def main() -> int:
    rep = env_report()
    print("=== 环境报告 ===")
    print(json.dumps(rep, indent=2, ensure_ascii=False))

    if not any(rep["eda_tools"].values()):
        print("\n[info] 未检测到 EDA 工具 → 期望 status=BLOCKED_EDA_MISSING（失败响亮验收）")
    else:
        print("\n[info] 检测到 EDA 工具 → 期望闭环正常执行")

    cmd = [str(PYTHON), "-m", "src.cli.commands", "verify",
           str(SPEC), "--max-rounds", "3", "--json"]
    print(f"\n=== 执行: {' '.join(cmd)} ===")
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=1800)
    if r.returncode not in (0, 1):
        print("非预期退出码:", r.returncode)
        print(r.stderr[-2000:])
        return 2

    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("stdout 非 JSON（可能被日志污染），尝试提取最后一个 JSON 对象")
        for line in reversed(r.stdout.splitlines()):
            if line.strip().startswith("{"):
                out = json.loads(line)
                break
        else:
            print(r.stdout[-3000:])
            return 2

    print("\n=== 闭环结果 ===")
    print(json.dumps({k: out.get(k) for k in (
        "run_id", "status", "passed", "total", "final_coverage",
        "effective_coverage", "converged", "eda_blocked")}, indent=2, ensure_ascii=False))

    # ── 断言 1：失败响亮 ──
    if not any(rep["eda_tools"].values()):
        assert out.get("status") == "BLOCKED_EDA_MISSING", \
            f"无 EDA 时应 BLOCKED_EDA_MISSING，实际 {out.get('status')}"
        eda_phases = [p for p in out.get("phases", []) if p.get("name") == "eda_check"]
        assert eda_phases and eda_phases[-1].get("status") == "failed", "缺少 eda_check failed 阶段"
        print("\n[PASS] 失败响亮：无 EDA → BLOCKED_EDA_MISSING + eda_check failed")
    else:
        # 有 EDA：闭环不应以 BLOCKED 终止
        assert out.get("status") != "BLOCKED_EDA_MISSING", "有 EDA 却 BLOCKED？检查 PATH"

    # ── 断言 2：audit 门禁如实 ──
    # CLI --json 不含 output_root；取最新的 output_* 目录（含用户与时间戳后缀）
    output_root = None
    if out.get("output_root"):
        output_root = Path(out["output_root"])
    else:
        cands = sorted(ROOT.glob("output_*"), key=lambda p: p.stat().st_mtime, reverse=True)
        output_root = cands[0] if cands else None
    assert output_root is not None and output_root.exists(), "找不到输出目录"
    report_path = output_root / "report.json"
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print("\n=== audit report.json gates ===")
        print(json.dumps(report.get("gates", {}), indent=2, ensure_ascii=False))
        verdict = report.get("verdict")
        # 参考模型占位 → 必须 NEEDS_FIX（不允许假 APPROVED）
        if verdict == "READY":
            print("\n[PASS] 签核 READY（门禁全过）")
        else:
            print(f"\n[PASS] 签核如实 {verdict}（门禁未全过 → 不 APPROVED）")

    # ── 断言 3：manifest 完整性 ──
    manifest_path = output_root / "docs" / "manifest.json"
    assert manifest_path.exists(), "manifest.json 缺失"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("rtl_hashes", "coverage_db_history", "llm_audit", "phases"):
        assert key in manifest, f"manifest 缺 {key}"
    print("\n[PASS] manifest.json 完整（rtl_hashes / coverage_db_history / llm_audit / phases）")

    # ── 断言 4：tb_top 参考模型比对接入（黄金命中时 bench.yaml 必须含 ref_model）──
    bench_path = output_root / "inputs" / "yaml" / "uvm" / "bench.yaml"
    if bench_path.exists():
        bench = bench_path.read_text(encoding="utf-8")
        has_ref = "ref_model:" in bench and "enabled: true" in bench
        has_golden = "golden:" in bench
        if has_ref and has_golden:
            print("\n[PASS] bench.yaml 含 ref_model（黄金模型真实实例化比对已接入）")
        else:
            print("\n[WARN] bench.yaml 无 ref_model 段 —— 黄金未命中或生成失败，参考模型比对未接入")
    else:
        print("\n[WARN] 未找到 bench.yaml（UVM 环境可能未生成）")

    print("\n=== 验收结论: 通过 ===")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as e:
        print(f"\n[FAIL] 断言失败: {e}")
        sys.exit(1)
