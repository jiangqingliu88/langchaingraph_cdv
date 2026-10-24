"""检查 gen_uvm.run 后 environment.agents 的 config 合并是否生效。"""
import sys, tempfile
sys.path.insert(0, 'src')
from pathlib import Path
from src.tools.generation.uvm_tools.tool_uvm.gen_uvm import UVMGenerator, JinjaRenderer, TEMPLATES_DIR, YAMLLoader

od = Path('output_jiang_20260819_211653')
gen = UVMGenerator(JinjaRenderer(TEMPLATES_DIR), od)

# 手动走 parse + 合并逻辑
yaml_files = YAMLLoader.collect_paths([od / 'inputs' / 'yaml' / 'uvm'])
data = YAMLLoader.parse_documents(yaml_files)
interfaces = data['interfaces']
environments = data['environments']
print('interfaces:', [(a.name, a.config) for a in interfaces])
for env in environments:
    print('env agents before merge:', [(a.name, a.config) for a in env.agents])
    iface_by_name = {a.name: a for a in interfaces}
    for ag in env.agents:
        src = iface_by_name.get(ag.name)
        if src is not None and getattr(src, 'config', None):
            ag.config = src.config
    print('env agents after merge:', [(a.name, a.config) for a in env.agents])
