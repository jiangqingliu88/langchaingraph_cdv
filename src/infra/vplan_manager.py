# src/infra/vplan_manager.py
"""
验证计划管理器 - vPlan 导入/导出 + 需求追踪矩阵
"""

from typing import Dict, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
import csv
import io


# ==================== 数据模型 ====================

class RequirementStatus(Enum):
    NOT_STARTED = "not_started"     # 未开始
    IN_PROGRESS = "in_progress"     # 进行中
    VERIFIED = "verified"           # 已验证
    BLOCKED = "blocked"             # 阻塞
    WAIVED = "waived"               # 豁免


class TestStatus(Enum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"


@dataclass
class Requirement:
    """需求项 —— 支持 Chip/ST/IT/BT/UT 五级层级"""
    id: str
    description: str
    priority: str = "P1"
    category: str = "functional"
    owner: str = ""
    status: RequirementStatus = RequirementStatus.NOT_STARTED
    level: str = "bt"                # chip / st / it / bt / ut
    parent_id: str = ""              # 上级需求 ID（chip 级为空）
    children_ids: List[str] = field(default_factory=list)
    doc_path: str = ""               # 关联的 MD 规格文档路径，如 specs/uart_spec.md

    # 关联
    test_ids: List[str] = field(default_factory=list)
    coverage_goal: float = 100.0
    coverage_actual: float = 0.0
    assertions: List[str] = field(default_factory=list)


@dataclass
class TestCase:
    """测试用例"""
    id: str
    name: str
    description: str
    status: TestStatus = TestStatus.NOT_RUN
    requirement_ids: List[str] = field(default_factory=list)  # 关联的需求


@dataclass
class TraceabilityMatrix:
    """需求追踪矩阵"""
    requirements: Dict[str, Requirement] = field(default_factory=dict)
    testcases: Dict[str, TestCase] = field(default_factory=dict)
    
    def get_matrix(self) -> List[Dict]:
        """生成追踪矩阵"""
        rows = []
        for req_id, req in self.requirements.items():
            row = {
                "requirement_id": req_id,
                "requirement_desc": req.description,
                "priority": req.priority,
                "status": req.status.value,
                "tests": [],
                "coverage_goal": req.coverage_goal,
                "coverage_actual": req.coverage_actual,
                "gap": req.coverage_goal - req.coverage_actual,
            }
            for test_id in req.test_ids:
                test = self.testcases.get(test_id)
                if test:
                    row["tests"].append({
                        "test_id": test_id,
                        "test_name": test.name,
                        "status": test.status.value,
                    })
            rows.append(row)
        return rows
    
    def get_uncovered_requirements(self) -> List[Requirement]:
        """获取未覆盖的需求"""
        return [r for r in self.requirements.values() 
                if not r.test_ids or r.coverage_actual < r.coverage_goal]
    
    def get_summary(self) -> Dict:
        """获取追踪汇总"""
        total = len(self.requirements)
        verified = sum(1 for r in self.requirements.values() 
                      if r.status == RequirementStatus.VERIFIED)
        uncovered = len(self.get_uncovered_requirements())
        return {
            "total_requirements": total,
            "verified": verified,
            "uncovered": uncovered,
            "verification_rate": f"{verified/total*100:.1f}%" if total > 0 else "0%",
            "coverage_rate": self._calc_coverage(),
        }
    
    def _calc_coverage(self) -> str:
        total = sum(r.coverage_goal for r in self.requirements.values())
        actual = sum(r.coverage_actual for r in self.requirements.values())
        return f"{actual/total*100:.1f}%" if total > 0 else "0%"


# ==================== vPlan 管理器 ====================

class VPlanManager:
    """验证计划管理器"""
    
    def __init__(self):
        self.matrix = TraceabilityMatrix()
        self.plan_name = ""
        self.version = "1.0"
        self.created_at = datetime.now().isoformat()
    
    # ==================== 需求管理 ====================
    
    def add_requirement(self, req_id: str, description: str,
                        priority: str = "P1", category: str = "functional",
                        level: str = "bt", parent_id: str = "", doc_path: str = "") -> Requirement:
        req = Requirement(id=req_id, description=description,
                         priority=priority, category=category,
                         level=level, parent_id=parent_id, doc_path=doc_path)
        if parent_id and parent_id in self.matrix.requirements:
            self.matrix.requirements[parent_id].children_ids.append(req_id)
        self.matrix.requirements[req_id] = req
        return req
    
    def add_testcase(self, test_id: str, name: str, description: str) -> TestCase:
        test = TestCase(id=test_id, name=name, description=description)
        self.matrix.testcases[test_id] = test
        return test
    
    def link_requirement_test(self, req_id: str, test_id: str):
        """关联需求和测试用例"""
        if req_id in self.matrix.requirements and test_id in self.matrix.testcases:
            self.matrix.requirements[req_id].test_ids.append(test_id)
            self.matrix.testcases[test_id].requirement_ids.append(req_id)
    
    def update_test_status(self, test_id: str, status: TestStatus):
        """更新测试状态"""
        if test_id in self.matrix.testcases:
            self.matrix.testcases[test_id].status = status
            
            # 自动更新关联需求的状态
            for req_id in self.matrix.testcases[test_id].requirement_ids:
                self._update_requirement_status(req_id)
    
    def update_coverage(self, req_id: str, coverage: float):
        """更新需求覆盖率"""
        if req_id in self.matrix.requirements:
            self.matrix.requirements[req_id].coverage_actual = coverage
            if coverage >= self.matrix.requirements[req_id].coverage_goal:
                self.matrix.requirements[req_id].status = RequirementStatus.VERIFIED
    
    def _update_requirement_status(self, req_id: str):
        """根据关联测试状态更新需求状态"""
        req = self.matrix.requirements.get(req_id)
        if not req or not req.test_ids:
            return
        
        all_passed = all(
            self.matrix.testcases[tid].status == TestStatus.PASSED
            for tid in req.test_ids
            if tid in self.matrix.testcases
        )
        
        if all_passed and req.coverage_actual >= req.coverage_goal:
            req.status = RequirementStatus.VERIFIED
        elif any(self.matrix.testcases[tid].status == TestStatus.FAILED 
                for tid in req.test_ids if tid in self.matrix.testcases):
            req.status = RequirementStatus.IN_PROGRESS
    
    # ==================== 层级管理 ====================

    LEVEL_NAMES = {"chip": "芯片级(Chip)", "st": "系统级(ST)", "it": "集成级(IT)",
                   "bt": "模块级(BT)", "ut": "单元级(UT)"}
    LEVEL_ORDER = ["chip", "st", "it", "bt", "ut"]

    def get_requirements_by_level(self, level: str) -> List[Requirement]:
        return [r for r in self.matrix.requirements.values() if r.level == level]

    def get_children(self, req_id: str) -> List[Requirement]:
        req = self.matrix.requirements.get(req_id)
        if not req: return []
        return [self.matrix.requirements[cid] for cid in req.children_ids if cid in self.matrix.requirements]

    def get_hierarchy(self) -> List[dict]:
        """构建完整层级树，含每级统计数据"""
        def _calc_coverage(reqs: List[Requirement]) -> float:
            if not reqs: return 0.0
            return round(sum(r.coverage_actual for r in reqs) / max(len(reqs), 1), 1)

        def _node(level: str, parent_id: str = "", name: str = "") -> dict:
            reqs = [r for r in self.matrix.requirements.values()
                    if r.level == level and (parent_id == "" or r.parent_id == parent_id)]
            if not reqs and level != "chip":
                return None
            verified = sum(1 for r in reqs if r.status == RequirementStatus.VERIFIED)
            blocked = sum(1 for r in reqs if r.status == RequirementStatus.BLOCKED)
            cov = _calc_coverage(reqs)
            node = {
                "level": level, "name": name or self.LEVEL_NAMES.get(level, level),
                "req_count": len(reqs), "verified": verified, "blocked": blocked,
                "coverage": cov,
                "requirements": [self._req_to_dict(r) for r in reqs],
                "children": []
            }
            # 递归构建子节点
            for r in reqs:
                child = _node(self._child_level(level), r.id, r.description)
                if child:
                    node["children"].append(child)
            return node

        def _all_of_level(level: str) -> List[Requirement]:
            return [r for r in self.matrix.requirements.values() if r.level == level]

        # Chip 级根节点
        chip_reqs = _all_of_level("chip")
        if not chip_reqs:
            # 如果没有 chip 级需求，将所有无 parent 的顶级需求作为根
            chip_reqs = [r for r in self.matrix.requirements.values() if not r.parent_id]
            if not chip_reqs:
                all_reqs = list(self.matrix.requirements.values())
                root = {
                    "level": "chip", "name": self.LEVEL_NAMES["chip"],
                    "req_count": len(all_reqs), "verified": sum(1 for r in all_reqs if r.status == RequirementStatus.VERIFIED),
                    "blocked": sum(1 for r in all_reqs if r.status == RequirementStatus.BLOCKED),
                    "coverage": _calc_coverage(all_reqs),
                    "requirements": [self._req_to_dict(r) for r in all_reqs],
                    "children": []
                }
                return [root]

        result = []
        for r in chip_reqs:
            node = {
                "level": "chip", "name": r.description,
                "req_id": r.id,
                "req_count": 1, "verified": 1 if r.status == RequirementStatus.VERIFIED else 0,
                "blocked": 1 if r.status == RequirementStatus.BLOCKED else 0,
                "coverage": r.coverage_actual,
                "requirements": [self._req_to_dict(r)],
                "children": []
            }
            # 递归构建 ST → IT → BT → UT
            st_reqs = [r2 for r2 in self.matrix.requirements.values() if r2.level == "st" and r2.parent_id == r.id]
            for st in st_reqs:
                st_node = self._build_branch(st)
                if st_node: node["children"].append(st_node)
            result.append(node)
        return result

    def _build_branch(self, req: Requirement) -> dict:
        """递归构建一个需求节点及其下级"""
        level_order = {"st": "it", "it": "bt", "bt": "ut"}
        children = self.get_children(req.id)
        child_reqs = [r for r in self.matrix.requirements.values() if r.parent_id == req.id]

        node = {
            "level": req.level, "name": req.description,
            "req_id": req.id,
            "req_count": 1 + len(child_reqs),  # 本节点 + 下级全部
            "verified": (1 if req.status == RequirementStatus.VERIFIED else 0),
            "blocked": (1 if req.status == RequirementStatus.BLOCKED else 0),
            "coverage": req.coverage_actual,
            "requirements": [self._req_to_dict(req)],
            "children": []
        }
        next_level = level_order.get(req.level)
        if next_level:
            for child in [r for r in self.matrix.requirements.values()
                          if r.level == next_level and r.parent_id == req.id]:
                child_node = self._build_branch(child)
                if child_node:
                    node["children"].append(child_node)
                    node["req_count"] += child_node["req_count"]
                    node["verified"] += child_node["verified"]
                    node["blocked"] += child_node["blocked"]
        # 重新计算覆盖率（包含子节点）
        all_ids = [req.id] + self._all_descendant_ids(req.id)
        all_reqs = [self.matrix.requirements[rid] for rid in all_ids if rid in self.matrix.requirements]
        if all_reqs:
            node["coverage"] = round(sum(r.coverage_actual for r in all_reqs) / len(all_reqs), 1)
        return node

    def _all_descendant_ids(self, req_id: str) -> List[str]:
        ids = []
        for r in self.matrix.requirements.values():
            if r.parent_id == req_id:
                ids.append(r.id)
                ids.extend(self._all_descendant_ids(r.id))
        return ids

    def _child_level(self, level: str) -> str:
        return {"chip": "st", "st": "it", "it": "bt", "bt": "ut"}.get(level, "")

    def _req_to_dict(self, r: Requirement) -> dict:
        return {
            "id": r.id, "description": r.description, "priority": r.priority,
            "category": r.category, "level": r.level, "parent_id": r.parent_id,
            "status": r.status.value, "test_ids": r.test_ids,
            "coverage_goal": r.coverage_goal, "coverage_actual": r.coverage_actual,
            "doc_path": r.doc_path,
        }

    # ==================== 导入 ====================
    
    def import_from_csv(self, csv_content: str):
        """从 CSV 导入需求"""
        reader = csv.DictReader(io.StringIO(csv_content))
        for row in reader:
            self.add_requirement(
                req_id=row.get("id", ""),
                description=row.get("description", ""),
                priority=row.get("priority", "P1"),
                category=row.get("category", "functional"),
            )
    
    def import_from_excel(self, file_path: str):
        """从 Excel 导入（需要 openpyxl）"""
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_path)
            ws = wb.active
            
            headers = [cell.value for cell in ws[1]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                data = dict(zip(headers, row))
                self.add_requirement(
                    req_id=str(data.get("id", "")),
                    description=str(data.get("description", "")),
                    priority=str(data.get("priority", "P1")),
                    category=str(data.get("category", "functional")),
                )
            return {"imported": ws.max_row - 1}
        except ImportError:
            return {"error": "需要安装 openpyxl: pip install openpyxl"}
    
    def import_from_yaml(self, yaml_content: str):
        """从 YAML 导入"""
        import yaml
        data = yaml.safe_load(yaml_content)
        for req in data.get("requirements", []):
            self.add_requirement(
                req_id=req["id"],
                description=req["description"],
                priority=req.get("priority", "P1"),
                category=req.get("category", "functional"),
            )
    
    def import_from_json(self, json_content: str):
        """从 JSON 导入"""
        data = json.loads(json_content) if isinstance(json_content, str) else json_content
        for req in data.get("requirements", []):
            self.add_requirement(
                req_id=req["id"],
                description=req["description"],
                priority=req.get("priority", "P1"),
                category=req.get("category", "functional"),
            )
    
    # ==================== 导出 ====================
    
    def export_to_csv(self) -> str:
        """导出为 CSV"""
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["ID", "Description", "Priority", "Category", 
                         "Status", "Tests", "Coverage", "Gap"])
        
        for req_id, req in self.matrix.requirements.items():
            writer.writerow([
                req_id, req.description, req.priority, req.category,
                req.status.value,
                ",".join(req.test_ids),
                f"{req.coverage_actual:.1f}%",
                f"{req.coverage_goal - req.coverage_actual:.1f}%",
            ])
        
        return output.getvalue()
    
    def export_to_json(self) -> str:
        """导出为 JSON"""
        return json.dumps({
            "plan_name": self.plan_name,
            "version": self.version,
            "requirements": [
                {
                    "id": r.id,
                    "description": r.description,
                    "priority": r.priority,
                    "status": r.status.value,
                    "tests": r.test_ids,
                    "coverage": r.coverage_actual,
                }
                for r in self.matrix.requirements.values()
            ],
            "testcases": [
                {
                    "id": t.id,
                    "name": t.name,
                    "status": t.status.value,
                    "requirements": t.requirement_ids,
                }
                for t in self.matrix.testcases.values()
            ],
        }, indent=2, ensure_ascii=False)
    
    def export_traceability_matrix(self) -> str:
        """导出需求追踪矩阵"""
        return json.dumps({
            "summary": self.matrix.get_summary(),
            "matrix": self.matrix.get_matrix(),
            "uncovered": [
                {"id": r.id, "description": r.description, "priority": r.priority}
                for r in self.matrix.get_uncovered_requirements()
            ],
        }, indent=2, ensure_ascii=False)
    
    def export_report(self) -> str:
        """生成验证计划报告"""
        summary = self.matrix.get_summary()
        uncovered = self.matrix.get_uncovered_requirements()
        
        report = {
            "title": f"验证计划报告 - {self.plan_name}",
            "version": self.version,
            "generated_at": datetime.now().isoformat(),
            "summary": summary,
            "uncovered_requirements": len(uncovered),
            "uncovered_detail": [
                {"id": r.id, "desc": r.description, "gap": f"{r.coverage_goal - r.coverage_actual:.1f}%"}
                for r in uncovered
            ],
            "recommendations": self._generate_recommendations(uncovered),
        }
        return json.dumps(report, indent=2, ensure_ascii=False)
    
    def _generate_recommendations(self, uncovered: List[Requirement]) -> List[str]:
        recs = []
        for r in uncovered:
            if not r.test_ids:
                recs.append(f"需求 {r.id} ({r.description}) 没有关联测试用例，请添加")
            elif r.coverage_actual < r.coverage_goal:
                recs.append(f"需求 {r.id} 覆盖率 {r.coverage_actual:.1f}% < 目标 {r.coverage_goal:.1f}%，请补充测试")
        return recs if recs else ["所有需求已覆盖"]


# ==================== 使用示例 ====================

if __name__ == "__main__":
    vplan = VPlanManager()
    vplan.plan_name = "UART 验证计划"
    
    # 添加需求
    vplan.add_requirement("REQ_001", "UART 基本发送功能", "P0")
    vplan.add_requirement("REQ_002", "UART 基本接收功能", "P0")
    vplan.add_requirement("REQ_003", "奇偶校验错误检测", "P1")
    vplan.add_requirement("REQ_004", "FIFO 溢出处理", "P1")
    
    # 添加测试用例
    vplan.add_testcase("test_001", "test_uart_basic_tx", "基本发送测试")
    vplan.add_testcase("test_002", "test_uart_basic_rx", "基本接收测试")
    vplan.add_testcase("test_003", "test_uart_parity_error", "奇偶校验错误测试")
    
    # 关联
    vplan.link_requirement_test("REQ_001", "test_001")
    vplan.link_requirement_test("REQ_002", "test_002")
    vplan.link_requirement_test("REQ_003", "test_003")
    
    # 更新测试状态
    vplan.update_test_status("test_001", TestStatus.PASSED)
    vplan.update_test_status("test_002", TestStatus.PASSED)
    
    # 更新覆盖率
    vplan.update_coverage("REQ_001", 100)
    vplan.update_coverage("REQ_002", 100)
    
    # 导出追踪矩阵
    print(vplan.export_traceability_matrix())
    
    # 导出报告
    print(vplan.export_report())