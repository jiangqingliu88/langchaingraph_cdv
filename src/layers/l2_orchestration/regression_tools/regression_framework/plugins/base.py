# src/regression_framework/plugins/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional

class PluginBase(ABC):
    """所有插件的基类"""
    
    # 插件元信息（子类必须定义）
    plugin_name: str = None
    plugin_version: str = "1.0.0"
    plugin_description: str = ""
    
    @abstractmethod
    def initialize(self, config: Dict[str, Any]) -> bool:
        """初始化插件，返回是否成功"""
        pass

class NotifierPlugin(PluginBase):
    """通知插件：回归结束后发送通知"""
    
    @abstractmethod
    def notify(self, summary: Dict[str, Any], report_url: str, report_data: Dict[str, Any]):
        """
        发送通知
        summary: {'total': 100, 'pass': 80, 'fail': 15, 'unknown': 5, 'pass_rate': 80.0}
        report_url: HTML报告路径或URL
        report_data: 完整的报告数据（可用于自定义格式）
        """
        pass

class ReporterPlugin(PluginBase):
    """报告插件：自定义报告格式"""
    
    @abstractmethod
    def generate(self, tasks: List, root_dir: str, **kwargs) -> str:
        """
        生成报告，返回报告文件路径
        """
        pass

class MatrixPlugin(PluginBase):
    """Matrix插件：动态生成参数组合"""
    
    @abstractmethod
    def generate(self, **kwargs) -> Dict[str, List]:
        """
        返回参数字典，例如 {'SEED': [1,2,3], 'MODE': ['ADD','SUB']}
        """
        pass

class ExecutorPlugin(PluginBase):
    """执行器插件：对接不同的调度系统"""
    
    @abstractmethod
    def submit(self, script_path: str, cwd: str, job_name: str, **kwargs):
        """提交任务"""
        pass
    
    @abstractmethod
    def poll_status(self, job_id: str) -> str:
        """查询任务状态，返回 'running', 'done', 'failed'"""
        pass

class HookPlugin(PluginBase):
    """钩子插件：在特定事件触发"""
    
    @abstractmethod
    def on_event(self, event_name: str, context: Dict[str, Any]):
        """
        event_name: 'pre_regression', 'post_regression', 'pre_build', 'post_build', 'pre_test', 'post_test'
        context: 事件上下文（包含任务信息等）
        """
        pass