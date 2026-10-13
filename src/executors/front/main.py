"""前置分析智能体 —— 输入（RTL / spec / doc）→ 后面所有人吃的结构化设计信息。

## 为什么单开一个角色

这件事一直有人干（`tool_find_spec_yaml` 解 RTL 端口、`analyze_specification` 抽
spec），但它是**被调的工具**：产出的东西**没有 phase 记录**，出了事查不到是哪一步
产的。抬成角色之后，"这次的设计信息从哪来、是怎么解出来的"进证据链。

## 它到底产什么

**产结构化设计信息（`spec` / `design_arch`），不直接产那三个 yaml。**
三个 yaml（环境 / 用例建模 / 模型）是**下游**从它产的东西生成的 ——
顺序上必须是这样：`bench.yaml` 要知道 DUT 的顶层与端口，那是 design 之后才定的。

  · 环境 yaml     ← 下游 `tool_find_spec_yaml`（吃 spec/design_arch）
  · 用例建模 yaml  ← 下游同上（tags/build/run_cmd 由 agents + 用例库拼）
  · 模型 yaml     ← 下游 `ModelRegistry.to_util_component()`（TLM 1.0 装配单）

所以 front 的 **契约**是那三个 yaml 必须有源可溯 —— 而它的**产出**是它们的输入。

## 输入三选一（互斥规则与 CLI 一致）

  RTL 有、spec 无  → 读 RTL：顶层 module 名 → design_name；端口表 → interfaces
  spec 有、RTL 无  → 读 spec：`analyze_specification` 抽 design_name/interfaces/registers
  doc 可作补充     → 给语义（它不给结构）
  两者都无         → **响亮失败**（没有输入就别往下走）

**不从 RTL 猜寄存器**：地址译码有 `case (paddr[1:0])` 直连、`paddr[7:2]==0` 区间
判定、`regs[paddr]` 数组索引、DLAB 那种地址重载 —— 猜错就是"spec 说 16 个、
RTL 里 4 个"（实测亲手犯过）。推不出就**如实留空**。
"""
from typing import Any, Dict
from pathlib import Path

import structlog

from src.layers.l2_orchestration.executors.base import ExecutorResult, BaseExecutor
from src.layers.l2_orchestration.executors.registry import register_executor

logger = structlog.get_logger()


@register_executor("front")
class FrontExecutor(BaseExecutor):
    """前置分析 = 读输入 + 解出结构化设计信息。"""

    task_type = "code_generation"
    consumes = []
    produces = "spec"

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(role="front", display_name="前置分析智能体",
                         description="RTL / spec / doc → 结构化设计信息（喂下游三个 yaml）",
                         config=config or {})

    async def _setup(self):
        """子类特定初始化 —— front 是**纯分析**角色：不接 LLM、不挂工具，
        全部工作由 `execute_task` 调确定性工具/分析完成（见模块 docstring）。

        必须实现：`BaseExecutor` 把它声明成 `@abstractmethod`，不实现的话
        `FrontExecutor()` **实例化即 TypeError** —— 而 `execution.py` 的实例表
        是在导入期构造的，一个抽象方法没实现会把整个运行服务带崩
        （实测：连带 84 个测试失败）。
        """
        self.ctx_reg = getattr(self, "ctx_reg", None)

    async def _get_prompt_template(self):
        return None

    async def _get_tools(self):
        return []

    async def _execute(self, input_text: str):
        return input_text

    # ── 主入口 ──────────────────────────────────────────────

    async def execute_task(self, task: Dict[str, Any]) -> ExecutorResult:
        from src.layers.l1_infrastructure.output_config import make_output_root

        output_dir = Path(make_output_root(task.get("output_dir") or None))
        task["output_dir"] = str(output_dir)
        spec_text = str(task.get("input") or "")

        rtl_dir = output_dir / "rtl"
        rtl_files = sorted(rtl_dir.glob("*.sv")) if rtl_dir.is_dir() else []

        if not rtl_files and not spec_text.strip():
            # **没有输入就别往下走** —— 静默给一个 `design_name: dut` 会让后面
            # 整条链在一个不存在的设计上跑，最后报一堆看不懂的错。
            return ExecutorResult(
                success=False,
                data={"score": 0},
                error="前置分析失败：既没有 RTL（<run>/rtl/ 为空）也没有 spec —— "
                      "没有输入。请给 spec，或用 `--rtl <目录>` 给 RTL。",
                metadata={"phase": "front", "no_input": True})

        info: Dict[str, Any] = {}
        sources = []

        # ① RTL：顶层 module 名 + 端口表（**调工具**，确定性）
        if rtl_files:
            try:
                from src.tools.uvm_tools.tool_find_spec_yaml.main import _parse_rtl_module
                rtl = _parse_rtl_module(rtl_dir, "") or {}
                info["design_name"] = rtl.get("module_name") or "dut"
                info["interfaces"] = [
                    {"name": p.get("name", ""),
                     "direction": p.get("direction", "input"),
                     "data_width": p.get("width", 1)}
                    for p in (rtl.get("ports") or [])]
                # 寄存器**不猜**（见模块 docstring）
                info["registers"] = []
                info["_source"] = "rtl_analysis"
                info["_note"] = ("规格由 RTL 分析生成（端口来自 module 声明）；"
                                 "registers 未从 RTL 推断 —— 如需寄存器用例请补 spec")
                sources.append(f"rtl({len(rtl_files)} files)")
                logger.info(f"front：RTL 分析 design_name={info['design_name']} "
                            f"ports={len(info['interfaces'])}（registers 未推断）")
            except Exception as e:                     # noqa: BLE001 分析失败不该炸
                logger.warning(f"front：RTL 分析失败: {e}")

        # ② spec：抽 design_name/interfaces/registers/features（确定性）
        if spec_text.strip():
            try:
                import json as _json
                from src.tools.spec_tools.main import analyze_specification
                raw = analyze_specification(spec_text)
                doc = _json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("{") else {}
                if isinstance(doc, dict):
                    # RTL 已经解出端口时**以 RTL 为准**（它是实现，spec 是意图）；
                    # 只补 spec 有而 RTL 给不出的字段（registers/features）。
                    for k in ("design_name", "registers", "features", "overview"):
                        if doc.get(k) and not info.get(k):
                            info[k] = doc[k]
                    info.setdefault("interfaces", doc.get("interfaces", []))
                    sources.append("spec")
                    logger.info(f"front：spec 分析 design_name={info.get('design_name')} "
                                f"registers={len(info.get('registers') or [])}")
            except Exception as e:                     # noqa: BLE001
                logger.warning(f"front：spec 分析失败: {e}")

        if not info.get("design_name"):
            return ExecutorResult(success=False, data={"score": 0},
                               error="前置分析失败：没能解出 design_name（RTL 里没有 "
                                     "module 声明，spec 里也没有 design_name）")

        arch = {"module_name": info["design_name"],
                "interfaces": info.get("interfaces", []),
                "registers": info.get("registers", []),
                "function_hier": {"children": []}}

        # 用例库登记：design 之后 spec 就绪 —— 这里更早，用例库早一步可查
        #
        # 登记时把**这一轮的 RTL 版本**一起写上：用例是有版本的（RTL 换了版，
        # 旧用例是在哪版上定的就答不上来了）。版本走 `ensure_run_rtl_version`
        # 这一个入口（与 debug / finalize 共用），拿不到就是 None，不编一个 0。
        rtl_version_no = None
        try:
            from src.layers.l4_memory.lineage import run_rtl_version_no
            rtl_version_no = run_rtl_version_no(output_dir,
                                                module=info["design_name"])
        except Exception as e:                         # noqa: BLE001 血缘不该阻断分解
            logger.warning(f"血缘：这一轮的 RTL 版本取不到（用例将不带版本）: {e}")
        try:
            if self.ctx_reg is not None:
                self.ctx_reg.register_from_spec(info, info["design_name"],
                                                rtl_version_no=rtl_version_no)
        except Exception:                              # noqa: BLE001 登记失败不阻断
            pass

        # ── casemodel：从 spec 出 case 属性模型 ──
        # 这是"测试点分解 + 用例建模"的入口。草稿是**确定性**的（见 `_draft_casemodel`），
        # 但**必须过 `run_validate`** —— 过不了就不写盘：一份校验不过的模型拿给下游，
        # 只会把错误推到更远的地方（这一整个会话反复吃的就是这个亏）。
        casemodel_path = ""
        try:
            import yaml as _yaml
            from src.tools.casemodel_tools.api import (blocking_issues,
                                                       run_validate, run_uvm_tests)

            model = self._draft_casemodel(info)
            if model:
                text = _yaml.safe_dump(model, allow_unicode=True, sort_keys=False)
                errs = [i for i in (run_validate(text).get("issues") or [])
                        if i.get("severity") == "error"]
                # schema 绿了不等于模型立得住：维度 id / 字段名这类**全局坐标**
                # 撞车 schema 看不见，要到下游才炸（重复测试点 → 同一个 SV 类名
                # → Typedef 重定义 → 覆盖率归零）。这道闸只拦「身份类」的错，
                # 不拦 `case_without_check` 那种已知且合理的（见 blocking_issues）。
                if not errs:
                    errs = blocking_issues(text)
                if errs:
                    # 草稿自己没写对 —— 如实记下来，**不写盘**（写下去就是给下游埋雷）
                    logger.warning(f"front：casemodel 草稿没过校验（{len(errs)} 条），不写盘；"
                                   f"首条：{str(errs[0])[:120]}")
                else:
                    # 落点走 `layout.casemodel_path` —— **一处契约**。
                    # 别写进 `inputs/yaml/uvm/`：那是 find_spec_yaml 的私有目录，
                    # 它每次跑先清空 `*.yaml`，会把这里刚写的东西删掉，而接下来
                    # 要读它的正是同一个工具（实测：env/tests 里生成不出属性 test）。
                    from src.layers.l1_infrastructure.layout import casemodel_path as _cm_path
                    cm_file = _cm_path(output_dir)
                    cm_file.parent.mkdir(parents=True, exist_ok=True)
                    casemodel_path = str(cm_file)
                    cm_file.write_text(text, encoding="utf-8")
                    _t = run_uvm_tests(text, max_tests=200)
                    # ⚠️ `casemodel_path` 是 **str**（上面 `str(...)` 转过了）——
                    # 对它调 `.name` 会 `'str' object has no attribute 'name'`，
                    # 而外面那个宽 `except` 会把它吞成"生成失败"。**实测踩过**：
                    # 文件明明写成功了，日志却报失败，白查了一轮。
                    logger.info(f"front：casemodel 已写出 {Path(casemodel_path).name}"
                                f"（维度 {len(model.get('dimensions') or [])}、"
                                f"专题 {len(model.get('themes') or [])}、"
                                f"可生成测试 {_t.get('count')} 条）")
                    # ── 落用例库：属性取值点 → 用例 ──
                    # 用例库的 `constraints` 列**以前永远是空的**（全仓库没有一处传过
                    # 它），于是"建模声明了 N 个覆盖点"和"regression.yaml 里跑着 M 条"
                    # 可以同时成立而没人发现。这道桥把一个取值点落成一条用例，粒度与
                    # 上面 `run_uvm_tests` 的条数 **1:1** —— 对不上就说明漏了。
                    # 复用 `ctx_reg`（同一个库句柄），不另开一个连接指向同一个文件。
                    try:
                        from src.tools.casemodel_tools.registry_bridge import register_cases
                        _r = register_cases(text, info.get("design_name", "dut"),
                                            registry=self.ctx_reg, max_cases=200,
                                            rtl_version_no=rtl_version_no)
                        logger.info(f"front：用例库登记 {_r.get('registered', 0)} 条"
                                    f"（覆盖点共 {_r.get('total_before_cap', 0)}、"
                                    f"截断丢弃 {_r.get('dropped', 0)}）")
                        for _n in (_r.get("notes") or [])[:2]:
                            logger.warning(f"front：{_n}")
                    except Exception as e:             # noqa: BLE001 登记失败不阻断
                        logger.warning(f"front：用例库登记失败（建模产物不受影响）: {e}")
        except Exception as e:                         # noqa: BLE001 建模失败不该拖垮入口
            logger.warning(f"front：casemodel 生成失败（不影响后面的链路）: {e}")

        return ExecutorResult(
            success=True,
            data={"spec": info, "design_arch": arch, "score": 90,
                  "casemodel_path": casemodel_path,
                  "sources": sources,
                  "front": {"sources": sources,
                            "design_name": info["design_name"],
                            "ports": len(info.get("interfaces", [])),
                            "registers": len(info.get("registers") or []),
                            "register_source": info.get("_source", "")}},
            metadata={"phase": "front"})

    #: 用例库句柄，由外部（init 节点）注入；没有就跳过登记
    ctx_reg = None

    # ── casemodel（测试点分解 + 用例建模）──
    #
    # **为什么要 front 产它**：`casemodel_tools` 是一套完整的建模子系统
    # （OrgTree 层级分解 + 专题 + 维度正交组合 + 五种生成方法），
    # 但它是**纯工具、零 LLM** —— "从 spec 建模型"这一步本来就该由 LLM 干，
    # 工具只做校验和缺口分析（`run_validate` / `run_gaps`）。
    # 而 front 是链路的入口、手里正好有 spec，所以由它落这一笔。
    #
    # **先出确定性草稿**：把 spec 的 features/registers/interfaces 摆成功能组织树，
    # 配上标准维度与专题（专题的 priority 正好对上分级回归的 p0/p1/p2/p3）。
    # LLM 精修是后续增量 —— 但**草稿先要过 `run_validate`**，过不了就不写盘。

    @staticmethod
    def _draft_casemodel(spec: Dict[str, Any]) -> Dict[str, Any]:
        """spec → casemodel 模型草稿（确定性，不猜语义）。"""
        name = spec.get("design_name", "dut")
        # 功能组织树：spec 的 features 是**功能主体**；没有 features 就退到寄存器/接口。
        subs = []
        for i, f in enumerate(spec.get("features") or [], 1):
            fn = f if isinstance(f, str) else (f or {}).get("name", "")
            if fn:
                subs.append({"id": f"OBJ-{i:02d}", "name": str(fn),
                             "code": f"F{i:02d}"})
        if not subs:
            for i, f in enumerate(spec.get("registers") or [], 1):
                rn = (f or {}).get("name", "")
                if rn:
                    subs.append({"id": f"OBJ-{i:02d}", "name": str(rn),
                                 "code": f"R{i:02d}"})
        if not subs:
            subs = [{"id": "OBJ-01", "name": name, "code": "DUT"}]

        # 维度：从 spec 的接口表取**真的信号**（不编），只有能落成维度的才收
        #
        # **按 id 收，不按接口条数收。** 一份 spec 里 `pwdata` 与 `prdata` 会双双
        # 落进下面同一个分支 —— 直接 append 就得到**两个 `D_DATA`**。维度 id 是
        # 全局坐标（`build_dimension` 拿它当 key），两个同 id 的维度会让下游按
        # `(dimension, value)` 展开出**重复测试点**，再撞成**同一个 SV 类名**
        # （`attr_class_slug` 只看 dimension + value）—— 编译期 Typedef 重定义，
        # work 库空掉、覆盖率归零。实测就是这么炸的。
        #
        # 同 id 撞车时**激励胜过响应**：`wdata` > `rdata`。测试点扫的是能驱动的
        # 那一路取值，读数据是响应，不是这一维该扫的东西。
        dims_by_id: Dict[str, Dict[str, Any]] = {}
        _rank_of = {"wdata": 2, "rdata": 1}      # 只有 D_DATA 有第二来源
        _chosen_rank: Dict[str, int] = {}

        def _put(dim: Dict[str, Any], source: str = "") -> None:
            rid = dim["id"]
            rank = _rank_of.get(source, 1)
            if _chosen_rank.get(rid, -1) >= rank:
                return                            # 已有同级或更优的来源，不覆盖
            dims_by_id[rid] = dim
            _chosen_rank[rid] = rank

        addr_w, data_w = 8, 8
        for it in (spec.get("interfaces") or []):
            if not isinstance(it, dict):
                continue
            n = str(it.get("name", "")).split("[")[0].lower()
            w = int(it.get("data_width", 1) or 1)
            if "addr" in n:
                addr_w = w
                _put({"id": "D_ADDR", "name": "地址",
                      "fields": [{"name": n, "type": "range", "min": 0,
                                  "max": (1 << w) - 1,
                                  "boundary": ["0", "3", "4",
                                               str((1 << w) - 1)]}]})
            elif "wdata" in n or "rdata" in n:
                data_w = max(data_w, w)
                _put({"id": "D_DATA", "name": "写数据",
                      "fields": [{"name": n, "type": "range", "min": 0,
                                  "max": (1 << w) - 1,
                                  "boundary": ["0", str((1 << w) - 1)]}]},
                     source="wdata" if "wdata" in n else "rdata")
            elif n in ("pwrite", "wr", "we"):
                _put({"id": "D_DIR", "name": "读写方向",
                      "fields": [{"name": n, "type": "enum",
                                  "values": [0, 1]}]})
        dims = list(dims_by_id.values())           # dict 保序 → 维持首次出现的顺序
        if not dims:
            # 一个维度都没有 → 模型立不起来（`dimensions` 是 schema 唯一的 required）
            return {}

        # 专题：priority 用的是**分级回归那五个词**，不是 P0/P1/P2 —— 直接对上
        themes = [{"id": "TH-P0", "name": "功能", "priority": "P0",
                   "applies_to": [s["name"] for s in subs],
                   # themes.dimensions 收的是**维度 id**，不是维度对象
                   "dimensions": [d["id"] for d in dims]}]
        if len(dims) > 1:
            themes.append({"id": "TH-P2", "name": "压力", "priority": "P2",
                           "applies_to": [subs[0]["name"]],
                           "dimensions": [dims[0]["id"]]})
        themes.append({"id": "TH-RND", "name": "随机", "priority": "P3",
                       "applies_to": ["*"]})

        return {"version": "1", "object": name, "object_cn": name,
                # object_code 有 pattern 约束（字母数字，**不许下划线**）—— "APB_UART" 会报
                # invalid_pattern。去掉非字母数字再截断。
                "object_code": "".join(ch for ch in name.upper()
                                       if ch.isalnum())[:12],
                "description": f"{name} 的 case 属性模型（front 自动草稿）",
                "sub_objects": subs, "dimensions": dims, "themes": themes}
