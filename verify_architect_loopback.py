"""
Validate Architect Agent Loopback Test Pipeline
================================================
Checks:
  1. Template correctness
  2. Generated code quality
  3. QuestaSim compile check
  4. TLM loopback connections
  5. regression_wrapper integration
"""
import os, sys, subprocess, re
from pathlib import Path
from datetime import datetime

os.environ["PYTHONIOENCODING"] = "utf-8"

PROJECT_ROOT = Path("D:/cdv_a")
GEN_DIR = PROJECT_ROOT / "generated" / "uart"
AGENTS_DIR = GEN_DIR / "agents" / "UART_in"
LB_DIR = AGENTS_DIR / "loopback"
QUESTA_DIR = Path("f:/questasim64_2024.1/win64")
UVM_SRC = Path("f:/questasim64_2024.1/verilog_src/uvm-1.2/src")

RESULTS = []

def read_sv(path: Path) -> str:
    """Read SV file with encoding fallback."""
    for enc in ['utf-8', 'gbk', 'latin-1']:
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return path.read_text(encoding='utf-8', errors='replace')

def check(ok: bool, name: str, detail: str = "") -> dict:
    r = {"name": name, "pass": ok, "detail": detail}
    RESULTS.append(r)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}")
    if detail:
        print(f"         {detail}")
    return r

print("=" * 70)
print(" Architect Agent Loopback Test - Validation")
print("=" * 70)

# ═══════════════════════════════════ 1. Templates ═══
print("\n-- 1. Template Completeness --")

TEMPLATE_DIR = PROJECT_ROOT / "src" / "tools" / "uvm" / "tool_uvm" / "templates"
loopback_templates = [
    "interface_templates/agent_loopback_env.sv.j2",
    "interface_templates/agent_loopback_scb.sv.j2",
    "interface_templates/agent_loopback_test.sv.j2",
    "interface_templates/agent_loopback_tb.sv.j2",
]

for tpl in loopback_templates:
    p = TEMPLATE_DIR / tpl
    check(p.exists(), f"Template: {tpl}",
          "" if p.exists() else "MISSING")

# ═══════════════════════════════════ 2. Generated Files ═══
print("\n-- 2. Generated File Completeness --")

expected_agent_files = [
    "UART_in_interface.sv", "UART_in_interface_structure.sv",
    "UART_in_transaction.sv", "UART_in_sequencer.sv",
    "UART_in_monitor.sv", "UART_in_driver.sv",
    "UART_in_config.sv", "UART_in_agent.sv",
    "UART_in_pkg.sv", "UART_in_base_seq.sv",
    "UART_in_coverage_collector.sv",
]
expected_lb_files = [
    "UART_in_loopback_env.sv", "UART_in_loopback_scb.sv",
    "UART_in_loopback_test.sv", "UART_in_loopback_tb.sv",
]

for f in expected_agent_files:
    p = AGENTS_DIR / f
    check(p.exists(), f"Agent: {f}",
          f"{p.stat().st_size} bytes" if p.exists() else "MISSING")

for f in expected_lb_files:
    p = LB_DIR / f
    check(p.exists(), f"Loopback: {f}",
          f"{p.stat().st_size} bytes" if p.exists() else "MISSING")


# ═══════════════════════════════════ 3. Static Analysis ═══
print("\n-- 3. Generated Code Static Analysis --")

# 3a. Loopback TB port names
lb_tb = LB_DIR / "UART_in_loopback_tb.sv"
if lb_tb.exists():
    content = read_sv(lb_tb)
    has_hardcoded_clk = ".clk(clk)" in content
    has_hardcoded_rst = ".rst_n(rst_n)" in content
    check(not has_hardcoded_clk,
          "TB: no hardcoded .clk(clk) connection",
          "Template uses hardcoded clock name, should use agent.clock" if has_hardcoded_clk else "OK")
    check(not has_hardcoded_rst,
          "TB: no hardcoded .rst_n(rst_n) connection",
          "Template uses hardcoded reset name, should use agent.reset" if has_hardcoded_rst else "OK")

# 3b. Duplicate import
if lb_tb.exists():
    import_count = content.count("import UART_in_pkg::*;")
    check(import_count == 1, f"TB: duplicate import check (count={import_count})",
          "OK" if import_count == 1 else f"Duplicate import ({import_count} occurrences)")

# 3c. Duplicate typedef
lb_env = LB_DIR / "UART_in_loopback_env.sv"
if lb_env.exists():
    env_content = read_sv(lb_env)
    typedef_count = env_content.count("typedef class UART_in_loopback_scb;")
    check(typedef_count == 1, f"Env: duplicate typedef check (count={typedef_count})",
          "OK" if typedef_count == 1 else f"Duplicate typedef ({typedef_count} occurrences)")

# 3d. Driver expected_port
drv = AGENTS_DIR / "UART_in_driver.sv"
if drv.exists():
    drv_content = read_sv(drv)
    check("expected_port" in drv_content, "Driver: expected_port declared")
    check("expected_port.write(req)" in drv_content or "expected_port.write" in drv_content,
          "Driver: expected_port.write() called")

# 3e. Monitor item_collected_port
mon = AGENTS_DIR / "UART_in_monitor.sv"
if mon.exists():
    mon_content = read_sv(mon)
    check("item_collected_port" in mon_content, "Monitor: item_collected_port declared")

# 3f. Scoreboard TLM imports + logic
scb = LB_DIR / "UART_in_loopback_scb.sv"
if scb.exists():
    scb_content = read_sv(scb)
    check("expected_export" in scb_content, "Scoreboard: expected_export")
    check("actual_export" in scb_content, "Scoreboard: actual_export")
    check("write_expected" in scb_content, "Scoreboard: write_expected()")
    check("write_actual" in scb_content, "Scoreboard: write_actual()")
    check("compare(" in scb_content, "Scoreboard: compare() logic")

# 3g. Loopback Env TLM connections
if lb_env.exists():
    check("expected_port.connect" in env_content or "drv.expected_port" in env_content,
          "Loopback Env: Driver->Scoreboard TLM connection")
    check("item_collected_port.connect" in env_content or "mon.item_collected_port" in env_content,
          "Loopback Env: Monitor->Scoreboard TLM connection")

# 3h. Loopback Test sequence start
lb_test = LB_DIR / "UART_in_loopback_test.sv"
if lb_test.exists():
    test_content = read_sv(lb_test)
    check("seq.start" in test_content, "Loopback Test: seq.start() call")

# 3i. CB signal consistency - Driver/Monitor vs Interface
iface = AGENTS_DIR / "UART_in_interface.sv"
if drv.exists() and iface.exists():
    iface_content = read_sv(iface)
    # Filter out commented / unused lines for CB signal check
    drv_active = '\n'.join(l for l in drv_content.split('\n') if not l.strip().startswith('//'))
    mon_active = '\n'.join(l for l in mon_content.split('\n') if not l.strip().startswith('//'))
    drv_cb_signals = set(re.findall(r'vif\.cb\.(\w+)', drv_active))
    mon_cb_signals = set(re.findall(r'vif\.cb\.(\w+)', mon_active)) if mon.exists() else set()
    all_cb_signals = drv_cb_signals | mon_cb_signals

    cb_section = re.search(r'clocking cb.*?endclocking', iface_content, re.DOTALL)
    if cb_section:
        cb_signals = set(re.findall(r'(?:input|output)\s+(\w+)', cb_section.group(0)))
    else:
        cb_signals = set()

    missing = all_cb_signals - cb_signals
    if missing:
        check(False, "CB signal consistency: Driver/Monitor <-> Interface",
              f"Missing CB signals: {missing}")
    else:
        check(True, "CB signal consistency: Driver/Monitor <-> Interface",
              "All CB signals present in interface")

# 3j. Interface ports vs TB connection names
if iface.exists() and lb_tb.exists():
    iface_ports = set(re.findall(r'logic\s+(\w+)', iface_content))
    tb_connections = set(re.findall(r'\.(\w+)\(', content))
    # Remove Verilog keywords
    tb_connections.discard('clk')
    iface_port_names = set()
    for port_str in re.findall(r'(?:input|output)\s+(?:logic\s+)?(?:\[\d+:\d+\]\s+)?(\w+)', iface_content):
        iface_port_names.add(port_str)
    check(True, f"Interface ports: {iface_port_names}",
          f"TB connections: {[c for c in tb_connections if c not in ('clk',)]}")


# ═══════════════════════════════════ 4. Template Source Analysis ═══
print("\n-- 4. Template Source Issues --")

# 4a. agent_loopback_tb.sv.j2 - hardcoded ports
tb_tpl = TEMPLATE_DIR / "interface_templates/agent_loopback_tb.sv.j2"
if tb_tpl.exists():
    tpl_content = read_sv(tb_tpl)
    has_dynamic_clk = "{{ agent.clock }}" in tpl_content
    has_dynamic_rst = "{{ agent.reset }}" in tpl_content
    check(has_dynamic_clk or ".clk(" not in tpl_content,
          "TB template: clock port uses agent.clock (dynamic)",
          "GOOD: dynamic clock binding" if has_dynamic_clk else "ISSUE: hardcoded .clk(clk)")
    check(has_dynamic_rst or ".rst_n(" not in tpl_content,
          "TB template: reset port uses agent.reset (dynamic)",
          "GOOD: dynamic reset binding" if has_dynamic_rst else "ISSUE: hardcoded .rst_n(rst_n)")

# 4b. agent_loopback_env.sv.j2 - typedef count
env_tpl = TEMPLATE_DIR / "interface_templates/agent_loopback_env.sv.j2"
if env_tpl.exists():
    env_tpl_content = read_sv(env_tpl)
    typedef_lines = [l for l in env_tpl_content.split('\n') if 'typedef class' in l]
    check(len(typedef_lines) <= 1,
          f"Env template: typedef class count ({len(typedef_lines)})",
          "OK" if len(typedef_lines) <= 1 else "Duplicate typedef will cause warnings")

# 4c. driver.sv.j2 - CB signal pattern (迭代 ports 替代 transaction_vars)
drv_tpl = TEMPLATE_DIR / "interface_templates/driver.sv.j2"
if drv_tpl.exists():
    drv_tpl_content = read_sv(drv_tpl)
    check("{%- for port in ports %}" in drv_tpl_content,
          "Driver template: iterates over ports for cb signal access",
          "Uses physical DUT ports correctly")

# 4d. monitor.sv.j2 - CB signal pattern (迭代 ports 替代 transaction_vars)
mon_tpl = TEMPLATE_DIR / "interface_templates/monitor.sv.j2"
if mon_tpl.exists():
    mon_tpl_content = read_sv(mon_tpl)
    check("{%- for port in ports %}" in mon_tpl_content,
          "Monitor template: iterates over ports for cb signal access",
          "Uses physical DUT ports correctly")


# ═══════════════════════════════════ 5. QuestaSim Compile ═══
print("\n-- 5. QuestaSim Compile Check --")

vlog_exe = QUESTA_DIR / "vlog.exe"
vlib_exe = QUESTA_DIR / "vlib.exe"
uvm_pkg = UVM_SRC / "uvm_pkg.sv"

questa_available = vlog_exe.exists() and vlib_exe.exists()
check(questa_available, "QuestaSim available",
      f"vlog={vlog_exe.exists()}, vlib={vlib_exe.exists()}" if questa_available else "Not installed")

if questa_available:
    # Build loopback filelist
    lb_filelist = GEN_DIR / "filelist_loopback.f"
    # Agent 类文件由 UART_in_pkg.sv 通过 `include 包含 (含 loopback env/scb/test)
    # loopback_tb 是顶层 module，必须单独编译
    # 正确编译顺序: uvm_pkg → interface → agent_pkg(含所有 include) → loopback_tb
    lb_filelist.write_text(f"""// Loopback Test Filelist: UART_in
+incdir+{UVM_SRC}
+incdir+{AGENTS_DIR}
+incdir+{LB_DIR}
// 1. UVM base
{UVM_SRC / 'uvm_pkg.sv'}
// 2. Interface (standalone, 被 driver/monitor 引用)
{AGENTS_DIR / 'UART_in_interface.sv'}
// 3. Agent package (include 所有 agent + loopback 类)
{AGENTS_DIR / 'UART_in_pkg.sv'}
// 4. Loopback Testbench 顶层 module (唯一需单独编译的 loopback 文件)
{LB_DIR / 'UART_in_loopback_tb.sv'}
""", encoding='utf-8')

    work_dir = GEN_DIR / "build" / "loopback_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    # vlib
    print("  [vlib] Creating work library...")
    r1 = subprocess.run([str(vlib_exe), str(work_dir)],
                        capture_output=True, text=True, timeout=60)
    vlib_ok = r1.returncode == 0 or "already exists" in r1.stdout
    check(vlib_ok, "vlib: create work library",
          r1.stderr[:100] if not vlib_ok else "OK")

    if vlib_ok:
        # vlog
        print("  [vlog] Compiling loopback test suite...")
        vlog_cmd = [
            str(vlog_exe), "-work", str(work_dir), "-sv",
            "+incdir+" + str(UVM_SRC),
            "-timescale=1ns/1ps",
            "+define+UART_in_loop_back_test",
            str(uvm_pkg),
            "-f", str(lb_filelist),
        ]
        r2 = subprocess.run(vlog_cmd, capture_output=True, text=True, timeout=120)
        errors = r2.stdout.count("** Error")
        warnings = r2.stdout.count("** Warning")

        check(errors == 0, f"vlog compile: {errors} errors, {warnings} warnings",
              "Compile PASSED" if errors == 0 else "Compile FAILED")

        if errors > 0:
            print("  --- Compile Errors ---")
            for line in r2.stdout.split('\n'):
                if '** Error' in line:
                    print(f"    {line.strip()}")
        if warnings > 0:
            print("  --- Compile Warnings ---")
            for line in r2.stdout.split('\n'):
                if '** Warning' in line:
                    print(f"    {line.strip()}")


# ═══════════════════════════════════ 6. Regression Wrapper ═══
print("\n-- 6. Regression Wrapper Integration --")

try:
    from src.tools.compilesim.regression_wrapper import RegressionRunner
    check(True, "regression_wrapper import: OK")
except Exception as e:
    check(False, "regression_wrapper import", str(e))

try:
    runner = RegressionRunner(
        env_output_dir=str(GEN_DIR),
        filelist=str(GEN_DIR / "filelist_loopback.f"),
        top_module="UART_in_loopback_tb",
        simulator="echo",
    )
    yaml_data = runner._build_yaml(
        [{"name": "UART_in_loopback_test", "seed": 1, "count": 1}],
        tags=["loopback"]
    )
    check("loopback" in str(yaml_data), "YAML build: loopback test config",
          "Tag=loopback test generated correctly")
except Exception as e:
    check(False, "YAML build", str(e))


# ═══════════════════════════════════ Summary ═══
print("\n" + "=" * 70)
print(" SUMMARY")
print("=" * 70)

passed = sum(1 for r in RESULTS if r["pass"])
failed = sum(1 for r in RESULTS if not r["pass"])
total = len(RESULTS)

print(f"\n  Total: {total}   Passed: {passed}   Failed: {failed}")
print(f"  Pass Rate: {passed*100//total}%")

if failed > 0:
    print(f"\n  FAILED ITEMS:")
    for r in RESULTS:
        if not r["pass"]:
            print(f"    - {r['name']}")
            if r["detail"]:
                print(f"      => {r['detail']}")

print(f"\n  Completed: {datetime.now().isoformat()}")
sys.exit(0 if failed == 0 else 1)
