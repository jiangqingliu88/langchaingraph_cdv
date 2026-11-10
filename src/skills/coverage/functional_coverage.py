"""
FunctionalCoveragePointGenerator —— 从设计规格提取功能覆盖率点，生成语义 covergroup。

与 env_cov（transaction 字段自动 bin）的区别：这里是"从 spec 语义提取功能点"，
生成**有意义的 bin**（如 opcode 的 add/sub/mul 各一个 bin），而非"自动值域划分"。

这是功能覆盖率的"语义层"——回答"该测什么"（spec 里的功能点），
而非"信号有哪些值"（自动 bin）。

用法:
    from src.skills.coverage.functional_coverage import FunctionalCoveragePointGenerator
    gen = FunctionalCoveragePointGenerator()
    result = gen.generate(spec, module_name="dut")
    # → {covergroup_code, coverage_bins, feature_count}
"""
from __future__ import annotations

from collections import OrderedDict
from typing import Any, Dict, List, Optional


class FunctionalCoveragePointGenerator:
    """从 spec 提取功能点，生成语义 covergroup。"""

    def generate(self, spec: Dict[str, Any], module_name: str = "dut") -> Dict[str, Any]:
        """生成功能覆盖率点，返回 covergroup 代码 + 结构化 coverage_bins。"""
        features = self._extract_features(spec)
        covergroup_code = self._render_covergroup(features, module_name)
        coverage_bins = self._build_bin_structure(features)
        return {
            "covergroup_code": covergroup_code,
            "coverage_bins": coverage_bins,
            "feature_count": len(features),
            "module_name": module_name,
        }

    # ── 1. 从 spec 提取功能点（规则式，spec 已结构化）──

    def _extract_features(self, spec: Dict[str, Any]) -> List[Dict[str, Any]]:
        features: List[Dict[str, Any]] = []

        # 1. features（功能列表，如 add/sub/mul）→ opcode 的枚举 bin
        ops = spec.get("features", []) or []
        for i, op in enumerate(ops):
            name = op if isinstance(op, str) else (op.get("name") or f"op_{i}")
            features.append({
                "feature": name, "type": "enum",
                "signal": "opcode", "value": i,
            })

        # 2. registers → 寄存器读写功能点
        for r in spec.get("registers", []) or []:
            if isinstance(r, dict) and r.get("name"):
                features.append({
                    "feature": r["name"], "type": "register",
                    "signal": r["name"],
                })

        # 3. interfaces → 接口信号翻转功能点
        for iface in spec.get("interfaces", []) or []:
            if not isinstance(iface, dict):
                continue
            for sig in (iface.get("signals") or iface.get("ports") or []):
                if isinstance(sig, str):
                    features.append({"feature": sig, "type": "signal", "signal": sig})
                elif isinstance(sig, dict) and sig.get("name"):
                    features.append({"feature": sig["name"], "type": "signal",
                                     "signal": sig["name"]})

        return features

    # ── 2. 生成 covergroup（语义 bin）──

    def _render_covergroup(self, features: List[Dict[str, Any]], module_name: str) -> str:
        lines = [
            f"// 自动生成的功能覆盖率点（语义 bin，从 spec 提取）",
            f"covergroup cg_{module_name};",
        ]
        # 按 signal 分组，枚举型 feature 生成 bin
        grouped: "OrderedDict[str, List[Dict]]" = OrderedDict()
        for f in features:
            if f["type"] == "enum":
                grouped.setdefault(f["signal"], []).append(f)

        for signal, feats in grouped.items():
            lines.append(f"    cp_{signal}: coverpoint {signal} {{")
            for f in feats:
                lines.append(f"      bins {f['feature']} = {{{f['value']}}};")
            lines.append("    }")

        lines.append(f"  endgroup : cg_{module_name}")
        return "\n".join(lines) + "\n"

    # ── 3. 结构化 coverage_bins（供 gap 归因 + 策略包复用）──

    def _build_bin_structure(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return [
            {"name": f["feature"], "type": f["type"], "signal": f["signal"],
             "value": f.get("value")}
            for f in features
        ]

    # ── 4. 落盘到 coverage/*.sv ──

    def emit_sv_file(self, output_dir: Any, module_name: str = "dut",
                     covergroup_code: str = "") -> str:
        """落盘 covergroup 代码到 coverage/<module>_cg.sv，返回文件路径。"""
        from pathlib import Path
        cov_dir = Path(output_dir) / "coverage"
        cov_dir.mkdir(parents=True, exist_ok=True)
        fpath = cov_dir / f"{module_name}_cg.sv"
        fpath.write_text(covergroup_code, encoding="utf-8")
        return str(fpath)
