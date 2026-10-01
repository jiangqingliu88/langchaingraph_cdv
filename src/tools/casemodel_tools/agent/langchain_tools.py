"""LangChain 接入面 —— 三个 @tool 外壳。

实现在 agent/adapters.py，这里只负责包装成 LangChain 工具。
用 src/tools/_lc_tool_compat.tool 而不是 langchain.tools.tool：
langchain-core 1.x 的 StructuredTool 实例不可直接调用，垫片让它保持可调用
（本仓库有大量调用点把工具对象当普通函数用）。
"""
from __future__ import annotations

import json
from typing import Optional

from src.tools._lc_tool_compat import tool

from .adapters import run_gaps, run_generate, run_validate


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool("casemodel_validate")
def casemodel_validate(yaml_text: str) -> str:
    """按 JSON Schema 校验 case 属性模型 YAML 的语法/类型/必填/取值表形状。

    只回答「文档写对了吗」；引用是否存在、层级是否错位请用 casemodel_gaps。

    Args:
        yaml_text: case 模型 YAML 全文。

    Returns:
        JSON 字符串：{valid, error_count, warning_count, issues:[...]}
    """
    return _dumps(run_validate(yaml_text))


@tool("casemodel_gaps")
def casemodel_gaps(yaml_text: str, max_cases: Optional[int] = None,
                   cases_text: Optional[str] = None) -> str:
    """对 case 属性模型做全量完备性分析，返回缺口与建议。

    ① 功能组织树（叶子覆盖、代号唯一）
    ② 专题（P0/P1/P2 优先级阶梯、作用目标、专题重叠、范围）
    ③ 层级正交性（把字段当维度、把维度当对象、把方法当维度、把检查当对象）
    ④ 维度交叉矩阵与交叉组
    ⑤ 字段取值覆盖缺口
    ⑥ 环境指纹与检查项完备性

    给出 cases_text 时追加「模型 vs 实现」反向核对：真实 case 用了模型没声明的
    字段/取值/专题（模型落后），以及模型覆盖了但真实 case 没写（实现落后）。

    Args:
        yaml_text: case 模型 YAML 全文。
        max_cases: 生成上限；给出时覆盖模型里的 generation.max_cases。
        cases_text: 外部真实 case 列表 YAML 全文（可选）。

    Returns:
        JSON 字符串：score / summary / org_tree / themes / coverage / issues，
        带 cases_text 时另有 external。
    """
    return _dumps(run_gaps(yaml_text, max_cases=max_cases, cases_text=cases_text))


@tool("casemodel_generate")
def casemodel_generate(yaml_text: str, max_cases: Optional[int] = None,
                       seed: Optional[int] = None) -> str:
    """按属性组合生成 case 属性表。

    专题选目标节点与维度集合 → 取字段取值 → 选方法 → 计算组合 → 输出属性表。
    case_id 形如 TC-<对象>-<节点>-<方法>-<NN>。
    使用 seed 驱动的随机源，同模型同 seed 结果完全一致（可复现）。

    Args:
        yaml_text: case 模型 YAML 全文。
        max_cases: 生成上限；给出时覆盖模型里的 generation.max_cases。
        seed: 随机种子；给出时覆盖模型里的 generation.seed。

    Returns:
        JSON 字符串：{count, seed, driver, truncated, dropped, cases:[属性表...]}
    """
    return _dumps(run_generate(yaml_text, max_cases=max_cases, seed=seed))


CASEMODEL_TOOLS = [casemodel_validate, casemodel_gaps, casemodel_generate]
