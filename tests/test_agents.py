import asyncio
from src.agents import *

async def test_all_agents():
    """测试所有Agent的初始化"""
    
    agents = [
        ("规格规划师", SpecAndTestPlanner()),
        ("验证架构师", VerificationArchitect()),
        ("序列工程师", SequenceEngineer()),
        ("断言工程师", AssertionEngineer()),
        ("覆盖率管理器", CoverageManager()),
        ("回归管理器", RegressionManager()),
        ("调试工程师", DebugEngineer()),
        ("质量保证", QualityAssurance()),
        ("报告生成器", ReportGenerator()),
    ]
    
    for name, agent in agents:
        print(f"\n初始化 {name}...")
        await agent.initialize()
        print(f"  ✅ {name} 初始化成功")
        print(f"  LLM模型: {agent.llm.model_name if agent.llm else 'N/A'}")
        print(f"  工具数量: {len(agent.tools)}")

if __name__ == "__main__":
    asyncio.run(test_all_agents())