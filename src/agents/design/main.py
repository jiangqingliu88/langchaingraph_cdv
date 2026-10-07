"""设计智能体 —— Spec → 架构 → RTL（真实工具链）"""
from typing import Dict, Any
import json
from pathlib import Path

from src.layers.l2_orchestration.agents.base import BaseAgent, AgentResult
from src.layers.l2_orchestration.agents.registry import register_agent
import structlog

logger = structlog.get_logger()


@register_agent("design")
class DesignAgent(BaseAgent):
    """设计智能体 = spec 分析 + 架构分解 + RTL 生成"""

    task_type = "code_generation"
    consumes = ["spec"]
    produces = "design_arch"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(
            role="design", display_name="设计智能体",
            description="Spec→架构→RTL 全链路", config=config or {})

    async def _setup(self):
        logger.info(f"{self.display_name} 初始化完成")

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return {"output": ""}

    async def execute_task(self, task: Dict[str, Any]) -> AgentResult:
        """spec 分析 → design_arch → rtl（真实工具链）"""
        from src.layers.l1_infrastructure.output_config import make_output_root
        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)

        spec_text = task.get("input", "")
        ctx = task.get("ctx", {})
        spec_data = ctx.get("spec", {}) if hasattr(ctx, 'get') else {}

        # ── 1. Spec 分析（真实工具 spec_tools）──
        spec = spec_data
        if not isinstance(spec, dict) or not spec.get("design_name"):
            try:
                from src.layers.l2_orchestration.communication.tool_hub import call_tool
                raw = call_tool("analyze_specification",
                                {"spec_text": spec_text or str(spec_data)})
                spec = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith('{') else {}
            except Exception as e:
                logger.warning(f"spec 分析失败: {e}")
                spec = {"design_name": "dut"}

        module_name = spec.get("design_name", "dut")
        if module_name.lower() in ("dut", "dut_top", ""):
            module_name = "dut"

        # ── 2. 架构拆 IP：从 spec features 拆解 IP 列表，注册进 IP 库 ──
        #     fix_agent=rtl（REFACTOR_RTL）→ 强制重新生成，绕过 IP 缓存（缓存的是功能错的 RTL）
        _params = task.get("params", {}) if isinstance(task.get("params"), dict) else {}
        _force_regen = _params.get("fix_agent") == "rtl"
        # 修复路径要能回答"我到底改了什么"—— 改前记指纹，改完比对
        _rtl_before = self._rtl_fingerprint(output_dir) if _force_regen else {}
        ips = self._decompose_ips(spec, module_name, force_regen=_force_regen)

        # ── 3. LLM 写手：只对新 IP（reused=False）生成 RTL，复用的直接带库 RTL ──
        rtl_dir = output_dir / "rtl"
        rtl_dir.mkdir(parents=True, exist_ok=True)
        # 每个 IP 的产出结局都要**记下来**，不能只留一行 warning。
        # 三条失败路径原先都是 `warning + continue` —— 全丢光时 `rtl/` 是空的，
        # 流程却照常往下跑，最后在编译期报一屏 `Module 'xxx' is not defined`
        #（实测：加了寄存器表之后 design 没产出任何 RTL，整轮就是这么塌的，
        #  而失败原因只留在日志里一行 warning）。**要能"兜住"它。**
        rtl_reused: List[str] = []
        rtl_discarded: List[Dict[str, str]] = []
        for ip in ips:
            if ip.get("reused"):
                rtl_reused.append(ip["ip_name"])
                continue  # 查库复用：RTL 已在 ip["rtl_code"]，不再 LLM 生成
            # **重试再丢**：LLM 产出残缺是随机事件（长文件被截断尤其常见），
            # 一次不成不代表这个 IP 写不出来。原先 `warning + continue` 一次就扔，
            # 全丢光 `rtl/` 就空了（实测：加了寄存器表之后整轮就是这么塌的）。
            # 重试**不改变"验不过就不收"**这条 —— 只是多给它两次机会；
            # 三次都不成，照旧丢弃并记明原因（由 RTL 门禁响亮收口）。
            _last_why = "未尝试"
            for _attempt in range(1, 4):
                try:
                    rtl = self._llm_write_ip(ip, spec)
                    # RTL 完整性校验：module + 端口闭合 + endmodule（LLM 可能截断/残缺）
                    if not self._is_valid_rtl(rtl):
                        _last_why = "RTL 残缺（缺端口闭合/endmodule）"
                        logger.warning(f"IP {ip['ip_name']} 第 {_attempt}/3 次 RTL 残缺，重试")
                        continue
                    # 铁律一：走 L1 基础设施做 vlog 编译校验（EDA 是唯一真理）
                    if not self._verify_ip_rtl(rtl_dir, ip["ip_name"], rtl):
                        _last_why = "vlog 编译失败"
                        logger.warning(f"IP {ip['ip_name']} 第 {_attempt}/3 次 vlog 不过，重试")
                        continue
                    from src.layers.l4_memory.ip_registry import IpRegistry
                    _reg = IpRegistry()
                    _reg.update_rtl(ip["ip_name"], rtl)
                    ip["rtl_code"] = rtl
                    _reg.close()
                    _last_why = ""
                    break
                except Exception as e:
                    _last_why = f"LLM 写手失败: {e}"
                    logger.warning(f"IP {ip['ip_name']} 第 {_attempt}/3 次写手异常: {e}")
            if not ip.get("rtl_code"):
                logger.warning(f"IP {ip['ip_name']} 三次都没产出可用 RTL（{_last_why}），丢弃")
                rtl_discarded.append({"ip": ip["ip_name"],
                                      "why": f"{_last_why}（已重试 3 次）"})

        # ── 4. 集成连线：各 IP RTL 集成为顶层 module ──
        rtl_files, top_used_fallback = self._integrate_top(ips, module_name, spec, rtl_dir)

        design_arch = {
            "module_name": module_name,
            "ips": ips,
            "function_hier": self._build_func_hier(spec),
            "registers": spec.get("registers", []),
            "interfaces": spec.get("interfaces", []),
            "signoff_checklist": [],
            # 说真话：LLM 顶层连线失败 → 回退确定性骨架（只有 clk/rst 直连，无真实互连逻辑）
            # audit 门禁 rtl_real 据此拒绝签核（见 audit agent gate）
            "rtl_placeholder": top_used_fallback,
            # ── RTL 产出的**实况**（不是日志里的一句话）──
            # `rtl_discarded` 非空 / `rtl_generated` 为空 = 这个设计**没有可验的 RTL**，
            # 闭环必须据此**响亮地停下**，不能拿一个空 `rtl/` 往下跑。
            "rtl_generated": [i["ip_name"] for i in ips if i.get("rtl_code")],
            "rtl_reused": rtl_reused,
            "rtl_discarded": rtl_discarded,
        }

        # V2 Knowledge Graph：设计时子图落库（跨 run 沉淀，供决策层语义溯源）
        try:
            from src.tools.spec_tools.verify_dsl import build_graph_from_spec
            from src.layers.l3_decision.knowledge.persistence import save_graph_to_db
            _kg = build_graph_from_spec(spec)
            await save_graph_to_db(_kg)
            logger.info(f"验证知识图已落库: nodes={len(_kg)}")
        except Exception as e:
            logger.warning(f"验证知识图落库失败: {e}")

        result = {
            "design_arch": design_arch,
            "rtl": {"module_name": module_name, "files": rtl_files,
                    "file_count": len(rtl_files)},
            "spec": spec,
        }
        score = min(50 + len(rtl_files) * 15 + len(spec.get("registers", [])) * 2, 90) \
            if rtl_files else 30
        result["score"] = score

        # ── 修复路径：**"没改动任何 RTL"要如实失败** ──
        # 实测：一轮 `design_fix` 报 PASS 90、只用了 9.5 秒，而 RTL 与改前逐字节
        # 相同（守卫那边的 `changed: []` 是准的）。文件写了、内容没变 —— 对"修 bug"
        # 等于什么都没做，却占掉了这一轮的修复额度，界面上还是一片绿。
        # 所以这一路自己也要能回答"我改了什么"；没改就说没改。
        if _force_regen:
            result["rtl_changed"] = self._rtl_diff(
                _rtl_before, self._rtl_fingerprint(output_dir))
            if not result["rtl_changed"]:
                logger.warning("设计修复没有产生任何 RTL 变化 —— 如实记失败，不当作修复成功")
                result["score"] = 20
                return AgentResult(success=False, data=result, error=(
                    "这次设计修复没有改动任何 RTL（产出与改动前一致）—— "
                    "要么 LLM 没改，要么改回去了"))
        return AgentResult(success=bool(rtl_files), data=result)

    @staticmethod
    def _rtl_fingerprint(output_dir: Path) -> dict:
        """`{文件名: sha256}` —— 修复路径用它回答"我到底改了什么"。"""
        import hashlib

        out = {}
        rtl_dir = Path(output_dir) / "rtl"
        if not rtl_dir.is_dir():
            return out
        for f in sorted(rtl_dir.rglob("*.sv")):
            out[str(f.relative_to(rtl_dir)).replace("\\", "/")] =                 hashlib.sha256(f.read_bytes()).hexdigest()
        return out

    @staticmethod
    def _rtl_diff(before: dict, after: dict) -> list:
        """内容变了的文件（含新增与删除）—— 与 `RefactorGuard.changed_files` 同口径。"""
        changed = [name for name, digest in after.items() if before.get(name) != digest]
        changed += [name for name in before if name not in after]
        return sorted(set(changed))

    # ═══════════════════════════════════════════════════════════
    # 架构拆 IP → LLM 写手 → 集成连线
    # ═══════════════════════════════════════════════════════════

    def _decompose_ips(self, spec: dict, module_name: str, force_regen: bool = False) -> list:
        """架构拆 IP：用搜索策略从 IP 库匹配（替代硬编码关键词映射）。

        每个 feature 文本通过 search_ip 匹配 IP 库（tags/desc 语义匹配），
        命中 generated 的直接复用 RTL，命中 planned 的走 LLM 写手生成。
        force_regen=True（fix_agent=rtl）时跳过复用，全部 LLM 重新生成。
        """
        from src.layers.l4_memory.ip_registry import IpRegistry
        ip_reg = IpRegistry()

        ips = []
        seen = set()
        features = spec.get("features", []) or []
        for f in features:
            fname = f.get("name", "") if isinstance(f, dict) else str(f)
            # 搜索 IP 库：按 feature 文本匹配最相似的 IP（tags/desc 语义匹配）
            matches = ip_reg.search_ip(fname, limit=1)
            if not matches:
                continue  # 库无匹配，跳过（该 feature 无对应 IP）
            matched = matches[0]
            generic_name = matched["ip_name"]
            category = matched["category"]
            if generic_name in seen:
                continue
            if matched["status"] == "generated" and matched["rtl_code"] and not force_regen:
                # 查库复用：直接用库里已有 RTL，不再 LLM 生成
                ip_reg.mark_reused(generic_name)
                ips.append({"ip_name": generic_name, "category": category,
                            "function_desc": fname,
                            "interface": matched["interface"],
                            "reused": True, "rtl_code": matched["rtl_code"]})
            else:
                # 新 IP：库里有 seed 预置的完整接口就用库的，否则从 spec 提取
                iface = matched["interface"] or self._extract_ip_interface(spec, category)
                ips.append({"ip_name": generic_name, "category": category,
                            "function_desc": fname, "interface": iface,
                            "reused": False})
            seen.add(generic_name)
        ip_reg.close()
        return ips

    @staticmethod
    def _extract_ip_interface(spec: dict, category: str) -> list:
        """从 spec interfaces 提取某类 IP 的相关信号（按 protocol 字段筛选）。"""
        interfaces = spec.get("interfaces", []) or []
        cat = category.lower()
        if cat in ("apb", "uart", "irq"):
            return [i for i in interfaces if cat in i.get("protocol", "").lower()]
        return []  # fifo 等内部信号，由 LLM 写手决定

    @staticmethod
    def _llm_write_ip(ip: dict, spec: dict) -> str:
        """LLM 写手：根据 IP 功能描述 + 接口，生成真实 RTL 逻辑。

        这是"LLM 做完形填空"的落点——小 IP 的逻辑简单（状态机/寄存器），
        LLM 容易生成正确；大模块拆成小 IP 后，每个 IP 的 RTL 是真实逻辑而非占位。
        """
        clk_rst = [i for i in spec.get("interfaces", [])
                   if i.get("protocol", "").lower() in ("clock", "reset")]
        prompt = f"""你是 IC 设计工程师，精通 SystemVerilog RTL 设计。

请为以下 IP 生成完整的 RTL module：

IP 名: {ip['ip_name']}
类别: {ip['category']}
功能: {ip['function_desc']}

时钟/复位信号:
{json.dumps(clk_rst, ensure_ascii=False)}

该 IP 的接口信号:
{json.dumps(ip.get('interface', []), ensure_ascii=False)}

要求：
1. 生成完整的 module，端口 = 时钟/复位 + 接口信号
2. 用 always_ff 写真实的功能逻辑（状态机/寄存器/组合逻辑，不是占位）
3. 每个 reg 变量只能在一个 always_ff 块里赋值（禁止多驱动），组合逻辑用 assign 或 always_comb
4. 每个 always_ff 块的敏感列表统一用 @(posedge clk or negedge rst_n)
5. 只输出 SystemVerilog 代码，无 markdown 代码块、无解释
"""
        try:
            from src.tools.lib.llm_custom_logic import _call_llm_raw
            return _call_llm_raw(prompt, "", "")
        except Exception:
            return ""

    @staticmethod
    def _is_valid_rtl(rtl: str) -> bool:
        """RTL 完整性校验：module 声明 + 端口闭合 `);` + endmodule。

        LLM 生成的 RTL 可能截断（如端口列表没闭合就写 endmodule），
        这种残缺 RTL 会导致 vlog 编译错误，必须丢弃。
        """
        import re
        if not rtl:
            return False
        if "module" not in rtl or "endmodule" not in rtl:
            return False
        # 端口闭合：module X ( ... );  必须有 ");"
        m = re.search(r'module\s+\w+\s*\(([^)]*)\)\s*;', rtl, re.DOTALL)
        return m is not None

    @staticmethod
    def _verify_ip_rtl(output_dir: Path, ip_name: str, rtl_code: str) -> bool:
        """铁律一：用 L1 基础设施（InfrastructureManager.compile → EdaBackend）做 vlog 编译校验。

        LLM 生成的 RTL 语法对但可能有语义错误（多驱动/端口悬空），
        vlog 编译返回 0/1，失败则丢弃（回退）。这是"EDA 是唯一真理"的落点。
        """
        import tempfile
        from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
        try:
            # 落盘 IP RTL 到临时目录 + 生成 filelist
            tmp_dir = Path(tempfile.mkdtemp(prefix="ip_verify_"))
            (tmp_dir / f"{ip_name}.sv").write_text(rtl_code, encoding="utf-8")
            fl = tmp_dir / "filelist.f"
            fl.write_text(str(tmp_dir / f"{ip_name}.sv"), encoding="utf-8")
            # L1 编译校验（vlog）
            infra = InfrastructureManager(tmp_dir)
            result = infra.compile(str(fl), coverage=False)
            return result.get("status") == "PASS" and result.get("errors", 0) == 0
        except Exception as e:
            logger.warning(f"IP {ip_name} L1 编译校验失败: {e}")
            return False

    def _integrate_top(self, ips: list, module_name: str, spec: dict, rtl_dir: Path) -> tuple:
        """集成连线：各 IP 的 RTL 落盘 + LLM 生成顶层 module（完整连线）。

        返回 (files, top_used_fallback)：LLM 顶层生成失败回退确定性骨架时
        top_used_fallback=True（骨架只有 clk/rst 直连，无真实互连 → 标记占位）。
        """
        from src.layers.l4_memory.ip_registry import IpRegistry
        ip_reg = IpRegistry()

        files = []
        for ip in ips:
            rtl_code = ip.get("rtl_code")  # 优先用 ip 里缓存的（复用/刚生成）
            if not rtl_code:
                rtl = ip_reg.get_ip(ip["ip_name"])
                rtl_code = rtl["rtl_code"] if rtl else ""
            if rtl_code:
                fpath = rtl_dir / f"{ip['ip_name']}.sv"
                fpath.write_text(rtl_code, encoding="utf-8")
                files.append(str(fpath))

        # 顶层 module：优先 LLM 生成（理解各 IP 接口做完整连线），失败回退规则骨架
        top_used_fallback = False
        if files:
            top = self._llm_write_top(module_name, ips, spec)
            if not top:
                top = self._gen_top_module(module_name, ips, spec)
                top_used_fallback = True
                logger.warning(f"顶层 {module_name} 回退确定性骨架（LLM 连线失败，仅 clk/rst 直连，无真实互连逻辑）")
            top_path = rtl_dir / f"{module_name}.sv"
            top_path.write_text(top, encoding="utf-8")
            files.append(str(top_path))

        ip_reg.close()
        return files, top_used_fallback

    @staticmethod
    def _llm_write_top(module_name: str, ips: list, spec: dict) -> str:
        """LLM 集成：根据各 IP 的接口，生成顶层 module（实例化 + 完整连线）。"""
        from src.layers.l4_memory.ip_registry import IpRegistry
        reg = IpRegistry()
        ip_rtls = []
        for ip in ips:
            rtl = reg.get_ip(ip["ip_name"])
            if rtl and rtl["rtl_code"]:
                ip_rtls.append({"ip_name": ip["ip_name"], "rtl": rtl["rtl_code"]})
        reg.close()

        if not ip_rtls:
            return ""

        prompt = f"""你是 IC 集成工程师，精通 SystemVerilog。

请把以下 IP 集成成顶层 module。

顶层模块名: {module_name}
顶层端口（来自 spec，这些是 DUT 对外接口）:
{json.dumps(spec.get('interfaces', []), ensure_ascii=False)}

各 IP 的 RTL（注意各 IP 的端口名，连线时用端口名匹配）:
{json.dumps([{'ip_name': r['ip_name'], 'rtl': r['rtl']} for r in ip_rtls], ensure_ascii=False)}

要求：
1. 顶层 module 端口 = spec 接口（时钟/复位 + 顶层接口）
2. 实例化所有 IP，按端口名连线：顶层端口直连同名 IP 端口，跨 IP 的信号用内部 wire 声明
3. 顶层输出（如 tx/irq/prdata）必须由某个 IP 的输出驱动，不能悬空
4. 只输出 SystemVerilog 代码，无 markdown 代码块、无解释
"""
        try:
            from src.tools.lib.llm_custom_logic import _call_llm_raw
            return _call_llm_raw(prompt, "", "")
        except Exception:
            return ""

    @staticmethod
    def _gen_top_module(module_name: str, ips: list, spec: dict) -> str:
        """生成顶层 module：端口 = spec 接口，实例化各 IP（时钟/复位直连）。"""
        interfaces = spec.get("interfaces", []) or []
        # 端口声明
        ports = DesignAgent._gen_ports(interfaces)
        # 识别时钟/复位
        clk = rst_n = None
        for itf in interfaces:
            proto = itf.get("protocol", "").lower()
            nm = itf.get("name", "").split("[")[0]
            if proto in ("clock", "clk"):
                clk = nm
            elif proto in ("reset", "rst"):
                rst_n = nm

        lines = [f"module {module_name} ("]
        lines.append(ports)
        lines.append(");")
        # 实例化各 IP（时钟/复位直连，接口信号由 LLM 写手生成的 IP 端口决定）
        for ip in ips:
            ip_inst = ip["ip_name"].replace(module_name + "_", "")
            lines.append("")
            lines.append(f"  {ip['ip_name']} u_{ip_inst} (")
            # 时钟/复位直连
            conns = []
            if clk:
                conns.append(f"    .{clk}({clk})")
            if rst_n:
                conns.append(f"    .{rst_n}({rst_n})")
            lines.append(",\n".join(conns) if conns else "    // 接口连线待 LLM 写手生成后补齐")
            lines.append("  );")
        lines.append("")
        lines.append("endmodule")
        return "\n".join(lines) + "\n"

    def _build_func_hier(self, spec: dict) -> dict:
        """从 spec features 构建功能层次。"""
        features = spec.get("features", [])
        children = []
        for f in features:
            if isinstance(f, dict):
                name = f.get("name", "feature")
            else:
                name = str(f)
            # 简化：每个 feature 是一个叶子操作
            children.append({"name": name.replace(" ", "_").lower()[:30]})
        if not children:
            children = [{"name": "core_op"}]
        return {"name": spec.get("design_name", "dut"), "children": children}

    def _generate_rtl(self, design_arch: dict, rtl_dir: Path) -> list:
        """从 spec 接口表生成 RTL：端口对齐 + 确定性功能骨架。

        不再写死 ALU——端口从 spec 的 interfaces 字段生成（与 UVM bench top 对齐），
        功能逻辑先给确定性骨架（输出信号在时钟沿依赖输入，制造真实接口信号 toggle），
        真实功能逻辑（APB 读写/UART 状态机）由 LLM 在后续迭代填充。
        """
        module_name = design_arch["module_name"]
        interfaces = design_arch.get("interfaces", [])

        if not interfaces:
            # 无接口表：回退到旧 ALU 骨架（保持向后兼容）
            return self._generate_rtl_legacy(design_arch, rtl_dir)

        ports = self._gen_ports(interfaces)
        logic = self._gen_logic_skeleton(module_name, interfaces)

        rtl_code = f"module {module_name} (\n{ports}\n);\n\n{logic}\nendmodule\n"

        fpath = rtl_dir / f"{module_name}.sv"
        fpath.write_text(rtl_code, encoding="utf-8")
        return [str(fpath)]

    @staticmethod
    def _gen_ports(interfaces: list) -> str:
        """从 spec 接口表生成 module 端口声明（paddr[7:0] → [7:0] paddr）。"""
        dir_map = {"INPUT": "input", "OUTPUT": "output", "INOUT": "inout"}
        ports = []
        for itf in interfaces:
            name = itf.get("name", "")
            width = int(itf.get("data_width", 1))
            direction = itf.get("direction", "INPUT").upper()
            base = name.split("[")[0] if "[" in name else name  # paddr[7:0] → paddr
            decl = f"[{width - 1}:0] {base}" if width > 1 else base
            ports.append(f"  {dir_map.get(direction, 'input')}  logic {decl}")
        return ",\n".join(ports)

    @staticmethod
    def _gen_logic_skeleton(module_name: str, interfaces: list) -> str:
        """确定性功能骨架：识别时钟/复位，输出信号在时钟沿依赖输入（制造 toggle）。

        这是"骨架"——端口对齐 + 输出有时序驱动 + 通过 vlog 编译。
        真实功能逻辑（APB 读写/UART 状态机）由 LLM 后续迭代填充。
        """
        # 识别时钟 / 复位（按 protocol 字段）
        clk, rst_n = "clk", "rst_n"
        rst_active_low = False
        for itf in interfaces:
            proto = itf.get("protocol", "").lower()
            nm = itf.get("name", "").split("[")[0]
            if proto in ("clock", "clk"):
                clk = nm
            elif proto in ("reset", "rst"):
                rst_n = nm
                rst_active_low = "n" in nm.lower()

        inputs = [i for i in interfaces
                  if i.get("direction", "").upper() == "INPUT"
                  and i.get("protocol", "").lower() not in ("clock", "reset")]
        outputs = [i for i in interfaces if i.get("direction", "").upper() == "OUTPUT"]
        src_list = [i.get("name", "").split("[")[0] for i in inputs]

        edge = f"posedge {clk}" + (f" or negedge {rst_n}" if rst_active_low else f" or posedge {rst_n}")
        cond = f"!{rst_n}" if rst_active_low else rst_n

        lines = [f"  // 确定性功能骨架：端口对齐 + 输出时序驱动（真实逻辑待 LLM 填充）"]
        lines.append(f"  always_ff @({edge}) begin")
        lines.append(f"    if ({cond}) begin")
        for o in outputs:
            nm = o.get("name", "").split("[")[0]
            w = int(o.get("data_width", 1))
            lines.append(f"      {nm} <= {w}'h0;")
        lines.append("    end else begin")
        if src_list:
            for idx, o in enumerate(outputs):
                nm = o.get("name", "").split("[")[0]
                src = src_list[idx % len(src_list)]
                lines.append(f"      {nm} <= {src};  // 占位：依赖输入制造 toggle")
        else:
            for o in outputs:
                nm = o.get("name", "").split("[")[0]
                lines.append(f"      {nm} <= ~{nm};  // 无输入，自翻转制造 toggle")
        lines.append("    end")
        lines.append("  end")
        return "\n".join(lines)

    def _generate_rtl_legacy(self, design_arch: dict, rtl_dir: Path) -> list:
        """旧 ALU 骨架（无接口表时的回退）。"""
        module_name = design_arch["module_name"]
        func_hier = design_arch.get("function_hier", {})
        ops = self._extract_ops(func_hier)

        rtl_code = (
            f"module {module_name} (\n"
            f"  input  logic clk,\n"
            f"  input  logic rst_n,\n"
            f"  input  logic [31:0] opcode,\n"
            f"  input  logic [31:0] operand_a,\n"
            f"  input  logic [31:0] operand_b,\n"
            f"  output logic [31:0] result\n"
            f");\n\n"
            f"  always_ff @(posedge clk or negedge rst_n) begin\n"
            f"    if (!rst_n) result <= '0;\n"
            f"    else begin\n"
            f"      case (opcode)\n"
        )
        for i, op in enumerate(ops):
            rtl_code += f"        {i}: result <= operand_a + operand_b;  // {op}\n"
        rtl_code += (
            f"        default: result <= '0;\n"
            f"      endcase\n"
            f"    end\n"
            f"  end\n"
            f"endmodule\n"
        )

        fpath = rtl_dir / f"{module_name}.sv"
        fpath.write_text(rtl_code, encoding="utf-8")
        return [str(fpath)]

    def _extract_ops(self, func_hier: dict) -> list:
        ops = []
        for child in func_hier.get("children", []):
            if isinstance(child, dict) and child.get("name"):
                ops.append(child["name"])
        return ops or ["op"]
