# src/core/deepseek_config.py
"""
DeepSeek专用配置和优化
"""
from typing import Dict, Any

class DeepSeekOptimizer:
    """DeepSeek优化器 - 针对IC验证任务优化"""
    
    # 不同任务的优化参数
    TASK_CONFIGS = {
        "spec_analysis": {
            "model": "deepseek-chat",
            "temperature": 0.0,
            "max_tokens": 4096,
            "system_prompt_prefix": "你是一个IC验证专家。"
        },
        "test_planning": {
            "model": "deepseek-chat",
            "temperature": 0.1,
            "max_tokens": 4096,
            "system_prompt_prefix": "你是一个验证测试规划专家。"
        },
        "code_generation": {
            "model": "deepseek-coder",
            "temperature": 0.0,
            "max_tokens": 8192,
            "system_prompt_prefix": "你是一个SystemVerilog/UVM代码生成专家。"
        },
        "assertion_generation": {
            "model": "deepseek-coder",
            "temperature": 0.0,
            "max_tokens": 4096,
            "system_prompt_prefix": "你是一个SVA断言专家。"
        },
        "debug_analysis": {
            "model": "deepseek-chat",
            "temperature": 0.0,
            "max_tokens": 4096,
            "system_prompt_prefix": "你是一个验证调试专家。"
        },
        "quality_review": {
            "model": "deepseek-chat",
            "temperature": 0.0,
            "max_tokens": 4096,
            "system_prompt_prefix": "你是一个代码质量审查专家。"
        },
    }
    
    @classmethod
    def get_task_config(cls, task_type: str) -> Dict[str, Any]:
        """获取任务配置"""
        return cls.TASK_CONFIGS.get(task_type, cls.TASK_CONFIGS["spec_analysis"])
    
    @classmethod
    def optimize_prompt_for_deepseek(cls, prompt: str, task_type: str) -> str:
        """
        优化Prompt以适应DeepSeek
        
        DeepSeek特点：
        1. 对中文支持好
        2. 代码生成能力强
        3. 需要清晰的指令
        """
        config = cls.get_task_config(task_type)
        
        # 添加任务前缀
        optimized = f"{config['system_prompt_prefix']}\n\n{prompt}"
        
        # 对于代码生成任务，添加格式指令
        if task_type == "code_generation":
            optimized += "\n\n请生成完整的、可编译的SystemVerilog代码。"
            optimized += "\n使用标准的UVM编码规范。"
        
        # 对于分析任务，要求结构化输出
        if task_type in ["spec_analysis", "test_planning"]:
            optimized += "\n\n请以结构化的JSON格式输出结果。"
        
        return optimized