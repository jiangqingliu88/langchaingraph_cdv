"""
黄金参考模型库加载器 —— model agent 的"真实模型"来源。

设计原则（见 docs/design/golden_model_library.md）：
  1. 入库必须验证（scripts/model_library_verify.py 定向仿真 matched==N && mismatched==0）
  2. LLM 只做"选模型 + 参数化"，不现场写功能逻辑
  3. 无匹配 → 诚实占位（audit 拒绝签核），禁止静默降级为模板

用法:
    from src.tools.lib.golden_library import match_golden, load_golden
    hit = match_golden(design_arch)          # → {"ip","version","path","sha256","params"} 或 None
    sv = load_golden(hit["ip"], hit["version"])
    sv = parameterize(sv, module_name, hit["params"])
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, Optional

# 库根目录（仓库内，git 版本化）
LIBRARY_ROOT = Path(__file__).resolve().parent.parent.parent.parent / "model_library"

# 各黄金模型的 spec 匹配规则（协议关键词 → 需要出现在 interfaces 协议/名字中）
_MATCH_RULES: Dict[str, Dict[str, Any]] = {
    "apb_slave": {
        "protocol_keywords": ("apb",),
        "name_keywords": ("paddr", "pwdata", "prdata", "psel", "penable", "pwrite"),
        "require_registers": False,   # APB 从机语义与寄存器表无关（通用读写回读）
    },
    "uart_tx": {
        "protocol_keywords": ("uart", "serial"),
        "name_keywords": ("tx", "txd", "sout"),
        "require_registers": False,
    },
    "uart_rx": {
        "protocol_keywords": ("uart", "serial"),
        "name_keywords": ("rx", "rxd", "sin"),
        "require_registers": False,
    },
}


def _lib_path(ip: str, version: str) -> Optional[Path]:
    p = LIBRARY_ROOT / ip / version / "model.sv"
    return p if p.exists() else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def match_golden(design_arch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """按 design_arch（interfaces/registers）匹配黄金模型库。

    返回 {"ip", "version", "path", "sha256", "params"}；无匹配返回 None（诚实占位）。
    """
    interfaces = design_arch.get("interfaces", []) or []
    protos = {str(i.get("protocol", "")).lower() for i in interfaces if isinstance(i, dict)}
    names = {str(i.get("name", "")).lower() for i in interfaces if isinstance(i, dict)}

    for ip, rule in _MATCH_RULES.items():
        # 协议匹配：任一协议关键词命中
        proto_hit = bool(protos & set(rule["protocol_keywords"]))
        # 名字匹配：任一信号名关键词命中
        name_hit = any(any(k in n for k in rule["name_keywords"]) for n in names)
        if not (proto_hit or name_hit):
            continue
        # 找 active 版本
        active = _active_version(ip)
        if not active:
            continue
        path = _lib_path(ip, active)
        if not path:
            continue
        params = _params_from_spec(ip, design_arch)
        return {"ip": ip, "version": active, "path": str(path),
                "sha256": _sha256(path), "params": params}
    return None


def _active_version(ip: str) -> Optional[str]:
    """从 INDEX.yaml 读 active 版本；失败回退扫描 v* 目录。"""
    idx = LIBRARY_ROOT / "INDEX.yaml"
    if idx.exists():
        try:
            import yaml
            data = yaml.safe_load(idx.read_text(encoding="utf-8"))
            return (data.get(ip) or {}).get("active")
        except Exception:
            pass
    vers = sorted([d.name for d in (LIBRARY_ROOT / ip).glob("v*")]) if (LIBRARY_ROOT / ip).exists() else []
    return vers[-1] if vers else None


def _params_from_spec(ip: str, design_arch: Dict[str, Any]) -> Dict[str, Any]:
    """从 spec 接口表提取参数（ADDR_W/DATA_W/NREGS）。"""
    if ip != "apb_slave":
        return {}
    interfaces = design_arch.get("interfaces", []) or []
    data_w = 8
    addr_w = 8
    nregs = 16
    for i in interfaces:
        if not isinstance(i, dict):
            continue
        name = str(i.get("name", "")).lower()
        try:
            w = int(i.get("data_width", 1) or 1)
        except (TypeError, ValueError):
            continue
        if "paddr" in name:
            addr_w = max(addr_w, w)
        elif "pwdata" in name or "prdata" in name:
            data_w = max(data_w, w)
    # NREGS：寄存器表行数（有则用之，无则按地址空间 2^ADDR_W 截断到 256）
    regs = design_arch.get("registers", []) or []
    if regs:
        nregs = max(1, min(256, len(regs)))
    else:
        nregs = max(1, min(256, 1 << addr_w))
    return {"NREGS": nregs, "ADDR_W": addr_w, "DATA_W": data_w}


def load_golden(ip: str, version: str) -> str:
    """读取黄金模型 SV 源码。"""
    path = _lib_path(ip, version)
    if not path:
        raise FileNotFoundError(f"黄金模型不存在: model_library/{ip}/{version}/model.sv")
    return path.read_text(encoding="utf-8")


def parameterize(sv_code: str, module_name: str, params: Dict[str, Any]) -> str:
    """黄金模型 → {module}_ref_model：替换模块名 + 更新 parameter 默认值。

    实际参数绑定发生在 bench 实例化处（golden_ref.params 记录应绑定的值）；
    这里只把 definition 的 parameter 默认值设为 spec 推导值（合法 SV，实例化仍可覆盖）。
    """
    text = re.sub(r"module\s+\w+", f"module {module_name}_ref_model", sv_code, count=1)
    for k, v in (params or {}).items():
        text = re.sub(rf"(parameter\s+int\s+{re.escape(k)}\s*=\s*)\d+",
                      lambda m, _v=v: f"{m.group(1)}{_v}", text, count=1)
    return text


def verify_manifest(ip: str, version: str) -> Dict[str, Any]:
    """读取黄金模型 manifest（含 sha256 / verified 标记）。"""
    mp = LIBRARY_ROOT / ip / version / "manifest.json"
    if not mp.exists():
        return {}
    try:
        return json.loads(mp.read_text(encoding="utf-8"))
    except Exception:
        return {}
