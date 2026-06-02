"""
Jinja2模板加载器
"""
from pathlib import Path
from typing import Dict, Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape
import structlog

logger = structlog.get_logger()

class TemplateLoader:
    """模板加载器 - Singleton模式"""
    
    _instance: Optional["TemplateLoader"] = None
    _env: Optional[Environment] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "TemplateLoader":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            self._setup_environment()
    
    def _setup_environment(self):
        """设置Jinja2环境"""
        template_dir = Path(__file__).parent
        
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=select_autoescape(['j2']),
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True
        )
        
        # 添加自定义过滤器
        self._env.filters['indent_code'] = self._indent_code_filter
        self._env.filters['comment_block'] = self._comment_block_filter
        self._env.filters['uvm_field_registry'] = self._uvm_field_registry_filter
        
        # 添加全局函数
        self._env.globals['generate_uvm_id'] = lambda: f"id_{id(self)}"
        
        logger.info("Jinja2模板环境初始化完成")
    
    @staticmethod
    def _indent_code_filter(code: str, spaces: int = 4) -> str:
        """代码缩进过滤器"""
        indent = ' ' * spaces
        return '\n'.join(indent + line if line.strip() else line for line in code.split('\n'))
    
    @staticmethod
    def _comment_block_filter(text: str, style: str = 'line') -> str:
        """注释块过滤器"""
        if style == 'line':
            return '\n'.join(f'// {line}' for line in text.split('\n'))
        elif style == 'block':
            return f'/*\n * {text}\n */'
        return text
    
    @staticmethod
    def _uvm_field_registry_filter(fields: list) -> str:
        """UVM字段注册过滤器"""
        lines = []
        for field in fields:
            if isinstance(field, dict):
                name = field.get('name', '')
                flag = field.get('flag', 'UVM_DEFAULT')
                lines.append(f'`uvm_field_int({name}, {flag})')
            else:
                lines.append(f'`uvm_field_int({field}, UVM_DEFAULT)')
        return '\n    '.join(lines)
    
    def get_template(self, template_path: str):
        """获取模板"""
        try:
            return self._env.get_template(template_path)
        except Exception as e:
            logger.error(f"模板加载失败", path=template_path, error=str(e))
            raise
    
    def render(self, template_path: str, **context) -> str:
        """渲染模板"""
        template = self.get_template(template_path)
        return template.render(**context)
    
    def get_env(self) -> Environment:
        """获取Jinja2环境"""
        return self._env

# 便捷函数
def render_template(template_path: str, **context) -> str:
    """渲染模板的便捷函数"""
    loader = TemplateLoader.get_instance()
    return loader.render(template_path, **context)