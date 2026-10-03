"""casemodel 工具的两个注册面：声明式 ToolRegistry 与 ToolHub 的 ITool。

    · `ensure_casemodel_tool_registry()`  —— 声明式 ToolRegistry
      给 src/layers/l2_orchestration/agents/agent_tools.py 汇总注册，
      BaseAgent 据此 wrap 工具调用并校验输出。与
      uvm_tools.agent_tools.ensure_uvm_tool_registry 同构。

    · `build_casemodel_tools()` / `register_casemodel_tools(hub)` —— ITool
      带 manifest / 风险等级 / 审计追踪，可被 hub.get_llm_tools 发现。

两个面与 LangChain 面共用 `tool_specs()` 与 `casemodel_tools.api` 的实现，
所以三面不会各给一个答案（有测试固定）。

工具名用下划线而不是 ToolHub 注释里建议的 `a.b` 点号命名空间：
点号会被原样带进 OpenAI function-calling 的 function.name，而那是非法字符。
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional, Tuple

from src.tools.casemodel_tools.api import (TOOL_GAPS, TOOL_GENERATE, TOOL_NAMES,
                                           TOOL_VALIDATE, RUNNERS)

__version__ = "2.0.0"

TAGS = ["casemodel", "testplan", "orgtree", "themes", "coverage"]
CATEGORY = "coverage"          # 归在 coverage 类：它量的是「验证得全不全」

_YAML_TEXT = {"type": "string", "description": "case 模型 YAML 全文"}
_MAX_CASES = {"type": "integer",
              "description": "生成上限，覆盖模型里的 generation.max_cases"}
_SEED = {"type": "integer",
         "description": "随机种子，覆盖 generation.seed；同 seed 结果一致"}
_CASES_TEXT = {"type": "string",
               "description": "外部真实 case 列表（YAML 全文），"
                              "给出时追加「模型 vs 实现」反向核对"}


def tool_specs() -> List[Tuple[str, str, Dict[str, Any], str]]:
    """(name, description, input_schema, risk_level) —— 三面共用的唯一来源。

    risk_level 一律 safe：三个工具都是纯计算，不写盘、不起子进程。
    """
    return [
        (TOOL_VALIDATE,
         "按 JSON Schema 校验 case 属性模型 YAML 的语法/类型/必填/取值表形状。"
         f"只回答「文档写对了吗」；引用是否存在、层级是否错位请用 {TOOL_GAPS}。",
         {"type": "object", "properties": {"yaml_text": _YAML_TEXT},
          "required": ["yaml_text"]},
         "safe"),
        (TOOL_GAPS,
         "对 case 属性模型做全量完备性分析：功能组织树（叶子覆盖、代号唯一）、"
         "专题（P0/P1/P2 优先级、目标、重叠、范围）、层级正交性、维度交叉矩阵、"
         "字段取值覆盖、环境指纹与检查项。"
         "可选 cases_text 给出真实 case 列表，追加「模型落后于实现 / "
         "实现落后于模型 / 重复 / 缺指纹」四个方向的反向核对。",
         {"type": "object",
          "properties": {"yaml_text": _YAML_TEXT, "max_cases": _MAX_CASES,
                         "cases_text": _CASES_TEXT},
          "required": ["yaml_text"]},
         "safe"),
        (TOOL_GENERATE,
         "按属性组合生成 case 属性表：专题选目标节点与维度集合 → 取字段取值 → "
         "选方法 → 计算组合 → 输出属性表。case_id 形如 "
         "TC-<对象>-<节点>-<方法>-<NN>，每条含 theme / priority / tree_path / "
         "fields / checks / environment（文档十六节最小字段集）。",
         {"type": "object",
          "properties": {"yaml_text": _YAML_TEXT, "max_cases": _MAX_CASES,
                         "seed": _SEED},
          "required": ["yaml_text"]},
         "safe"),
    ]


# ════════════════════════════════════════════════════════════
# 1) 声明式 ToolRegistry
# ════════════════════════════════════════════════════════════

_registry_instance = None


def ensure_casemodel_tool_registry():
    """返回三个 Tool 的 ToolRegistry（单例）。"""
    global _registry_instance
    if _registry_instance is not None:
        return _registry_instance

    from src.layers.l2_orchestration.communication.tool_system import Tool, ToolRegistry
    registry = ToolRegistry()
    registry.register_many([
        Tool(name, description=desc, input_schema=schema, risk_level=risk)
        for name, desc, schema, risk in tool_specs()
    ])
    _registry_instance = registry
    return registry


# ════════════════════════════════════════════════════════════
# 2) ToolHub 的 ITool
# ════════════════════════════════════════════════════════════

def _build_itool_classes() -> Dict[str, type]:
    """延迟构造 ITool 子类 —— 没装 langchain 的环境不该因为 import 而失败。"""
    from src.layers.l2_orchestration.communication.tool_protocol import (
        BaseTool, ExecutionContext, ExecutionMode, ToolManifest, ToolResult,
        ToolRisk, ToolStatus,
    )

    specs = {name: (desc, schema) for name, desc, schema, _risk in tool_specs()}

    class _CasemodelTool(BaseTool):
        """三个工具的公共脚手架：manifest 装配 + 统一异常转 ToolResult。"""

        TOOL_NAME = ""
        RUNNER = None                       # type: ignore[assignment]

        def __init__(self, context: ExecutionContext = None):
            desc, schema = specs[self.TOOL_NAME]
            self._manifest = ToolManifest(
                name=self.TOOL_NAME,
                version=__version__,
                description=desc,
                input_schema=schema,
                output_schema={"type": "object"},
                risk_level=ToolRisk.SAFE,
                execution_mode=ExecutionMode.INLINE,
                timeout_s=60.0,
                requires_python=">=3.10",
                requires_packages=["pyyaml", "jsonschema"],
                author="SignOffAI",
                tags=list(TAGS),
                category=CATEGORY,
                status=ToolStatus.ACTIVE,
                tips=["yaml_text 必须是完整的 case 模型 YAML（object + dimensions 必填）",
                      "模型很大时请设 max_cases，避免生成的属性表撑爆上下文"],
            )
            super().__init__(context)

        @property
        def manifest(self) -> "ToolManifest":
            return self._manifest

        async def _execute_impl(self, args: Dict[str, Any],
                                context: "ExecutionContext") -> "ToolResult":
            try:
                data = self.RUNNER(**args)
            except TypeError as exc:          # 参数名/个数不对
                return ToolResult.fail(f"参数不匹配: {exc}")
            except Exception as exc:          # noqa: BLE001
                return ToolResult.fail(f"{self.TOOL_NAME} 执行失败: {exc}")

            # 模型解析不了时，工具把原因放在 {"error": ...} 里返回 —— 那是真失败，
            # 不能报 success=True 让上游以为分析跑通了。
            # （validate 例外：返回 valid=False 表示「校验成功且结论是不合法」。）
            reason = data.get("error") if isinstance(data, dict) else None
            if reason:
                return ToolResult.fail(str(reason), data={"error": str(reason)})

            # 纯确定性工具，无外部验证者；结论由输入 YAML 唯一决定
            return ToolResult.ok(data, verified_by="none")

    return {
        name: type(f"_Tool_{name}", (_CasemodelTool,),
                   {"TOOL_NAME": name, "RUNNER": staticmethod(RUNNERS[name])})
        for name in TOOL_NAMES
    }


def build_casemodel_tools() -> List[Any]:
    """构造三个 ITool 实例（不注册）。"""
    classes = _build_itool_classes()
    return [classes[name]() for name in TOOL_NAMES]


def register_casemodel_tools(hub=None,
                             agent_roles: Optional[List[str]] = None) -> int:
    """把三个工具注册进 ToolHub。

    agent_roles 为 None 时不限定角色 —— casemodel 工具是纯计算，给谁用都安全，
    限定角色反而会让新角色漏掉它。返回成功注册数。
    """
    if hub is None:
        from src.layers.l2_orchestration.communication.tool_hub import ToolHub
        hub = ToolHub.get_instance()
    return sum(1 for tool in build_casemodel_tools()
               if hub.register(tool, agent_roles))


def main(argv: Optional[List[str]] = None) -> int:
    """独立自检：三个接入面各跑一遍。"""
    from pathlib import Path
    args = list(sys.argv[1:] if argv is None else argv)
    # 示例模型已迁到 `config/casemodel/examples/`（CLI 与工作台共用）——
    # 别再指回工具包里的 examples/，那里现在是空的
    path = Path(args[0]) if args else (
        Path(__file__).resolve().parents[4] / "config" / "casemodel"
        / "examples" / "cpu_pipeline.yaml")
    text = path.read_text(encoding="utf-8")

    print(f"源: {path}")
    validate = RUNNERS[TOOL_VALIDATE](text)
    print(f"validate : valid={validate.get('valid')} "
          f"errors={validate.get('error_count')}")
    gaps = RUNNERS[TOOL_GAPS](text)
    print(f"gaps     : score={gaps.get('score')} "
          f"issues={len(gaps.get('issues', []))} "
          f"themes={len(gaps.get('themes', []))}")
    gen = RUNNERS[TOOL_GENERATE](text, max_cases=5)
    print(f"generate : count={gen.get('count')} "
          f"truncated={gen.get('truncated')} dropped={gen.get('dropped')}")
    for tool in build_casemodel_tools():
        manifest = tool.manifest
        print(f"  ITool {manifest.name:<22} risk={manifest.risk_level.value} "
              f"category={manifest.category} issues={manifest.validate() or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
