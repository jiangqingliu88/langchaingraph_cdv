#!/usr/bin/env python3
# debug_sc_pred.py - 调试 sc_pred 解析

import yaml
from pathlib import Path
from gen_uvm import YAMLLoader

# 加载 YAML 文件
yaml_file = Path("examples/mpu_with_sc_pred.yaml")
with yaml_file.open("r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

print("=== YAML 内容 ===")
print(f"键: {list(data.keys())}")
print()

# 检查 sc_pred 键
if "sc_pred" in data:
    print("[OK] 找到 sc_pred 键")
    print(f"sc_pred 内容: {data['sc_pred']}")
else:
    print("[ERROR] 未找到 sc_pred 键")

print("\n=== 使用 YAMLLoader 解析 ===")
parsed_data = YAMLLoader.parse_documents([yaml_file])

if "sc_preds" in parsed_data:
    sc_preds = parsed_data["sc_preds"]
    print(f"[OK] 解析到 {len(sc_preds)} 个 sc_pred")
    for i, pred in enumerate(sc_preds):
        print(f"\n--- ScPred {i} ---")
        if pred:
            print(f"  名称: {pred.name}")
            print(f"  ID: {pred.id}")
            print(f"  产生点数量: {len(pred.prod_points)}")
            print(f"  检查点数量: {len(pred.chck_points)}")
        else:
            print("  [ERROR] None")
else:
    print("[ERROR] 未解析到 sc_preds")

print("\n=== 测试 parse_sc_pred_model ===")
sc_pred_model = YAMLLoader.parse_sc_pred_model(data)
print(f"parse_sc_pred_model 结果: {sc_pred_model}")
if sc_pred_model:
    print(f"  名称: {sc_pred_model.name}")
    print(f"  产生点数量: {len(sc_pred_model.prod_points)}")
    print(f"  检查点数量: {len(sc_pred_model.chck_points)}")