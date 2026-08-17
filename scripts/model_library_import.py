"""黄金模型入库 — 校验 manifest 的 verified 标记后更新 INDEX.yaml。

用法:
    python scripts/model_library_import.py apb_slave v1

要求:
    - model_library/<ip>/<version>/model.sv 存在
    - manifest.json 中 verified == true（必须先跑 scripts/model_library_verify.py 且 PASS）
    满足才把 <ip> 加入 INDEX.yaml 的 active 版本（模型不可变：只能新增版本）。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
LIB = ROOT / "model_library"


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    ip, version = sys.argv[1], sys.argv[2]
    model_path = LIB / ip / version / "model.sv"
    manifest_path = LIB / ip / version / "manifest.json"
    if not model_path.exists():
        print(f"[FAIL] 模型不存在: {model_path}")
        return 1
    if not manifest_path.exists():
        print(f"[FAIL] manifest 缺失: {manifest_path}（先跑 scripts/model_library_verify.py）")
        return 1
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not manifest.get("verified"):
        print(f"[FAIL] {ip} v{version} 未验证（verified=false）。"
              f"禁止未验证模型入库——先跑 scripts/model_library_verify.py {ip} {version}")
        return 1

    idx_path = LIB / "INDEX.yaml"
    try:
        import yaml
        idx = yaml.safe_load(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else {}
    except Exception:
        idx = {}
    entry = idx.setdefault(ip, {"versions": [], "active": None})
    if version not in entry["versions"]:
        entry["versions"].append(version)
    entry["active"] = version
    entry["matched_features"] = manifest.get("matched_features", [])
    idx_path.write_text(
        "# 黄金参考模型库索引（Golden Reference Model Library INDEX）\n"
        "# 入库必须验证（scripts/model_library_verify.py）；模型不可变，只能新增版本\n"
        + yaml.safe_dump(idx, allow_unicode=True, sort_keys=False),
        encoding="utf-8")
    print(f"[PASS] {ip} v{version} 已入索引（active={version}），sha256={manifest.get('sha256', '')[:12]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
