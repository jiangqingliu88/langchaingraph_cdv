# src/regression_framework/utils/yaml_utils.py
import copy
import yaml

def merge_yaml(base, override):
    """深度合并两个 YAML 字典（列表使用追加策略）"""
    if not isinstance(base, dict) or not isinstance(override, dict):
        return copy.deepcopy(override)
    result = copy.deepcopy(base)
    for key, val in override.items():
        if key in result:
            if isinstance(result[key], dict) and isinstance(val, dict):
                result[key] = merge_yaml(result[key], val)
            elif isinstance(result[key], list) and isinstance(val, list):
                result[key] = result[key] + val
            else:
                result[key] = copy.deepcopy(val)
        else:
            result[key] = copy.deepcopy(val)
    return result