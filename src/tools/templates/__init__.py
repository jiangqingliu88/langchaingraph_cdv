"""模板加载器"""
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

class TemplateLoader:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self._initialized = True
            template_dir = Path(__file__).parent
            self._env = Environment(loader=FileSystemLoader(str(template_dir)))
    
    def render(self, path, **context):
        template = self._env.get_template(path)
        return template.render(**context)

def render_template(path, **context):
    return TemplateLoader.get_instance().render(path, **context)
