"""测试公共夹具。

示例模型按用途分两类，夹具名也照这个分：
    clean_*   写对了的模型 —— 用来固定「不该误报」
    flawed_*  故意踩坑的模型 —— 用来固定「每条规则都抓得到」
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.casemodel_tools.analysis import AnalysisResult, analyze, analyze_file
from src.tools.casemodel_tools.domain import CaseModel
from src.tools.casemodel_tools.generation import GenerationResult, generate
from src.tools.casemodel_tools.repository import load_model

#: 示例模型已迁到 `config/casemodel/examples/`（CLI 与工作台共用，见 cli.py 的说明）
EXAMPLES = Path(__file__).resolve().parents[4] / "config" / "casemodel" / "examples"

CPU = EXAMPLES / "cpu_pipeline.yaml"                 # 组织树 + 专题，写对了
CPU_FLAWED = EXAMPLES / "cpu_pipeline_flawed.yaml"   # 组织树 / 专题的坑
FC = EXAMPLES / "fc_flowcontrol.yaml"                # 扁平子对象 + 交叉组（老写法）
FC_FLAWED = EXAMPLES / "fc_flawed.yaml"              # 维度层的坑
FC_REAL = EXAMPLES / "fc_real_cases.yaml"            # 外部真实 case 列表

CLEAN = (CPU, FC)
FLAWED = (CPU_FLAWED, FC_FLAWED)


# ── 模型 ──

def one_model(path):
    """读一份示例 → 一个 CaseModel。

    示例用的是「tests: 列被测对象」写法（一个文件 = 共享属性空间 + N 个对象）。
    夹具要的是「一个模型」的视图，所以取合并体：单对象时它就是那个对象本身。
    """
    from src.tools.casemodel_tools.analysis.multi import merge_models
    from src.tools.casemodel_tools.repository import load_models
    return merge_models(load_models(path))


@pytest.fixture(scope="module")
def cpu() -> CaseModel:
    return one_model(CPU)


@pytest.fixture(scope="module")
def cpu_flawed() -> CaseModel:
    return one_model(CPU_FLAWED)


@pytest.fixture(scope="module")
def fc() -> CaseModel:
    return one_model(FC)


# ── 生成 ──

@pytest.fixture(scope="module")
def cpu_gen(cpu) -> GenerationResult:
    return generate(cpu)


# ── 分析 ──

@pytest.fixture(scope="module")
def cpu_result() -> AnalysisResult:
    return analyze_file(CPU)


@pytest.fixture(scope="module")
def cpu_flawed_result() -> AnalysisResult:
    return analyze_file(CPU_FLAWED)


@pytest.fixture(scope="module")
def fc_result() -> AnalysisResult:
    return analyze_file(FC)


@pytest.fixture(scope="module")
def cpu_roundtrip() -> AnalysisResult:
    """CPU 模型 vs「它自己生成的 case 列表」—— 走真实的落盘/回喂路径。

    导出成 YAML 文本 → 用 case_list 读回来 → 当 external 喂给分析。
    这条路径就是 CLI 的 `generate -o x.yaml` 再 `analyze --cases x.yaml`，
    所以它同时固定了两件事：导出与解析同构（闭环无损），
    以及「模型对自己的 case 列表应当无话可说」。
    """
    from src.tools.casemodel_tools.repository.case_list import cases_from_text
    from src.tools.casemodel_tools.repository.exporters import export_cases

    model = one_model(CPU)
    gen = generate(model)
    text = export_cases(gen.cases, "yaml", seed=gen.seed)
    external = cases_from_text(text, hint=".yaml", source="<roundtrip>")
    return analyze(model, external=external, external_source="<roundtrip>")


@pytest.fixture(scope="module")
def fc_cross() -> AnalysisResult:
    """流控模型 vs 一份带缺陷的真实 case 列表。"""
    return analyze_file(FC, cases=str(FC_REAL))


# ════════════════════════════════════════════════════════════
# 校验辅助
# ════════════════════════════════════════════════════════════

def rules_of(result: AnalysisResult, category: str = "") -> set:
    """结果里出现过的规则 id —— 断言「某条规则是否触发」用。"""
    return {i.rule for i in result.issues
            if not category or i.category == category}


def issues_of(result: AnalysisResult, rule: str) -> list:
    return [i for i in result.issues if i.rule == rule]


# 界面相关的夹具（qt_app / gui / loaded_gui / type_into / load_into）随旧界面
# 一起搬到 `src/workbench/tests/` 了 —— 本包现在是纯工具，测试不需要 Qt。
# 想让工具自己的测试不依赖 Qt，就别在这里把它们加回来。
