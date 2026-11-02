"""SoC C 用例执行器 —— E203 CPU 跑 bare-metal C，驱动 NICE/NPU IP。

只做三件事：
  1. 用工程自带的 `sw/build_sw.py` 编 C（需要 RISC-V 工具链）；
  2. 用 Questa 编 E203 SoC（E203 源树只读 + 编译期同名覆盖适配器）；
  3. 跑 `tb_soc_top +TESTCASE=<firmware>`（内部例化 E203 `tb_top`），
     按日志里的 TEST_PASS/TEST_FAIL 判定。

不是第二套验证引擎：C 用例只是 SoC 业务的一种 case；产物仍可进 run 目录。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

CASE_FILE = Path("sw") / "cases.yaml"


def _read_yaml(path: Path) -> Dict[str, Any]:
    try:
        import yaml

        doc = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace"))
    except Exception:                               # noqa: BLE001
        return {}
    return doc if isinstance(doc, dict) else {}


def list_c_cases(project_root: str | Path) -> List[Dict[str, Any]]:
    root = Path(project_root).resolve()
    doc = _read_yaml(root / CASE_FILE)
    return [c for c in (doc.get("cases") or []) if isinstance(c, dict)]


def c_case(project_root: str | Path, case_id: str) -> Dict[str, Any]:
    for case in list_c_cases(project_root):
        if str(case.get("id") or "") == str(case_id or ""):
            return case
    return {}


def _run(argv, cwd: Path, log: Optional[Path] = None) -> subprocess.CompletedProcess:
    proc = subprocess.run([str(x) for x in argv], cwd=str(cwd),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=600)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text((proc.stdout or "") + (proc.stderr or ""),
                       encoding="utf-8", errors="replace")
    return proc


def _build_firmware(root: Path, out_dir: Path) -> Dict[str, Any]:
    script = root / "sw" / "build_sw.py"
    if not script.is_file():
        return {"ok": False, "error": f"缺 {script}"}
    log = out_dir / "build_sw.log"
    proc = _run([sys.executable, str(script)], cwd=root, log=log)
    verilog = root / "sw" / "gemm_8x8.verilog"
    return {"ok": proc.returncode == 0 and verilog.is_file(),
            "log": str(log), "verilog": str(verilog),
            "error": "" if proc.returncode == 0 else (proc.stderr or "")[-400:]}


def _e203_filelist(root: Path) -> List[Path]:
    """C 用例编译文件表 —— **E203 源树只读**。

    `e203_hbirdv2/` 保持原样：NICE 适配器 / int8_gemm 在文件表**末尾**再编
    一次，覆盖树内同名模块（Questa 后编覆盖前编）。顶层复用
    `tb/tb_soc_top.sv`（`+define+E203_C_RUN` 时例化 E203 `tb_top`）。
    NPU 子系统（`npu/npu_top.sv`）挂在 `e203_subsys_top` 层级，与
    `e203_subsys_main` 同级。
    """
    e203 = root / "e203_hbirdv2"
    files = sorted((e203 / "rtl" / "e203").rglob("*.v"))
    tb = e203 / "tb" / "tb_top.v"
    if tb.is_file():
        files.append(tb)
    files.append(root / "tb" / "tb_soc_top.sv")
    # 覆盖：必须在树内同名文件之后
    files.append(root / "npu" / "npu_top.sv")
    files.append(root / "npu" / "nice_disp" / "e203_nice_npu_adapter.sv")
    files.append(root / "npu" / "npu" / "int8_gemm.sv")
    return files


def _compile_e203(root: Path, out_dir: Path) -> Dict[str, Any]:
    from config.settings import questa_exe

    files = _e203_filelist(root)
    if not files:
        return {"ok": False, "error": "E203 RTL 不存在"}
    cpu = root / "e203_hbirdv2" / "rtl" / "e203" / "core" / "e203_cpu.v"
    subsys = (root / "e203_hbirdv2" / "rtl" / "e203" / "subsys"
              / "e203_subsys_top.v")
    try:
        wired = ("nice_req_valid_o" in cpu.read_text(
                     encoding="utf-8", errors="replace")
                 and "npu_top" in subsys.read_text(
                     encoding="utf-8", errors="replace"))
    except OSError:
        wired = False
    if not wired:
        return {"ok": False,
                "error": "E203 未把 NICE 接口引到子系统层级 / 未实例化 npu_top；"
                         "C 用例需要已重新集成的 E203 基线"}
    work = out_dir / "e203" / "work"
    work.mkdir(parents=True, exist_ok=True)
    filelist = out_dir / "e203" / "filelist.f"
    filelist.parent.mkdir(parents=True, exist_ok=True)
    filelist.write_text("\n".join(p.resolve().as_posix() for p in files),
                        encoding="utf-8")
    vlog = questa_exe("vlog.exe")
    if not Path(vlog).exists():
        return {"ok": False, "error": f"找不到 vlog：{vlog}"}
    e203 = root / "e203_hbirdv2" / "rtl" / "e203"
    proc = _run([
        vlog, "-work", str(work), "-sv", "-mfcu", "+acc", "-linedebug",
        f"+incdir+{(e203 / 'core').as_posix()}",
        f"+incdir+{(e203 / 'perips').as_posix()}",
        f"+incdir+{(e203 / 'perips' / 'apb_i2c').as_posix()}",
        "+define+DISABLE_SV_ASSERTION=1",
        "+define+E203_C_RUN=1",
        "-f", str(filelist), "-l", str(out_dir / "e203" / "build.log"),
    ], cwd=out_dir, log=None)
    if proc.returncode != 0:
        return {"ok": False, "work": str(work),
                "log": str(out_dir / "e203" / "build.log"),
                "error": ((proc.stdout or "") + (proc.stderr or ""))[-600:]}

    # Visualizer 源码浏览需要 vopt 产出的 design.bin（qwave.db 只是一半）。
    design = out_dir / "e203" / "design.bin"
    vopt = questa_exe("vopt.exe")
    if not Path(vopt).exists():
        return {"ok": False, "error": f"找不到 vopt：{vopt}"}
    proc2 = _run([
        vopt, "-work", str(work), "-designfile", str(design),
        "-linedebug", "+acc", "-suppress", "7061", "-suppress", "3009",
        "-o", "tb_soc_top_opt", "tb_soc_top",
    ], cwd=out_dir, log=out_dir / "e203" / "vopt.log")
    ok = proc2.returncode == 0 and design.is_file()
    return {"ok": ok, "work": str(work),
            "log": str(out_dir / "e203" / "build.log"),
            "vopt_log": str(out_dir / "e203" / "vopt.log"),
            "design": str(design) if design.is_file() else "",
            "error": "" if ok else ((proc2.stdout or "") + (proc2.stderr or ""))[-600:]}


def _slug(case_id: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in str(case_id)).strip("_")


def _run_e203(root: Path, out_dir: Path, firmware: Path,
              case_id: str = "") -> Dict[str, Any]:
    from config.settings import questa_exe

    work = out_dir / "e203" / "work"
    # TB 把 firmware 读进 ITCM index 0..65535；objcopy 的 @80000000 要改 @0。
    text = firmware.read_text(encoding="utf-8", errors="replace")
    testcase = out_dir / "e203" / "gemm_8x8_zero.verilog"
    relocated = text.replace("@80000000", "@00000000", 1)
    testcase.write_text(relocated, encoding="utf-8")
    # E203 tb_top 里 `$value$plusargs("TESTCASE=%s")` 与 `$readmemh` 是两个
    # 独立的 initial 块；开 +acc（波形需要）后 Questa 会改变 time-0 initial
    # 的执行顺序，readmemh 可能先跑、看到空 testcase，于是去找字面量
    # ".verilog"。在 vsim 的 cwd 放一份同名兜底镜像，两种顺序都能加载。
    (work.parent / ".verilog").write_text(relocated, encoding="utf-8")
    case_arg = testcase.with_suffix("").as_posix()
    vsim = questa_exe("vsim.exe")
    if not Path(vsim).exists():
        return {"ok": False, "error": f"找不到 vsim：{vsim}"}
    wave = out_dir / "e203" / "waves" / f"c_{_slug(case_id) or 'case'}.db"
    wave.parent.mkdir(parents=True, exist_ok=True)
    log = out_dir / "e203" / "sim.log"
    proc = _run([
        vsim, "-c", "-work", "work",
        "-suppress", "3009", "-suppress", "7061", "tb_soc_top_opt",
        f"+TESTCASE={case_arg}", "+DUMPWAVE=0",
        "-do", "log -r /*; run -all; quit", "-l", str(log),
        f"-qwavedb=+signal+memory=4096,4+class+wavefile={wave}",
    ], cwd=work.parent, log=None)
    body = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    ok = "TEST_PASS" in body
    failed = "TEST_FAIL" in body or "Time Out" in body
    return {"ok": ok, "failed": failed, "log": str(log),
            "wave": str(wave) if wave.is_file() else "",
            "error": "" if ok else ("TEST_FAIL" if failed else (proc.stderr or "")[-400:])}


def run_c_case(project_root: str | Path, case_id: str,
               output: str | Path = None) -> Dict[str, Any]:
    root = Path(project_root).resolve()
    case = c_case(root, case_id)
    if not case:
        return {"status": "FAIL", "error": f"C 用例不存在: {case_id}"}
    out = Path(output).resolve() if output else (root / f"output_c_{case_id}")
    out.mkdir(parents=True, exist_ok=True)

    fw = _build_firmware(root, out)
    if not fw.get("ok"):
        return {"status": "FAIL", "stage": "build_sw", **fw,
                "output_root": str(out)}
    comp = _compile_e203(root, out)
    if not comp.get("ok"):
        return {"status": "FAIL", "stage": "compile_e203", **comp,
                "output_root": str(out)}
    run = _run_e203(root, out, Path(fw["verilog"]), str(case.get("id") or ""))
    status = "PASS" if run.get("ok") else "FAIL"
    waves = ([{"path": Path(run["wave"]).relative_to(out).as_posix()}]
             if run.get("wave") else [])
    design = comp.get("design") or ""
    design_doc = ({"path": Path(design).relative_to(out).as_posix()}
                  if design else {})
    doc = {"schema": "soc_c_run_v1", "case": case, "status": status,
           "output_root": str(out), "firmware": fw,
           "compile": comp, "sim": run, "waves": waves,
           "design": design_doc}
    (out / "c_run.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc
