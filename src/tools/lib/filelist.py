"""
Filelist 构建 —— 生成 QuestaSim vlog 兼容的 filelist.f

用法:
    from src.tools.lib.filelist import build_filelist_for_tb, build_loopback_filelist
    fl = build_filelist_for_tb(output_dir, agents, "dut_env")
    lb_fl = build_loopback_filelist(output_dir, "agent_name")
"""
from pathlib import Path


def derive_env_name(output_dir: Path) -> str:
    """从已生成的 `env/` 里**认出环境名**。

    **不要**用"取排序第一个 `*_pkg.sv` 再去掉后缀"那种写法 —— 它错得很安静：
    env 目录里同时躺着

        apb_uart_env.sv              apb_uart_env_pkg.sv            ← 环境本体
        apb_uart_env_parameters_pkg.sv                             ← 子包

    而 `_parameters_` 按字母序**排在 `_pkg` 前面**（`pa` < `pk`），于是"第一个"
    是子包，环境名被猜成 `apb_uart_env_parameters`。filelist 里随即写满不存在的
    文件，vlog 第一个就报 `Failed to open design unit file`。实测踩过：
    `env_arch_check` 编译失败、`ops` 回归失败，一路到 run 挂掉。

    用一条**能唯一命中**的规则：环境包必然有一个同名兄弟 `{name}.sv`（环境类）——
    `apb_uart_env.sv` 在，`apb_uart_env_parameters.sv` 不在。多个命中时取最短的
    （子包名总是父名加后缀）。
    """
    env_dir = Path(output_dir) / "env"
    if not env_dir.is_dir():
        return "dut_env"

    matched = [p.name.replace("_pkg.sv", "")
               for p in sorted(env_dir.glob("*_pkg.sv"))
               if (env_dir / f"{p.name.replace('_pkg.sv', '.sv')}").is_file()]
    if matched:
        return min(matched, key=len)

    # 兜底：一个都没命中（比如环境类没生成出来）。退回老办法，但**它是兜底**，
    # 不是主路径 —— 正常生成的 env 一定走上面那条。
    for pkg in sorted(env_dir.glob("*_pkg.sv")):
        return pkg.name.replace("_pkg.sv", "")
    return "dut_env"


def _repo_root() -> Path:
    """仓库根 —— 本文件在 `src/tools/lib/` 下，往上三级。"""
    return Path(__file__).resolve().parents[3]


def _base_pkg_lines() -> list:
    """工具源码树里的公共包（`tool_uvm/base_pkg/`）。

    **它们不在运行目录里**，所以以前那份"只扫运行目录"的清单从来没收进来过 ——
    而每个 agent 包都 `import common_typedefs_pkg::*`，vlog 于是报一串
    `Could not find the package (common_typedefs_pkg)`。clk_and_rst / scb 同理。
    """
    base = _repo_root() / "src" / "tools" / "uvm_tools" / "tool_uvm" / "base_pkg"
    out = []
    for sub in ("clk_and_rst", "scb", "common_typedefs"):
        d = base / sub
        if not d.is_dir():
            continue
        out.append(f"+incdir+{d.as_posix()}")
        out.extend(sv.as_posix() for sv in sorted(d.glob("*.sv")))
    return out


def _uvm_lines() -> list:
    """UVM 库本身（`uvm_pkg.sv` + incdir）。

    与 `collect_real_coverage.compile_with_coverage` 同一套推导 —— 那边早就在做，
    这份 filelist 一直没有。少了它 vlog 第一句就是 `Could not find the package
    (uvm_pkg)`，后面全是连带错误。
    """
    try:
        from config.settings import questa_home

        root = questa_home()
    except Exception:
        return []
    if not root:
        return []
    src = Path(root) / "verilog_src" / "uvm-1.2" / "src"
    pkg = src / "uvm_pkg.sv"
    if not pkg.is_file():
        return []
    return [f"+incdir+{src.as_posix()}", pkg.as_posix()]


def _sub_pkg_names() -> tuple:
    """**子包**的文件名后缀 —— 它们要排在主包前面。

    环境包会 `import {env}_parameters_pkg::*` / `_typedefs_pkg::*`，所以子包必须先编译。
    列出来也是为了让 `*_pkg.sv` 那个 glob 能把它们排除掉（否则同一个文件进清单两遍）。
    """
    return ("_parameters_pkg.sv", "_typedefs_pkg.sv")


def _packages_in(directory: Path) -> list:
    """目录下的**主包**（含 `*_pkg.sv`，但不含子包）。"""
    if not directory.is_dir():
        return []
    subs = _sub_pkg_names()
    return sorted(sv for sv in directory.glob("*_pkg.sv")
                  if not sv.name.endswith(subs))


def _agent_lines(output_dir: Path, name: str) -> list:
    """一个 agent 的编译清单：子包 → 接口 → 主包。

    顺序不能换：`{agent}_pkg.sv` 里 `` `include `` 了驱动/监视器/序列，
    并通过 `import {agent}_typedefs_pkg::*` 取类型。
    """
    d = output_dir / "agents" / name
    if not d.is_dir():
        return []
    subs = _sub_pkg_names()
    out = [f"+incdir+{d.as_posix()}"]
    out.extend(sv.as_posix() for sv in sorted(d.glob("*.sv"))
               if sv.name.endswith(subs))
    iface_dir = d / "1_interface"
    if iface_dir.is_dir():
        out.extend(sv.as_posix() for sv in sorted(iface_dir.glob("*.sv")))
    out.extend(sv.as_posix() for sv in _packages_in(d))
    return out


def agent_layout(agent_dir: Path) -> dict:
    """一个 agent 目录里"写激励时要看/要改"的那几个文件。

    生成出来的 env 走的是**编号子目录布局**（模板见 `tool_uvm/templates/agent_templates/`）：

        1_interface/*_if.sv                      端口定义
        3_transaction_sequencer/*_seq_item.sv    事务项（rand 字段在这）
        <proto>_pkg.sv                           主包（`include 上面那些）
        7_sequence/*_sequence.sv                 已有序列

    平铺名（`<agent>_interface.sv` / `<agent>_transaction.sv` / `<agent>_pkg.sv`）
    是**旧布局**，不要再按它找 —— 实测事故：补定向激励那一步按平铺名找，
    于是每个 agent 都被跳过、产出 0 个文件（`verify_supplement` FAIL 20）。
    这是同一类错里的第二次（前一次是覆盖率编译的 filelist 漏了 UVM 库）。

    返回 `{"interface": [Path...], "seq_items": [Path...], "package": Path|None,
    "sequences": [Path...]}`。两套布局都认；认不出的项是空列表。
    """
    d = Path(agent_dir)
    if not d.is_dir():
        return {"interface": [], "seq_items": [], "package": None, "sequences": []}

    def pick(*patterns):
        found = []
        for pattern in patterns:
            found.extend(sorted(p for p in d.glob(pattern) if p.is_file()))
        return found

    package = None
    pkgs = _packages_in(d)                       # 主包（排除 _parameters/_typedefs 子包）
    if pkgs:
        package = Path(pkgs[0])
    else:
        flat = sorted(d.glob("*_pkg.sv"))
        if flat:
            package = flat[0]

    return {
        "interface": pick("1_interface/*.sv", "1_interface/*.svh",
                          "*_interface.sv", "interface/*.sv"),
        "seq_items": pick("3_transaction_sequencer/*_seq_item.sv",
                          "*_seq_item.sv", "*_transaction.sv"),
        "package": package,
        "sequences": pick("7_sequence/*.sv", "*_sequence.sv"),
    }


def _env_lines(output_dir: Path, env_name: str) -> list:
    """环境层：子包 → 环境包 → seqs → tests。"""
    d = output_dir / "env"
    if not d.is_dir():
        return []
    subs = _sub_pkg_names()
    out = [f"+incdir+{d.as_posix()}"]
    out.extend(sv.as_posix() for sv in sorted(d.glob("*.sv"))
               if sv.name.endswith(subs))
    out.extend(sv.as_posix() for sv in _packages_in(d))
    for sub in ("seqs", "tests"):
        sub_dir = d / sub
        if not sub_dir.is_dir():
            continue
        out.append(f"+incdir+{sub_dir.as_posix()}")
        out.extend(sv.as_posix() for sv in _packages_in(sub_dir))
    return out


def _bench_lines(output_dir: Path) -> list:
    """bench 层：**harness 先于 tb_top** —— tb_top 里例化的是 harness。"""
    d = output_dir / "bench"
    if not d.is_dir():
        return []
    out = [f"+incdir+{d.as_posix()}"]
    out.extend(sv.as_posix() for sv in sorted(d.glob("*_harness.sv")))
    tops = sorted(d.glob("*_tb_top.sv"))
    if tops:
        out.extend(sv.as_posix() for sv in tops)
    else:
        # 没找到 tb_top 就把 bench 下的都列上（老布局的兜底）
        out.extend(sv.as_posix() for sv in sorted(d.glob("*.sv"))
                   if not sv.name.endswith("_harness.sv"))
    return out


def build_filelist_for_tb(output_dir: Path, agents: list, env_name: str,
                          filelist_name: str = "filelist.f") -> Path:
    """构建全环境编译 filelist。

    **顺序即依赖**，不能指望 vlog 自己猜：

        公共包(base_pkg) → UVM → 各 agent(子包 → 接口 → 主包) → RTL/参考模型
        → env(子包 → 主包) → env/seqs → env/tests → bench(harness → tb_top)

    这份清单原来是"只扫运行目录"的：**公共包与 UVM 一个都没收进来**，agent 包的
    文件名也是按 `{目录名}_pkg.sv` 猜的（实际是 `{协议}_pkg.sv`，目录叫
    `apb_agent` 而包叫 `apb_pkg`）。结果 vlog 一上手就报
    `Could not find the package (uvm_pkg)` / `(common_typedefs_pkg)` / `(apb_pkg)`，
    后面全是连带错误 —— 等于这份 filelist 编译不了任何东西。

    现在按**盘上真实存在的文件**收（glob 各目录），而不是猜文件名 —— 生成器改了
    命名，这里跟着走，不会再对不上。
    """
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl_path = fl_dir / filelist_name

    lines = []
    # **UVM 必须最先**：base_pkg 里那几个包自己也 `import uvm_pkg::*`。
    # 反过来写就会得到 `clk_and_rst_pkg.sv(19): Could not find the package (uvm_pkg)`
    # 外加一屏连带错误。实测踩过。
    lines.extend(_uvm_lines())
    lines.extend(_base_pkg_lines())
    for a in agents:
        lines.extend(_agent_lines(output_dir, a["name"]))

    # RTL 与参考模型：harness 要 bind 到 DUT 模块，tb_top 要例化它们 ——
    # 都必须排在 bench 之前。
    rtl_dir = output_dir / "rtl"
    if rtl_dir.is_dir():
        lines.extend(sv.as_posix() for sv in sorted(rtl_dir.glob("*.sv")))
    model_dir = output_dir / "model"
    if model_dir.is_dir():
        lines.extend(sv.as_posix() for sv in sorted(model_dir.rglob("*_ref_model.sv")))

    # 功能覆盖率探针（`bind` 进 DUT）—— **必须排在 RTL 之后**：`bind <dut_module>`
    # 要求目标模块已经声明。采的是 `sample: dut` 的那些信号（内部状态 / 输出端口），
    # monitor 的事务通道一个都采不到，只有 bind 进去才看得见。
    #
    # 收 `*_probe.sv` 而不是整个 `coverage/` 目录：那里还躺着 `coverage_points.json`
    # 之类的非 SV 产物，一股脑收进来是给 vlog 塞垃圾。
    cov_dir = output_dir / "coverage"
    if cov_dir.is_dir():
        lines.extend(sv.as_posix() for sv in sorted(cov_dir.glob("*_probe.sv")))

    lines.extend(_env_lines(output_dir, env_name))
    lines.extend(_bench_lines(output_dir))

    # 全部转成**绝对路径**：`-f` 文件里的相对路径是相对 **cwd** 解析的（不是相对
    # filelist 自己），而这份清单可能被不同 cwd 的调用方拿去编译。老实现用的就是
    # resolve()，这里保持。
    resolved = []
    for line in lines:
        prefix = "+incdir+" if line.startswith("+incdir+") else ""
        body = line[len(prefix):]
        try:
            resolved.append(prefix + Path(body).resolve().as_posix())
        except OSError:
            resolved.append(line)

    fl_path.write_text("\n".join(resolved), encoding="utf-8", errors="replace")
    return fl_path


def build_loopback_filelist(output_dir: Path, agent_name: str) -> Path:
    """构建单 agent loopback 编译 filelist。

    产物名 `filelist_<agent_name>_lb.f`，**agent_name 是 agent 目录名**
    （如 `apb_agent`）—— `InfrastructureManager.run_regression` 就是拿
    `agents/` 下的目录名来调的，`regression.yaml` 里的 build 也必须引用同一个名字，
    否则 vlog 报 "Failed to open -f file ... No such file or directory"。

    路径按**当前 agent 目录布局**写：
      <agent>/1_interface/<if>_if.sv, <if>_system_if.sv
      <agent>/<if>_parameters_pkg.sv, <if>_typedefs_pkg.sv, <if>_pkg.sv
      <agent>/loopback/<if>_loopback_{scb,env,test,tb}.sv
    其中 `<if>` = 目录名去掉 `_agent`（包/接口名是协议名，不是 agent 名）。

    另：loopback tb 自己也要 `uvm_pkg` 和 `base_pkg`（clk_rst / scb /
    common_typedefs），所以这里带上 —— 只列 agent 自己的文件会缺 `uvm_pkg::*`。
    """
    fl_dir = output_dir / "inputs" / "filelists"
    fl_dir.mkdir(parents=True, exist_ok=True)
    fl = fl_dir / f"filelist_{agent_name}_lb.f"
    agent_dir = output_dir / "agents" / agent_name
    iface = agent_name[:-len("_agent")] if agent_name.endswith("_agent") else agent_name

    lines = _uvm_lines() + _base_pkg_lines()
    lines.append(f"+define+{iface}_loop_back_test")
    lines.append(f"+incdir+{agent_dir.resolve()}/loopback")
    lines.append(f"+incdir+{agent_dir.resolve()}")
    for rel in (
        f"{iface}_parameters_pkg.sv",
        f"{iface}_typedefs_pkg.sv",
        f"1_interface/{iface}_if.sv",
        f"1_interface/{iface}_system_if.sv",
        f"{iface}_pkg.sv",
        f"loopback/{iface}_loopback_scb.sv",
        f"loopback/{iface}_loopback_env.sv",
        f"loopback/{iface}_loopback_test.sv",
        f"loopback/{iface}_loopback_tb.sv",
    ):
        p = agent_dir / rel
        if p.exists():
            lines.append(str(p.resolve()))
    fl.write_text("\n".join(lines), encoding="utf-8", errors="replace")
    return fl
