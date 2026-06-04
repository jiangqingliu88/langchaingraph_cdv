"""
共享上下文 Schema —— Agent 间数据契约

每个 Agent 声明 consumes / produces，CLI 只负责调度。
上游 Agent 通过 produces 写入 ctx，下游 Agent 通过 consumes 读取 ctx。
"""
from pydantic import BaseModel, Field
from typing import List, Dict, Optional


class SpecContext(BaseModel):
    """① spec_planner 产出：规格分析与测试规划结果"""
    test_points: List[dict]   = Field(default_factory=list, description="测试点列表 [{name,category,priority,...}]")
    features: List[str]       = Field(default_factory=list, description="提取的功能点")
    verification_architecture: dict = Field(default_factory=dict, description="验证架构高层设计")
    coverage_targets: dict    = Field(default_factory=dict, description="覆盖率目标")
    risks: List[str]          = Field(default_factory=list, description="风险项")


class EnvContext(BaseModel):
    """② architect 产出：UVM 验证环境代码"""
    env_name: str    = Field(default="", description="环境名，如 uart_env")
    output_dir: str  = Field(default="", description="生成代码输出目录")
    filelist: str    = Field(default="", description="filelist.f 路径")
    agent_count: int = Field(default=0, description="Agent 组件数量")
    files: List[str] = Field(default_factory=list, description="生成的文件列表")


class PoliciesContext(BaseModel):
    """③ seq_engineer 产出：序列 / 策略定义"""
    sequences: List[dict]          = Field(default_factory=list, description="UVM sequence 列表")
    virtual_sequences: List[dict]  = Field(default_factory=list, description="virtual sequence 列表")
    policies: List[dict]           = Field(default_factory=list, description="约束策略")


class TestsContext(BaseModel):
    """④ tc_engineer 产出：生成的测试用例"""
    output_dir: str     = Field(default="", description="测试用例输出目录")
    scenario_count: int = Field(default=0, description="生成的场景数")
    test_names: List[str] = Field(default_factory=list, description="测试用例名列表")
    scenarios: List[dict] = Field(default_factory=list, description="场景详情")
    files: List[List[str]] = Field(default_factory=list, description="每个测试的文件列表")


class RegressionContext(BaseModel):
    """⑥ regress_manager 产出：回归测试结果"""
    compile_status: str = Field(default="unknown", description="编译状态: passed / failed / unknown")
    pass_count: int     = Field(default=0)
    fail_count: int     = Field(default=0)
    results: List[dict] = Field(default_factory=list, description="每项测试结果")
    scripts: List[str]  = Field(default_factory=list, description="生成的回归脚本")


class CoverageContext(BaseModel):
    """⑦ cover_manager 产出：覆盖率分析"""
    coverage_data: dict   = Field(default_factory=dict, description="覆盖率原始数据")
    gaps: List[dict]      = Field(default_factory=list, description="覆盖率空洞")
    suggestions: List[str] = Field(default_factory=list, description="提升覆盖率的建议")
    report: dict          = Field(default_factory=dict, description="覆盖率报告摘要")


class SharedContext(BaseModel):
    """所有 Agent 共享的上下文 —— 全局白板"""
    spec:       SpecContext       = Field(default_factory=SpecContext)
    env:        EnvContext        = Field(default_factory=EnvContext)
    policies:   PoliciesContext   = Field(default_factory=PoliciesContext)
    tests:      TestsContext      = Field(default_factory=TestsContext)
    regression: RegressionContext = Field(default_factory=RegressionContext)
    coverage:   CoverageContext   = Field(default_factory=CoverageContext)

    # 元信息
    working_dir: str = Field(default="output", description="工作目录")
    env_name:   str = Field(default="env", description="环境名")

    def merge_from_result(self, key: str, data: dict) -> None:
        """将 Agent 返回的 data[key] 合并到对应 ctx 字段"""
        if not key or key not in data:
            return
        current = getattr(self, key)
        incoming = data[key]
        if isinstance(incoming, dict):
            for k, v in incoming.items():
                if hasattr(current, k) and v:
                    setattr(current, k, v)
        elif isinstance(incoming, list):
            existing = getattr(current, list(incoming).__class__.__name__ == 'list' and incoming or [])
            # merge lists by extending
            if hasattr(current, '__fields__'):
                pass  # let the dict merge handle it

    def write(self, key: str, data: dict) -> None:
        """用 data 更新 ctx.<key>"""
        if not key or not hasattr(self, key):
            return
        target = getattr(self, key)
        if isinstance(target, BaseModel):
            for k, v in data.items():
                if hasattr(target, k) and v:
                    setattr(target, k, v)

    def read(self, *keys: str) -> dict:
        """读取 ctx 中指定 key 的当前值（返回普通 dict）"""
        result = {}
        for k in keys:
            if hasattr(self, k):
                val = getattr(self, k)
                result[k] = val.model_dump() if isinstance(val, BaseModel) else val
        return result
