# src/regression_framework/plugins/manager.py
import os
import sys
import importlib
import inspect
from pathlib import Path
from typing import Dict, List, Type, Optional, Any

from ..core.logging_config import get_logger
from .base import (
    PluginBase,
    NotifierPlugin,
    ReporterPlugin,
    MatrixPlugin,
    ExecutorPlugin,
    HookPlugin
)

logger = get_logger(__name__)

class PluginManager:
    """插件管理器 - 负责发现、加载、注册插件"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.plugin_dirs = []
        self.plugins: Dict[str, PluginBase] = {}
        self.notifiers: Dict[str, NotifierPlugin] = {}
        self.reporters: Dict[str, ReporterPlugin] = {}
        self.matrix_plugins: Dict[str, MatrixPlugin] = {}
        self.executors: Dict[str, ExecutorPlugin] = {}
        self.hooks: List[HookPlugin] = []
        
        # 内置插件目录
        builtin_dir = os.path.join(os.path.dirname(__file__), 'builtin')
        self.plugin_dirs.append(builtin_dir)
    
    def add_plugin_dir(self, path: str):
        """添加插件搜索目录"""
        if os.path.isdir(path) and path not in self.plugin_dirs:
            self.plugin_dirs.append(path)
            logger.info(f"Added plugin directory: {path}")
    
    def discover_plugins(self):
        """发现并加载所有插件"""
        for plugin_dir in self.plugin_dirs:
            if not os.path.isdir(plugin_dir):
                continue
            self._load_plugins_from_dir(plugin_dir)
    
    def _load_plugins_from_dir(self, dir_path: str):
        """从单个目录加载插件"""
        for file in os.listdir(dir_path):
            if file.endswith('.py') and not file.startswith('__'):
                module_name = file[:-3]
                try:
                    # 动态导入模块
                    spec = importlib.util.spec_from_file_location(
                        f"plugin_{module_name}",
                        os.path.join(dir_path, file)
                    )
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # 扫描模块中的类
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if obj is PluginBase or not issubclass(obj, PluginBase):
                            continue
                        if obj.__module__ != module.__name__:
                            continue
                        self._register_plugin(obj)
                except Exception as e:
                    logger.warning(f"Failed to load plugin from {file}: {e}")
    
    def _register_plugin(self, plugin_class: Type[PluginBase]):
        """注册插件实例"""
        try:
            # 实例化插件
            plugin = plugin_class()
            plugin_name = plugin.plugin_name or plugin_class.__name__
            
            # 根据插件类型分类注册
            if isinstance(plugin, NotifierPlugin):
                self.notifiers[plugin_name] = plugin
                logger.info(f"Registered notifier plugin: {plugin_name}")
            elif isinstance(plugin, ReporterPlugin):
                self.reporters[plugin_name] = plugin
                logger.info(f"Registered reporter plugin: {plugin_name}")
            elif isinstance(plugin, MatrixPlugin):
                self.matrix_plugins[plugin_name] = plugin
                logger.info(f"Registered matrix plugin: {plugin_name}")
            elif isinstance(plugin, ExecutorPlugin):
                self.executors[plugin_name] = plugin
                logger.info(f"Registered executor plugin: {plugin_name}")
            elif isinstance(plugin, HookPlugin):
                self.hooks.append(plugin)
                logger.info(f"Registered hook plugin: {plugin_name}")
            else:
                self.plugins[plugin_name] = plugin
                logger.info(f"Registered generic plugin: {plugin_name}")
                
        except Exception as e:
            logger.error(f"Failed to register plugin {plugin_class.__name__}: {e}")
    
    def get_notifier(self, name: str) -> Optional[NotifierPlugin]:
        """获取通知插件"""
        return self.notifiers.get(name)
    
    def get_reporter(self, name: str) -> Optional[ReporterPlugin]:
        """获取报告插件"""
        return self.reporters.get(name)
    
    def get_matrix_plugin(self, name: str) -> Optional[MatrixPlugin]:
        """获取Matrix插件"""
        return self.matrix_plugins.get(name)
    
    def get_executor(self, name: str) -> Optional[ExecutorPlugin]:
        """获取执行器插件"""
        return self.executors.get(name)
    
    def trigger_hook(self, event_name: str, context: Dict[str, Any]):
        """触发所有钩子插件"""
        for hook in self.hooks:
            try:
                hook.on_event(event_name, context)
            except Exception as e:
                logger.warning(f"Hook {hook.plugin_name} failed for event {event_name}: {e}")
    
    def list_plugins(self) -> Dict[str, List[str]]:
        """列出所有已注册插件"""
        return {
            'notifiers': list(self.notifiers.keys()),
            'reporters': list(self.reporters.keys()),
            'matrix_plugins': list(self.matrix_plugins.keys()),
            'skills': list(self.executors.keys()),
            'hooks': [h.plugin_name for h in self.hooks]
        }