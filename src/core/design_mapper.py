"""
DesignArchitectMapper — 需求→模块→功能点→测试点 三层强映射引擎

这是 SignOffAI "可追溯" 的核心支柱:
  Layer 1: Requirements → Modules/Features
  Layer 2: Features → Testpoints
  Layer 3: Full traceability chain with confidence scores
"""

from __future__ import annotations

import re, json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# 关键词匹配库
FEATURE_KEYWORDS = {
    "data_path":    ["data", "数据", "通路", "path", "packet", "包", "forward", "转发"],
    "backpressure": ["backpressure", "背压", "buffer", "full", "满", "flow_control", "流控"],
    "arbitration":  ["arbit", "仲裁", "grant", "priority", "优先级", "round_robin"],
    "error":        ["error", "错误", "fault", "inject", "注入", "exception", "异常"],
    "interrupt":    ["interrupt", "中断", "irq", "isr"],
    "register":     ["register", "寄存器", "cfg", "config", "配置", "apb", "csr"],
    "reset":        ["reset", "复位", "rst", "init", "初始化"],
    "clock":        ["clock", "时钟", "clk", "frequency", "频率"],
    "power":        ["power", "功耗", "sleep", "休眠", "low_power"],
    "security":     ["security", "安全", "encrypt", "加密", "auth", "认证"],
}


@dataclass
class ParsedModule:
    """从 MD 解析出的模块"""
    name: str
    parent: str = ""
    description: str = ""
    interfaces: List[dict] = field(default_factory=list)
    signals: List[dict] = field(default_factory=list)
    features: List[dict] = field(default_factory=list)
    rtl_file: str = ""
    rtl_hash: str = ""


@dataclass
class MappingReport:
    """三层映射报告"""
    total_requirements: int = 0
    mapped_requirements: int = 0
    unmapped_requirements: List[str] = field(default_factory=list)
    total_modules: int = 0
    total_features: int = 0
    total_testpoints: int = 0
    mapping_matrix: List[dict] = field(default_factory=list)
    coverage_by_layer: Dict[str, float] = field(default_factory=dict)


class DesignArchitectMapper:
    """设计架构师 → 需求 → 测试点 三层映射引擎"""

    def parse_md_modules(self, md_text: str) -> List[ParsedModule]:
        """从 Markdown 设计文档解析模块/接口/功能点

        支持新格式:
          # 模块名（层级）  ← 模块标题
          <!-- meta -->    ← 元数据
          ## 1. 概述
          ## 2. 功能需求
          ### 需求标题
          **级别**：P0
          **类型**：FUNCTIONAL
          **描述**：...
          **验收标准**：...
          ## 3. 接口规范
          ## 4. 时序约束
          ## 5. 功耗约束
        """
        modules = []
        current_module = None
        current_feature = None
        in_meta = False
        meta_text = ""

        for line in md_text.split("\n"):
            stripped = line.strip()

            # HTML 注释元数据
            if stripped.startswith("<!--") and not stripped.endswith("-->"):
                in_meta = True
                meta_text = stripped[4:]
                continue
            if in_meta:
                if stripped.endswith("-->"):
                    meta_text += " " + stripped[:-3]
                    in_meta = False
                else:
                    meta_text += " " + stripped
                continue

            # H1 标题 = 模块名
            m = re.match(r'^#\s+(.+?)(?:（(.+?)）)?$', stripped)
            if m:
                if current_module:
                    modules.append(current_module)
                module_name = m.group(1).strip()
                current_module = ParsedModule(name=module_name)

                # 从元数据提取
                if meta_text:
                    lv = re.search(r'level:\s*(\w+)', meta_text)
                    parent = re.search(r'parent:\s*(\S+)', meta_text)
                    if parent: current_module.parent = parent.group(1)
                    ifcs = re.search(r'interfaces:\s*\[(.*?)\]', meta_text)
                    if ifcs:
                        for ifc in ifcs.group(1).split(","):
                            current_module.interfaces.append({"name": ifc.strip().strip("'\"") , "direction": "INPUT", "width": 32, "protocol": ""})
                    sigs = re.search(r'signals:\s*\[(.*?)\]', meta_text) or re.search(r'flags:\s*\[(.*?)\]', meta_text)
                    if sigs:
                        current_module.signals = [{"name": s.strip().strip("'\"")} for s in sigs.group(1).split(",")]
                    rtl = re.search(r'rtl_file:\s*(\S+)', meta_text)
                    if rtl: current_module.rtl_file = rtl.group(1)
                    meta_text = ""
                continue

            # H2/H3 标题
            m = re.match(r'^#+\s+(.+)', stripped)
            if m:
                section_title = m.group(1).strip()
                # 检查是否是需求标题（不以数字或特定词开头）
                if not re.match(r'^\d+[.\s]|概述|接口规范|时序约束|功耗约束', section_title):
                    if current_module:
                        current_feature = {"name": section_title, "level": "P0", "keywords": [], "spec_ref": "", "testpoints": []}
                        current_module.features.append(current_feature)
                continue

            if not current_module:
                # 尝试从 h1 之外的格式提取模块名
                m = re.match(r'#+\s*(?:模块|Module)[：:]\s*(.+)', stripped, re.IGNORECASE)
                if m:
                    current_module = ParsedModule(name=m.group(1).strip())
                    continue
                continue

            # 解析需求属性
            if current_feature:
                level_m = re.match(r'\*\*级别\*\*[：:]\s*(P\d)', stripped)
                if level_m: current_feature["level"] = level_m.group(1)

                type_m = re.match(r'\*\*类型\*\*[：:]\s*(\w+)', stripped)
                if type_m:
                    feat_type = type_m.group(1)
                    current_feature.setdefault("_type", feat_type)

                req_m = re.match(r'\*\*需求\*\*[：:]\s*(.+)', stripped)
                if req_m: current_feature["spec_ref"] = req_m.group(1).strip()

                tp_m = re.match(r'\*\*测试点\*\*[：:]\s*(.+)', stripped)
                if tp_m:
                    current_feature["testpoints"] = [t.strip() for t in tp_m.group(1).split(",")]

                # 关键词提取
                for kw_line in [stripped]:
                    for category, kws in FEATURE_KEYWORDS.items():
                        if any(kw.lower() in kw_line.lower() for kw in kws):
                            if category not in current_feature.get("keywords", []):
                                current_feature.setdefault("keywords", []).append(category)

            # 接口: ### 接口：xxx 或 ### Interface: xxx
            m = re.match(r'#+\s*(?:接口|Interface)[：:]\s*(.+)', line, re.IGNORECASE)
            if m:
                current_module.interfaces.append({"name": m.group(1).strip(), "direction": "INPUT", "width": 32, "protocol": ""})
                continue

            # 功能点: ### 功能点：xxx 或 ### Feature: xxx
            m = re.match(r'#+\s*(?:功能点|Feature)[：:]\s*(.+)', line, re.IGNORECASE)
            if m:
                feat_name = m.group(1).strip()
                current_feature = {"name": feat_name, "level": "P0", "keywords": [], "spec_ref": "", "testpoints": []}
                current_module.features.append(current_feature)
                continue

            # 从 HTML 注释提取元数据
            meta_m = re.search(r'<!--\s*(.*?)\s*-->', line, re.DOTALL)
            if meta_m and current_feature:
                meta_text = meta_m.group(1)
                # level: P1
                lv = re.search(r'level:\s*(P\d)', meta_text)
                if lv: current_feature["level"] = lv.group(1)
                # requirements: [REQ-001, REQ-002]
                rr = re.search(r'requirements:\s*\[(.*?)\]', meta_text)
                if rr: current_feature["spec_ref"] = rr.group(1).strip()
                # testpoints: [TP-001, TP-002]
                tp = re.search(r'testpoints:\s*\[(.*?)\]', meta_text)
                if tp: current_feature["testpoints"] = [t.strip() for t in tp.group(1).split(",")]

            # 信号: signals: [...]
            sig_m = re.search(r'signals:\s*\[(.*?)\]', line)
            if sig_m:
                current_module.signals = [{"name": s.strip()} for s in sig_m.group(1).split(",")]

            # 接口列表: interfaces: [...]
            ifc_m = re.search(r'interfaces:\s*\[(.*?)\]', line)
            if ifc_m:
                for ifc_name in ifc_m.group(1).split(","):
                    ifc_name = ifc_name.strip()
                    if not any(i["name"] == ifc_name for i in current_module.interfaces):
                        current_module.interfaces.append({"name": ifc_name, "direction": "INPUT", "width": 32, "protocol": ""})

            # features: [...]
            feat_m = re.search(r'features:\s*\[(.*?)\]', line)
            if feat_m:
                for fname in feat_m.group(1).split(","):
                    fname = fname.strip()
                    if not any(f["name"] == fname for f in current_module.features):
                        current_module.features.append({"name": fname, "level": "P0", "keywords": [], "spec_ref": "", "testpoints": []})

        if current_module:
            modules.append(current_module)

        # 如果没有解析到模块，创建默认模块
        if not modules:
            # 尝试从 spec 文本提取
            design_name = "auto_module"
            m = re.search(r'(?:design_name|module_name)[：:]\s*["\']?(\w+)', md_text)
            if m:
                design_name = m.group(1)
            modules.append(ParsedModule(name=design_name, description="自动提取"))

        return modules

    def match_req_to_features(self, requirements: List[dict], modules: List[ParsedModule]) -> List[dict]:
        """需求→功能点 关键词自动匹配"""
        mappings = []

        for req in requirements:
            req_id = req.get("id", "")
            req_desc = req.get("description", "")
            req_text = f"{req_id} {req_desc}".lower()
            matched = False

            for module in modules:
                for feat in module.features:
                    # 获取功能点关键词
                    keywords = feat.get("keywords", [])
                    if not keywords:
                        # 自动从功能点名提取关键词
                        feat_name = feat.get("name", "").lower()
                        keywords = feat_name.split("_") + feat_name.split("-") + [feat_name]

                    # 匹配
                    for kw in keywords:
                        if kw.lower() in req_text:
                            mappings.append({
                                "req_id": req_id,
                                "module_name": module.name,
                                "feature_name": feat.get("name", ""),
                                "feature_level": feat.get("level", "P0"),
                                "testpoints": feat.get("testpoints", []),
                                "mapping_type": "DIRECT",
                                "confidence": 0.9,
                                "mapped_by": "auto",
                            })
                            matched = True
                            break
                    if matched:
                        break

                    # 关键词库匹配
                    for category, kws in FEATURE_KEYWORDS.items():
                        if any(kw.lower() in req_text for kw in kws) and any(kw.lower() in feat.get("name", "").lower() for kw in kws):
                            mappings.append({
                                "req_id": req_id,
                                "module_name": module.name,
                                "feature_name": feat.get("name", ""),
                                "feature_level": feat.get("level", "P0"),
                                "testpoints": feat.get("testpoints", []),
                                "mapping_type": "INFERRED",
                                "confidence": 0.6,
                                "mapped_by": "auto",
                            })
                            matched = True
                            break
                    if matched:
                        break
                if matched:
                    break

            if not matched:
                mappings.append({
                    "req_id": req_id,
                    "module_name": "",
                    "feature_name": "",
                    "feature_level": "",
                    "testpoints": [],
                    "mapping_type": "UNMAPPED",
                    "confidence": 0,
                    "mapped_by": "",
                })

        return mappings

    def generate_report(self, requirements: List[dict], modules: List[ParsedModule], testpoints: List[dict] = None) -> MappingReport:
        """生成完整的三层映射报告"""
        mappings = self.match_req_to_features(requirements, modules)
        mapped = [m for m in mappings if m["mapping_type"] != "UNMAPPED"]
        unmapped = [m for m in mappings if m["mapping_type"] == "UNMAPPED"]

        all_features = [f for mod in modules for f in mod.features]
        all_testpoints = set()
        for m in mapped:
            for tp in m.get("testpoints", []):
                all_testpoints.add(tp)

        report = MappingReport(
            total_requirements=len(requirements),
            mapped_requirements=len(mapped),
            unmapped_requirements=[m["req_id"] for m in unmapped],
            total_modules=len(modules),
            total_features=len(all_features),
            total_testpoints=len(all_testpoints) + len(testpoints or []),
            mapping_matrix=mappings,
            coverage_by_layer={
                "req_to_module": round(len(mapped) / max(len(requirements), 1) * 100, 1),
                "module_to_feature": round(len(all_features) / max(len(modules) * 2, 1) * 100, 1),
                "feature_to_testpoint": round(len(all_testpoints) / max(len(all_features), 1) * 100, 1),
            },
        )
        return report

    async def store(self, project_id: int, modules: List[ParsedModule], mappings: List[dict]) -> dict:
        """将模块/功能点/映射写入数据库"""
        from src.database.connection import get_session
        from src.database.models import DesignModule, DesignFeature, ReqFeatureMap, FeatureTestpointMap
        from sqlalchemy import select

        s = await get_session()
        stored = {"modules": 0, "features": 0, "mappings": 0}

        for mod in modules:
            dm = DesignModule(
                project_id=project_id, name=mod.name, parent_id=None,
                description=mod.description, interfaces=mod.interfaces,
                signals=mod.signals, rtl_file=mod.rtl_file, rtl_hash=mod.rtl_hash,
            )
            s.add(dm)
            await s.flush()
            stored["modules"] += 1

            for feat in mod.features:
                df = DesignFeature(
                    module_id=dm.id, name=feat.get("name", ""),
                    level=feat.get("level", "P0"), description=feat.get("description", ""),
                    keywords=",".join(feat.get("keywords", [])),
                    spec_feature_ref=feat.get("spec_ref", ""),
                )
                s.add(df)
                await s.flush()
                stored["features"] += 1

                # 功能点→测试点 映射
                for tp_id in feat.get("testpoints", []):
                    s.add(FeatureTestpointMap(feature_id=df.id, testpoint_id=tp_id))

        # 需求→功能点 映射
        for m in mappings:
            if m.get("mapping_type") == "UNMAPPED":
                continue
            # 找到对应的 feature
            feat_result = await s.execute(
                select(DesignFeature).where(DesignFeature.name == m.get("feature_name", ""))
            )
            feat = feat_result.scalars().first()
            if feat:
                s.add(ReqFeatureMap(
                    req_id=m["req_id"], feature_id=feat.id,
                    mapping_type=m.get("mapping_type", "DIRECT"),
                    confidence=m.get("confidence", 1.0),
                    mapped_by=m.get("mapped_by", "auto"),
                ))
                stored["mappings"] += 1

        await s.commit()
        await s.close()
        return stored

    async def get_mapping_report(self, project_id: int) -> dict:
        """从数据库读取三层映射报告"""
        from src.database.connection import get_session
        from src.database.models import DesignModule, DesignFeature, ReqFeatureMap, FeatureTestpointMap
        from sqlalchemy import select

        s = await get_session()
        modules = (await s.execute(select(DesignModule).where(DesignModule.project_id == project_id))).scalars().all()
        features = (await s.execute(select(DesignFeature))).scalars().all()
        mappings = (await s.execute(select(ReqFeatureMap))).scalars().all()
        tp_maps = (await s.execute(select(FeatureTestpointMap))).scalars().all()

        total_reqs = len(set(m.req_id for m in mappings))
        total_modules = len(modules)
        total_features = len(features)
        total_testpoints = len(set(tp.testpoint_id for tp in tp_maps))

        matrix = []
        for m in mappings:
            feat = next((f for f in features if f.id == m.feature_id), None)
            mod = next((mod for mod in modules if feat and mod.id == feat.module_id), None)
            tps = [tp.testpoint_id for tp in tp_maps if tp.feature_id == m.feature_id]
            matrix.append({
                "req_id": m.req_id,
                "module_name": mod.name if mod else "",
                "feature_name": feat.name if feat else "",
                "feature_level": feat.level if feat else "",
                "testpoints": tps,
                "mapping_type": m.mapping_type,
                "confidence": m.confidence,
            })

        await s.close()
        return {
            "project_id": project_id,
            "mapping_matrix": matrix,
            "stats": {
                "total_reqs": total_reqs,
                "total_modules": total_modules,
                "total_features": total_features,
                "total_testpoints": total_testpoints,
                "mapped_reqs": len(set(m.req_id for m in mappings if m.mapping_type != "UNMAPPED")),
                "coverage": round(len(set(m.req_id for m in mappings)) / max(total_reqs, 1) * 100, 1),
            },
        }
