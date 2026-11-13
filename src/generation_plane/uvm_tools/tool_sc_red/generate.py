#!/usr/bin/env python3
# generate.py

import yaml
import os
from jinja2 import Environment, FileSystemLoader

# 定义工作目录
WORK_DIR = "sc_pred_work"

def load_yaml_config(yaml_file):
    """加载YAML配置文件"""
    with open(yaml_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

def create_directories():
    """创建输出目录（在sc_pred_work下）"""
    dirs = ['interfaces', 'prods', 'mon_ex']
    for dir_name in dirs:
        full_path = os.path.join(WORK_DIR, dir_name)
        os.makedirs(full_path, exist_ok=True)
    print(f"✓ 创建目录结构: {WORK_DIR}/")

def render_prod_interface(point, env):
    """生成Prod专用Interface文件"""
    template = env.get_template('prod_point_if.sv.j2')
    content = template.render(point=point)
    
    filename = os.path.join(WORK_DIR, "interfaces", f"{point['point_name']}_prod_if.sv")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ 生成 {filename}")

def render_mon_interface(point, env):
    """生成Monitor专用Interface文件"""
    template = env.get_template('prod_point_if.sv.j2')
    content = template.render(point=point)
    
    filename = os.path.join(WORK_DIR, "interfaces", f"{point['point_name']}_mon_if.sv")
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ 生成 {filename}")

def render_prod_component(point, env):
    """生成Prod组件文件"""
    template = env.get_template('prod.sv.j2')
    
    context = {
        'point': point,
        'print_fields': generate_prod_print_fields(point),
        'convert_fields': generate_prod_convert_fields(point)
    }
    
    content = template.render(**context)
    filename = os.path.join(WORK_DIR, "prods", f"{point['point_name']}_prod.sv")
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ 生成 {filename}")

def render_mon_ex_component(point, env):
    """生成Monitor Extended组件文件"""
    template = env.get_template('mon_ex.sv.j2')
    
    context = {
        'point': point,
        'print_mon_fields': generate_mon_print_fields(point),
        'convert_mon_fields': generate_mon_convert_fields(point)
    }
    
    content = template.render(**context)
    filename = os.path.join(WORK_DIR, "mon_ex", f"{point['point_name']}_mon_ex.sv")
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  ✓ 生成 {filename}")

def generate_prod_print_fields(point):
    """生成Prod的print字段"""
    fields = []
    for port in point['ports']:
        if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
            if port['width'] > 1:
                fields.append(f", {port['name']}=0x%0h")
            else:
                fields.append(f", {port['name']}=%0d")
    return ''.join(fields)

def generate_prod_convert_fields(point):
    """生成Prod的convert字段"""
    fields = []
    for port in point['ports']:
        if port['name'] not in ['clk', 'rst'] and port['dir'] == 'input':
            field_name = port['name']
            if port['width'] > 1:
                fields.append(f", {field_name}=0x%0h")
            else:
                fields.append(f", {field_name}=%0d")
    return ''.join(fields)

def generate_mon_print_fields(point):
    """生成Monitor的print字段"""
    fields = []
    for port in point['ports']:
        if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
            if port['width'] > 1:
                fields.append(f", {port['name']}=0x%0h")
            else:
                fields.append(f", {port['name']}=%0d")
    return ''.join(fields)

def generate_mon_convert_fields(point):
    """生成Monitor的convert字段"""
    fields = []
    for port in point['ports']:
        if port['name'] not in ['clk', 'rst'] and port['dir'] == 'output':
            field_name = port['name']
            if port['width'] > 1:
                fields.append(f", {field_name}=0x%0h")
            else:
                fields.append(f", {field_name}=%0d")
    return ''.join(fields)

def main():
    """主函数"""
    print("=" * 60)
    print("Jinja2 代码生成器 (Prod + Monitor Extended)")
    print("=" * 60)
    
    # 加载配置
    config = load_yaml_config('mpu_sc_pred.yaml')
    print(f"✓ 加载配置文件: mpu.yaml")
    print(f"  模块: {config['sc_pred']['name']}")
    print(f"  ID: {config['sc_pred']['id']}")
    
    # 设置Jinja2环境
    env = Environment(
        loader=FileSystemLoader('./TEMPLATES/sc_pred_templates'),
        trim_blocks=True,
        lstrip_blocks=True
    )
    
    # 创建目录
    create_directories()
    
    # 获取所有点
    prod_points = config['sc_pred'].get('prod_points', [])
    chck_points = config['sc_pred'].get('chck_points', [])
    
    print(f"\n📁 生成Interface文件:")
    # 生成Prod点的Interface
    for point in prod_points:
        render_prod_interface(point, env)
    
    # 生成Chk点的Interface
    for point in chck_points:
        render_mon_interface(point, env)
    
    print(f"\n📁 生成Prod组件:")
    # 生成Prod点的组件
    for point in prod_points:
        render_prod_component(point, env)
    
    print(f"\n📁 生成Monitor Extended组件:")
    # 生成Chk点的mon_ex组件
    for point in chck_points:
        render_mon_ex_component(point, env)
    
    print("\n" + "=" * 60)
    print(f"✅ 代码生成完成! 输出目录: {WORK_DIR}/")
    print("=" * 60)

if __name__ == '__main__':
    main()