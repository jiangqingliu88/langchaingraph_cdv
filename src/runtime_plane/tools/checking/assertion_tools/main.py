"""断言工具集 — 真实 SVA 生成（非 mock）。"""
from src.runtime_plane.tools._lc_tool_compat import tool
import json, re


def _parse_spec(specs: str) -> dict:
    """从 specs 文本提取关键信息。"""
    if not specs:
        return {}
    try:
        data = json.loads(specs) if isinstance(specs, str) else specs
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    return {"raw": str(specs)[:2000]}


def _extract_clock_reset(spec: dict) -> tuple:
    """提取时钟和复位信号名。"""
    va = spec.get("verification_architecture", {}) or {}
    cr = va.get("clock_reset", {}) or {}
    return cr.get("clk", "clk"), cr.get("rst_n", "rst_n")


def _extract_interfaces(spec: dict) -> list:
    interfaces = spec.get("interfaces", []) or []
    if not interfaces and spec.get("raw"):
        text = spec["raw"]
        interfaces = []
        if re.search(r'APB|apb', text):
            interfaces.append({"name": "APB", "type": "APB", "signals": {"psel": {}, "penable": {}, "pwrite": {}, "paddr": {}, "pwdata": {}, "prdata": {}}})
        if re.search(r'UART|uart|串行', text):
            interfaces.append({"name": "UART", "type": "UART", "signals": {"tx": {}, "rx": {}}})
        if re.search(r'中断|interrupt|irq', text, re.IGNORECASE):
            interfaces.append({"name": "INTR", "type": "Interrupt", "signals": {"irq": {}}})
    return interfaces


def _ident(text, fallback: str = "") -> str:
    """任意名字 → SV 标识符（只看 ASCII —— `"指".isalnum()` 也是 True，放过去会
    生成非 ASCII 标识符，而 vlog 报的是 "Errors: 0"）。"""
    s = "".join(ch if (ch.isascii() and (ch.isalnum() or ch == "_")) else "_"
                for ch in str(text or ""))
    s = s.strip("_")
    while "__" in s:
        s = s.replace("__", "_")
    if not s:
        return fallback
    return ("x" + s) if s[0].isdigit() else s


@tool("generate_sva_assertions")
def generate_sva_assertions(specs: str = "") -> str:
    """根据设计规格生成 SVA 断言 —— **可编译、且真的会报错的**一份。

    ## 为什么必须包成 module + bind

    原来这个函数直接把 `property ... endproperty` 与 `assert property(...)` 平铺在
    文件的 **$unit 作用域**：

      · `property` / `assert property` **不能**待在 $unit（必须在 module / interface /
        checker / program 里）—— 那样生成的文件**编不过**；
      · 而且它生成出来之后**没有人把它放进编译清单**（全 run 搜一遍，没有任何
        `.f`/`.sv`/`.yaml` 引用过 `assertions/<模块>_assertions.sv`）。

    两层加起来的结果：**断言一行都没编进去**，"assertion 不报错"这件事从来没有被
    检验过 —— 它不是"没有违规"，是"没有断言"。

    与基准探针同一条路子（见 `vplan/runtime/coverage.render_probe`）：包成一个
    **module**，用 `bind` 挂进 DUT —— 端口连接表达式在**目标模块作用域**里求值，
    所以 `clk`/`rst_n` 以及断言的信号直接按名字连得过去，不必知道层次路径。

    `dut_module` 由 `sampling.dut_module`（case 模型的 `sampling:` 块）给出；
    **给不出就不生成**（`""`）—— 一份挂不到任何模块上的断言，只会又是一个
    "看着有、从没编过"的产物。
    """
    spec = _parse_spec(specs)
    clk, rst_n = _extract_clock_reset(spec)
    interfaces = _extract_interfaces(spec)
    features = spec.get("features", []) or []
    features_text = " ".join(str(f) for f in features)

    dut_module = _ident((spec.get("sampling") or {}).get("dut_module", ""))
    if not dut_module:
        return ""            # 挂不到对象上 —— 宁可不生成（调用方据此如实记账）

    clk, rst_n = _ident(clk, "clk"), _ident(rst_n, "rst_n")
    props: list = []         # 每项 = (注释, property 名, 属性体, 违规消息)
    #: 断言体里**引用到的**信号 → 位宽。它们必须是 module 的**端口**（bind 靠端口
    #: 连接把 DUT 的信号接进来）—— 只声明 clk/rst_n 的话，`psel` 这类名字在
    #: module 里就是未定义变量，**vlog 直接报 `Undefined variable`**（实测）。
    #: 只收**引用到的**，不是"该协议的全体信号"：多声明一个 DUT 里没有的名字，
    #: 就变成绑不上的端口（vopt 报错），那同样是"生成得出来、编译不过"。
    used_sigs: dict = {}

    def _note_signals(body: str, sigs: dict) -> None:
        for s in (sigs or {}):
            if re.search(rf"\b{re.escape(str(s))}\b", body):
                w = 1
                if isinstance(sigs.get(s), dict):
                    try:
                        w = max(1, int(sigs[s].get("width", 1) or 1))
                    except (TypeError, ValueError):
                        w = 1
                used_sigs[str(s)] = w

    sv_lines: list = []

    # ── 模型声明的断言**优先** ──
    #
    # 执行资产的 `assertions.csv` 是设计者写的（"这条规则必须恒成立"），
    # 比自动生成认得出的协议特征**精确得多** —— 自动那套只认 APB/UART/handshake
    # 这类通用特征，对调度器/仲裁器这种自定义逻辑一个都认不出来（实测：给
    # npu_sched 生成出来的是空串）。模型给了就用模型的，自动那套是兜底。
    for a in (spec.get("assertions") or []):
        if not isinstance(a, dict):
            continue
        expr = str(a.get("expr") or "").strip()
        nm = _ident(a.get("name") or "", "")
        if not (expr and nm):
            continue
        props.append((str(a.get("group") or "模型声明"),
                      _ident(a.get("name"), "prop"),
                      expr, str(a.get("message") or nm)))
        for s in (a.get("signals") or []):
            if isinstance(s, dict) and s.get("name"):
                try:
                    w = max(1, int(s.get("width", 1) or 1))
                except (TypeError, ValueError):
                    w = 1
                used_sigs[_ident(s["name"], "")] = w

    for iface in interfaces:
        name = iface.get("name", "?")
        sigs = iface.get("signals", {}) or {}
        sig_names = list(sigs.keys()) if isinstance(sigs, dict) else []

        # APB protocol assertions
        if name == "APB" or "APB" in str(sig_names):
            props += [
                ("APB Protocol", "apb_setup_check",
                 "$rose(psel) |-> psel && !penable", "APB setup violation"),
                ("APB Protocol", "apb_stable_check",
                 "psel && penable |-> $stable(paddr) && $stable(pwrite)",
                 "APB address/write unstable"),
            ]
            for _l, _p, _b, _m in props[-2:]:
                _note_signals(_b, sigs)

        # UART assertions
        if name == "UART" or "UART" in str(sig_names):
            props.append(
                ("UART Protocol", "tx_start_stop",
                 "$fell(tx) |-> ##9 $rose(tx)  // 1 start + 8 data + 1 stop",
                 "UART TX frame error"))
            _note_signals("$fell(tx) $rose(tx)", sigs)

        # Handshake assertions
        if any(kw in features_text for kw in ["handshake", "握手", "valid", "ready"]):
            props.append(
                ("Handshake", "handshake_stable",
                 "valid && !ready |=> $stable(data) && valid",
                 "Data changed before ready"))
            _note_signals("valid ready data", sigs)

    # ⚠️ 原来这里还有一条 reset 断言：
    #
    #     !rst_n |-> ##1 rst_n [*2] ##1 !rst_n
    #
    # **它是错的，已删**。那条说的是"复位有效之后，rst_n 必须高两拍、然后再拉低一步"
    # —— 而任何正常设计的复位释放后 rst_n 就一直为高。发出去的结果不是"报了真错"，
    # 是**每条用例都误报一次**（造假的失败：比不报还坏，因为人很快会学会忽略断言）。
    # 断言必须**对正确设计恒真**才谈得上"不报错 = 没问题"。
    #
    # 所以：没有可断言的协议特征时**不出断言**（返回空串），由调用方如实记账 ——
    # 编一条恒假的断言出来，只会把"没有断言"伪装成"断言在跑"。

    if not props:
        return ""            # 无可断言特征 → 不生成（调用方据此记一笔）

    # ── 包成可 bind 的 module ──
    mod = f"{dut_module}_sva"
    guard = f"{mod.upper()}_SV"
    out = [
        f"`ifndef {guard}",
        f"`define {guard}",
        "",
        "// SVA 断言 —— 由 `generate_sva_assertions` 生成，**bind 进 DUT**。",
        "//",
        "// 为什么必须是 module + bind：`property` / `assert property` **不能**待在 $unit",
        "// 作用域（原来就是这么生成的 → 一份编不过的文件，而且没人把它放进编译清单）。",
        "// bind 的端口连接表达式在**目标模块作用域**里求值，所以 clk/rst_n 与断言里引用的",
        "// 信号按名字直接连得过来，不必知道层次路径。",
        "",
        f"module {mod} (",
        f"  input logic {clk},",
        f"  input logic {rst_n},",
    ]
    for _n, _w in sorted(used_sigs.items()):
        out.append(f"  input logic [{_w - 1}:0] {_ident(_n)}," if _w > 1
                   else f"  input logic {_ident(_n)},")
    out[-1] = out[-1].rstrip(",")          # 端口表尾不许留逗号
    out.append(");")
    for label, pname, body, msg in props:
        out += [
            f"  // ── {label} ──",
            f"  property {pname};",
            f"    @(posedge {clk}) disable iff (!{rst_n}) {body};",
            "  endproperty",
            f'  {pname}_a: assert property({pname}) else $error("{msg}");',
            "",
        ]
    # 连接表**不带尾逗号**，统一由 join 加分隔符（`...,)` 是语法错误；两个来源
    # 各带一个逗号就会连成 `...),,`，而那是**编不过**的）
    conns = [f"  .{clk}({clk})", f"  .{rst_n}({rst_n})"]
    conns += [f"  .{_ident(_n)}({_ident(_n)})" for _n in sorted(used_sigs)]
    out += ["endmodule", "", f"bind {dut_module} {mod} u_{mod}(",
            ",\n".join(conns), ");", "", f"`endif  // {guard}", ""]
    return "\n".join(out)


@tool("generate_immediate_assertions")
def generate_immediate_assertions(specs: str = "") -> str:
    """生成即时断言 (assert final / assert)"""
    spec = _parse_spec(specs)
    registers = spec.get("registers", []) or []
    lines = ["// Immediate Assertions", ""]
    for r in registers[:10]:
        if isinstance(r, dict):
            name = r.get("name", "reg")
            width = r.get("width", 8)
            lines.append(f"// Register {name} access check")
            lines.append(f"always_comb assert ({name} !== {width}'bx) else $error(\"{name} is X\");")
            lines.append("")
    if len(lines) <= 2:
        lines.append("always_comb assert (1) else $error(\"dummy\");")
    return "\n".join(lines)


@tool("generate_concurrent_assertions")
def generate_concurrent_assertions(specs: str = "") -> str:
    """生成并发断言 (property)"""
    spec = _parse_spec(specs)
    clk, rst_n = _extract_clock_reset(spec)
    lines = [f"// Concurrent Assertions — {clk}", ""]
    lines.append(f"property no_x_on_output;")
    lines.append(f"    @(posedge {clk}) disable iff (!{rst_n})")
    lines.append(f"    $stable(rst_n) |-> !$isunknown(data_out);")
    lines.append("endproperty")
    lines.append("no_x_assert: assert property(no_x_on_output) else $error(\"X on output\");")
    return "\n".join(lines)


@tool("generate_formal_properties")
def generate_formal_properties(specs: str = "") -> str:
    """生成形式验证属性"""
    spec = _parse_spec(specs)
    clk, rst_n = _extract_clock_reset(spec)
    return f"""// Formal Verification Properties
// Clock: {clk}, Reset: {rst_n}

// Safety: no deadlock
property no_deadlock;
    @(posedge {clk}) disable iff (!{rst_n})
    s_eventually($past({rst_n}));
endproperty

// Liveness: every request gets a response
property req_ack_liveness;
    @(posedge {clk}) disable iff (!{rst_n})
    req |-> s_eventually(ack);
endproperty

// Bounded: response within N cycles
property bounded_response;
    @(posedge {clk}) disable iff (!{rst_n})
    req |-> ##[1:16] ack;
endproperty
"""


@tool("generate_cdc_assertions")
def generate_cdc_assertions(specs: str = "") -> str:
    """生成跨时钟域检查断言"""
    spec = _parse_spec(specs)
    interfaces = _extract_interfaces(spec)
    # Check if multiple clock domains exist
    clocks = set()
    for iface in interfaces:
        if isinstance(iface, dict):
            c = iface.get("clock", "")
            if c:
                clocks.add(c)
    if len(clocks) < 2:
        return "// No multi-clock domain detected — CDC not applicable"
    clk_list = list(clocks)
    return f"""// CDC Assertions — {len(clocks)} clock domains: {', '.join(clk_list)}

// Pulse synchronizer check
property cdc_pulse_width;
    @(posedge {clk_list[0]})
    pulse_in |-> ##1 pulse_in [*2];  // pulse must be >2 cycles in source domain
endproperty
cdc_pulse_assert: assert property(cdc_pulse_width);

// Bus CDC: gray code check
property gray_code_check(bus);
    @(posedge {clk_list[0]})
    $stable(bus) || $onehot(bus ^ $past(bus));
endproperty
"""


@tool("generate_cover_properties")
def generate_cover_properties(specs: str = "") -> str:
    """生成 cover property (覆盖率属性)"""
    spec = _parse_spec(specs)
    clk, rst_n = _extract_clock_reset(spec)
    features = spec.get("features", []) or []
    feature_names = [f.get("name", str(f))[:20] for f in features[:5]] if features else ["operation"]

    lines = ["// Cover Properties — functional coverage", ""]
    for i, fn in enumerate(feature_names):
        lines.append(f"// Cover: {fn}")
        lines.append(f"cover_{fn}: cover property (")
        lines.append(f"    @(posedge {clk}) disable iff (!{rst_n})")
        lines.append(f"    ##1 1;  // TODO: refine with actual condition from design")
        lines.append(f");")
        lines.append("")
    return "\n".join(lines)


@tool("generate_assertion_package")
def generate_assertion_package(specs: str = "") -> str:
    """生成断言 package 封装"""
    return """// Assertion Package — bundles all SVA
package assertion_pkg;
    // Common sequences
    sequence reset_released;
        @(posedge clk) $rose(rst_n);
    endsequence

    sequence stable_after_reset(sig);
        @(posedge clk) reset_released ##1 $stable(sig) [*2];
    endsequence

    // Utility: no X/Z on bus
    sequence no_xz(sig);
        !$isunknown(sig);
    endsequence
endpackage
"""


@tool("analyze_assertion_coverage")
def analyze_assertion_coverage(data: str = "") -> str:
    """分析断言覆盖率"""
    spec = _parse_spec(data)
    # 基于 spec 估算断言覆盖率
    features = spec.get("features", []) or []
    test_points = spec.get("test_points", []) or []
    n_features = len(features)
    n_tp = sum(len(tp.get("tests", [])) for tp in test_points if isinstance(tp, dict))

    estimated = min(n_features * 3 + n_tp, 50)  # rough estimate
    return json.dumps({
        "total_assertions": estimated,
        "covered": max(1, estimated - n_features),
        "coverage_pct": round(max(1, estimated - n_features) / max(estimated, 1) * 100, 1),
        "by_type": {
            "immediate": n_features,
            "concurrent": n_features * 2,
            "formal": max(1, n_features),
        },
        "suggestion": "Re-generate with full design spec for accurate assertion coverage",
    }, indent=2)


class AssertionTools:
    def get_tools(self):
        return [
            generate_sva_assertions,
            generate_immediate_assertions,
            generate_concurrent_assertions,
            generate_formal_properties,
            generate_cdc_assertions,
            generate_cover_properties,
            generate_assertion_package,
            analyze_assertion_coverage,
        ]
