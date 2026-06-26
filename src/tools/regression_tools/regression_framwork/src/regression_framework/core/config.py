# src/regression_framework/core/config.py
import os
import sys
import yaml
import re
import json
import copy
from pathlib import Path
from typing import Dict, Any, List, Optional
from jinja2 import Template
from jsonschema import validate, ValidationError
from .exceptions import ConfigError
from .logging_config import get_logger
from ..plugins.manager import PluginManager
logger = get_logger(__name__)

# YAML Schema 定义
CONFIG_SCHEMA = {
    "type": "object",
    "properties": {
        "global_vars": {"type": "object"},
        "settings": {
            "type": "object",
            "properties": {
                "default_build": {"type": "string"},
                "default_count": {"type": "integer", "minimum": 1},
                "simulators": {"type": "object"},
                "hooks": {"type": "object"},
                "lsf_opts": {"type": "object"},
                "build_cache": {"type": "boolean"},
                "retry": {"type": "integer", "minimum": 0}
            }
        },
        "builds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "simulator": {"type": "string"},
                    "compile_opts": {"type": "array", "items": {"type": "string"}},
                    "files": {"type": "array", "items": {"type": "string"}},
                    "local_vars": {"type": "object"},
                    "hooks": {"type": "object"}
                },
                "required": ["name"]
            }
        },
        "tests": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "build": {"anyOf": [{"type": "string"}, {"type": "object"}]},
                    "count": {"type": "integer", "minimum": 1},
                    "matrix": {"type": "array"},
                    "local_vars": {"type": "object"},
                    "run_opts": {"type": "array", "items": {"type": "string"}},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "file_pattern": {"type": "array", "items": {"type": "string"}},
                    "expect": {"type": "object"},
                    "hooks": {"type": "object"}
                },
                "required": ["name"]
            }
        }
    },
    "required": ["global_vars", "settings", "builds", "tests"]
}

class ConfigBuilder:
    """配置构建器 - 支持 include, extends, 变量替换, matrix展开, 命令行覆盖"""
    
    def __init__(self, yaml_file: str, cli_overrides: Optional[List[str]] = None):
        self.yaml_file = yaml_file
        self.cli_overrides = cli_overrides or []
        self.context = {}
        self.plugin_dir = "plugins"
        self._raw_data = {}
        self.plugin_manager = PluginManager()
        self.plugin_manager.discover_plugins()  # 自动发现插件
    def load_yaml_with_includes(self, filepath: str, base_dir: str = None) -> dict:
        if base_dir is None:
            base_dir = os.path.dirname(filepath) or '.'
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to load YAML {filepath}: {e}")
            raise ConfigError(f"YAML load error: {e}")
        
        if data is None:
            data = {}
            
        if 'includes' in data:
            for inc in data['includes']:
                inc_path = os.path.join(base_dir, inc)
                if not os.path.exists(inc_path):
                    logger.warning(f"Include file '{inc_path}' not found, skipping.")
                    continue
                inc_data = self.load_yaml_with_includes(inc_path, base_dir)
                data = self._merge_config(inc_data, data)
        return data
    
    def _merge_config(self, base: dict, override: dict) -> dict:
        if not isinstance(base, dict) or not isinstance(override, dict):
            return copy.deepcopy(override)
        result = copy.deepcopy(base)
        for key, val in override.items():
            if key in result:
                if isinstance(result[key], dict) and isinstance(val, dict):
                    result[key] = self._merge_config(result[key], val)
                elif key == 'tests' and isinstance(result[key], list) and isinstance(val, list):
                    # 按 name 去重合并
                    names = {t.get('name') for t in result[key] if t.get('name')}
                    for item in val:
                        if item.get('name') in names:
                            for idx, old in enumerate(result[key]):
                                if old.get('name') == item.get('name'):
                                    result[key][idx] = self._merge_config(old, item)
                                    break
                        else:
                            result[key].append(item)
                elif key == 'builds' and isinstance(result[key], list) and isinstance(val, list):
                    existing = {b['name'] for b in result[key] if b.get('name')}
                    for item in val:
                        if item.get('name') in existing:
                            for idx, old in enumerate(result[key]):
                                if old.get('name') == item.get('name'):
                                    result[key][idx] = self._merge_config(old, item)
                                    break
                        else:
                            result[key].append(item)
                else:
                    result[key] = copy.deepcopy(val)
            else:
                result[key] = copy.deepcopy(val)
        return result
    
    def substitute_vars(self, obj, context: dict):
        if isinstance(obj, str):
            try:
                return Template(obj).render(**context)
            except Exception as e:
                logger.warning(f"Template render failed for '{obj}': {e}")
                return obj
        elif isinstance(obj, list):
            return [self.substitute_vars(item, context) for item in obj]
        elif isinstance(obj, dict):
            return {k: self.substitute_vars(v, context) for k, v in obj.items()}
        else:
            return obj
    
    def expand_matrix(self, tests: list) -> list:
        expanded = []
        for test in tests:
            if 'matrix' not in test:
                expanded.append(test)
                continue
            matrix_items = test.pop('matrix')
            all_params = {}
            for item in matrix_items:
                # 检查是否为插件调用
                if 'plugin' in item:
                    plugin_name = item.pop('plugin')
                    plugin = self.plugin_manager.get_matrix_plugin(plugin_name)
                    if plugin:
                        plugin.initialize(item.get('config', {}))
                        result = plugin.generate(**item.get('args', {}))
                        for k, v in result.items():
                            all_params.setdefault(k, []).extend(v)
                    else:
                        logger.warning(f"Matrix plugin '{plugin_name}' not found")
                else:
                    # 原有静态逻辑
                    for k, v in item.items():
                        if not isinstance(v, list):
                            v = [v]
                        all_params.setdefault(k, []).extend(v)
            
            name_format = test.pop('name_format', None)
            keys = list(all_params.keys())
            values = [all_params[k] for k in keys]
            idx = 0
            for combo in __import__('itertools').product(*values):
                new_test = copy.deepcopy(test)
                param_dict = dict(zip(keys, combo))
                if name_format:
                    ctx = param_dict.copy()
                    ctx['idx'] = idx
                    name = name_format.format(**ctx)
                else:
                    suffix = '_'.join([str(v) for v in param_dict.values()])
                    name = f"{test['name']}_{suffix}"
                new_test['name'] = name
                if 'local_vars' not in new_test:
                    new_test['local_vars'] = {}
                for k, v in param_dict.items():
                    new_test['local_vars'][k] = v
                expanded.append(new_test)
                idx += 1
        return expanded
    
    def expand_count(self, tests: list, default_count: int) -> list:
        expanded = []
        for test in tests:
            count = test.pop('count', default_count)
            base_seed = test.get('local_vars', {}).get('SEED', None)
            for i in range(1, count + 1):
                new_test = copy.deepcopy(test)
                if count > 1:
                    new_test['name'] = f"{test['name']}_run_{i}"
                    if base_seed is not None:
                        if 'local_vars' not in new_test:
                            new_test['local_vars'] = {}
                        new_test['local_vars']['SEED'] = base_seed + i - 1
                expanded.append(new_test)
        return expanded
    
    def apply_cli_overrides(self, data: dict) -> dict:
        """应用命令行覆盖，如 --set global_vars.SEED=9999"""
        for override in self.cli_overrides:
            if '=' not in override:
                logger.warning(f"Ignoring invalid override: {override}")
                continue
            path_str, value_str = override.split('=', 1)
            path = path_str.split('.')
            
            # 解析值类型
            try:
                if value_str.lower() == 'true':
                    value = True
                elif value_str.lower() == 'false':
                    value = False
                elif value_str.isdigit():
                    value = int(value_str)
                elif re.match(r'^-?\d+\.\d+$', value_str):
                    value = float(value_str)
                else:
                    value = value_str
            except:
                value = value_str
            
            # 遍历路径
            current = data
            for key in path[:-1]:
                if key not in current:
                    logger.warning(f"Path {path_str} not found, creating")
                    current[key] = {}
                current = current[key]
            current[path[-1]] = value
            logger.info(f"Applied override: {path_str} = {value}")
        return data
    
    def validate_config(self, data: dict):
        """使用 jsonschema 校验配置"""
        try:
            validate(instance=data, schema=CONFIG_SCHEMA)
        except ValidationError as e:
            raise ConfigError(f"Config validation error: {e.message} at {e.path}")
    
    def build(self, incremental=False, repo_path='.') -> dict:
        raw = self.load_yaml_with_includes(self.yaml_file)
        raw = self._resolve_extends(raw)
        raw = self.apply_cli_overrides(raw)
        self.validate_config(raw)
        
        global_vars = raw.get('global_vars', {})
        self.context = global_vars.copy()
        self.context.update(os.environ)
        
        substituted = self.substitute_vars(raw, self.context)
        
        settings = substituted.get('settings', {})
        default_count = settings.get('default_count', 1)
        tests = substituted.get('tests', [])
        tests = self.expand_matrix(tests)
        tests = self.expand_count(tests, default_count)
        
        if incremental:
            from ..utils.git_utils import filter_by_git_changes
            tests = filter_by_git_changes(tests, repo_path)
        
        substituted['tests'] = tests
        return substituted
    
    def _resolve_extends(self, data: dict) -> dict:
        if 'extends' in data:
            base_path = data.pop('extends')
            base_dir = os.path.dirname(self.yaml_file) or '.'
            base_full = os.path.join(base_dir, base_path)
            if not os.path.exists(base_full):
                logger.warning(f"Base config '{base_full}' not found, skipping extends.")
                return data
            base_data = self.load_yaml_with_includes(base_full, base_dir)
            return self._merge_config(base_data, data)
        return data