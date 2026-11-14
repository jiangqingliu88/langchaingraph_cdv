# src/regression_framework/plugins/examples/custom_matrix.py
"""
自定义Matrix插件示例
从CSV文件或数据库读取测试参数，动态生成组合
"""
import csv
import os
from ..base import MatrixPlugin
from ...core.logging_config import get_logger

logger = get_logger(__name__)

class CSVMatrixPlugin(MatrixPlugin):
    plugin_name = "csv_matrix"
    plugin_description = "Generate matrix from CSV file"
    
    def __init__(self):
        self.csv_file = None
    
    def initialize(self, config: dict) -> bool:
        self.csv_file = config.get('csv_file')
        if not self.csv_file or not os.path.exists(self.csv_file):
            logger.warning(f"CSV file not found: {self.csv_file}")
            return False
        return True
    
    def generate(self, **kwargs) -> dict:
        """从CSV读取参数"""
        if not self.csv_file:
            return {}
        
        result = {}
        try:
            with open(self.csv_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    for key, value in row.items():
                        if key not in result:
                            result[key] = []
                        if value not in result[key]:
                            result[key].append(value)
            logger.info(f"Generated {len(result)} parameters from CSV")
        except Exception as e:
            logger.error(f"CSV read error: {e}")
        
        return result

class RangeMatrixPlugin(MatrixPlugin):
    plugin_name = "range_matrix"
    plugin_description = "Generate range of values"
    
    def initialize(self, config: dict) -> bool:
        return True
    
    def generate(self, **kwargs) -> dict:
        """生成数值范围：start, end, step"""
        result = {}
        for key, params in kwargs.items():
            if isinstance(params, dict):
                start = params.get('start', 0)
                end = params.get('end', 10)
                step = params.get('step', 1)
                result[key] = list(range(start, end, step))
        return result