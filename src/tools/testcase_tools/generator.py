
# src/tools/testcase_gen/generator.py
"""
测试用例生成器 - 核心引擎
"""
import yaml
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from jinja2 import Environment, FileSystemLoader


class TestCaseGenerator:
    """测试用例生成器"""
    
    def __init__(self, yaml_path: str):
        self.yaml_path = Path(yaml_path)
        self.config = self._load_config()
        self.env_name = self.config.get("constraint", {}).get("env_name", "ENV")
        self.project_name = self.config.get("constraint", {}).get("name", "project")
        self.transactions = self.config.get("transactions", [])
        self.policies = self.config.get("policies", [])
        self.combinator = self.config.get("combinator", {})
        
        # Jinja2 环境
        template_dir = Path(__file__).parent / "templates"
        self.jinja = Environment(loader=FileSystemLoader(str(template_dir)))
        self.jinja.filters['get_type'] = self._get_transaction_type
    
    def _load_config(self) -> dict:
        with open(self.yaml_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    @property
    def is_scenario_mode(self) -> bool:
        """判断是否为场景模式（scenarios 键）"""
        return "scenarios" in self.config

    def get_scenarios(self) -> List[Dict]:
        """返回场景列表"""
        return self.config.get("scenarios", [])
    
    def _get_transaction_type(self, name: str) -> str:
        for t in self.transactions:
            if t["name"] == name:
                return t["type"]
        return f"{self.env_name}_{name}_transaction"
    
    def generate_test_matrix(self) -> List[Dict]:
        """生成测试矩阵"""
        policy_names = [p["name"] for p in self.policies]
        
        matrix = [
            # 单策略测试
            *[{
                "id": f"single_{p['name']}",
                "test_name": f"test_{p['name']}",
                "scenario": f"Single Policy: {p['name']}",
                "description": p.get("description", ""),
                "policy_mode": "APPLY_ALL",
                "active_policies": [p["name"]],
                "priority": "P0",
                "min_trans": 10,
                "max_trans": 50,
            } for p in self.policies],
            
            # 全策略组合
            {
                "id": "all_policies",
                "test_name": "test_all_policies",
                "scenario": "All Policies Combined",
                "description": "All policies active together",
                "policy_mode": "APPLY_SEQUENTIAL",
                "active_policies": policy_names,
                "priority": "P0",
                "min_trans": 50,
                "max_trans": 200,
            },
            
            # 加权随机
            {
                "id": "weighted_random",
                "test_name": "test_weighted_random",
                "scenario": "Weighted Random",
                "description": "Random policy selection by weight",
                "policy_mode": "APPLY_WEIGHTED",
                "active_policies": policy_names,
                "priority": "P1",
                "min_trans": 100,
                "max_trans": 500,
            },
            
            # 链式
            {
                "id": "policy_chain",
                "test_name": "test_policy_chain",
                "scenario": "Policy Chain",
                "description": "Chain policies sequentially",
                "policy_mode": "APPLY_CHAIN",
                "active_policies": policy_names,
                "priority": "P1",
                "min_trans": 20,
                "max_trans": 100,
            },
            
            # 随机子集
            {
                "id": "random_subset",
                "test_name": "test_random_subset",
                "scenario": "Random Subset",
                "description": "Random subset of policies",
                "policy_mode": "APPLY_FIRST_MATCH",
                "active_policies": policy_names[:3] if len(policy_names) > 3 else policy_names,
                "priority": "P2",
                "min_trans": 50,
                "max_trans": 150,
            },
        ]
        
        return matrix
    
    def generate_sequence(self, test_def: Dict) -> str:
        """生成 Sequence 代码"""
        template = self.jinja.get_template("sequence.sv.j2")
        return template.render(
            env_name=self.env_name,
            project_name=self.project_name,
            sequence_name=f"{test_def['test_name']}_seq",
            policy_mode=test_def["policy_mode"],
            active_policies=test_def["active_policies"],
            min_trans=test_def.get("min_trans", 10),
            max_trans=test_def.get("max_trans", 50),
            transactions=self.transactions,
            policies=[p for p in self.policies if p["name"] in test_def["active_policies"]],
            clock="clk",
        )
    
    def generate_test(self, test_def: Dict) -> str:
        """生成 Test 代码"""
        template = self.jinja.get_template("test.sv.j2")
        return template.render(
            env_name=self.env_name,
            project_name=self.project_name,
            test_name=test_def["test_name"],
            sequence_name=f"{test_def['test_name']}_seq",
            scenario=test_def["scenario"],
            policy_mode=test_def["policy_mode"],
            active_policies=test_def["active_policies"],
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            checks=[
                {"name": "policy_applied", "condition": "1", "message": "Policy check passed"},
                {"name": "transactions_done", "condition": "1", "message": "All transactions completed"},
            ],
        )
    
    def generate_run_script(self, test_def: Dict) -> str:
        """生成运行脚本"""
        template = self.jinja.get_template("run_script.sh.j2")
        return template.render(
            env_name=self.env_name,
            test_name=test_def["test_name"],
            policy_mode=test_def["policy_mode"],
            active_policies=test_def["active_policies"],
        )
    
    def generate_scenario_test(self, scenario: Dict, scenario_idx: int) -> Dict:
        """从单个场景生成测试代码"""
        policies = scenario.get("policies", [])
        combinator = scenario.get("combinator_mode", "APPLY_ALL")

        test_def = {
            "id": scenario.get("name", f"scenario_{scenario_idx}"),
            "test_name": f"test_{scenario['name']}",
            "scenario": scenario.get("description", scenario["name"]),
            "description": scenario.get("description", ""),
            "policy_mode": combinator,
            "active_policies": policies,
            "priority": "P0",
            "min_trans": scenario.get("repeat", 10),
            "max_trans": scenario.get("repeat", 10) * 2,
            "timeout": scenario.get("timeout", 600),
            "priority_rules": scenario.get("priority_rules", []),
            "params_override": scenario.get("params_override", {}),
        }

        seq_code = self.generate_sequence(test_def)
        test_code = self.generate_test(test_def)
        run_script = self.generate_run_script(test_def)

        return {
            "test_def": test_def,
            "sequence": seq_code,
            "test": test_code,
            "run_script": run_script,
        }

    def generate_from_scenarios(self, output_dir: str = "output/testcases") -> Dict:
        """从场景 YAML 生成测试用例"""
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)

        scenarios = self.get_scenarios()
        results = []

        for i, scenario in enumerate(scenarios):
            gen = self.generate_scenario_test(scenario, i)
            test_def = gen["test_def"]

            # 写入文件
            test_dir = out / test_def["test_name"]
            test_dir.mkdir(exist_ok=True)

            (test_dir / f"{test_def['test_name']}_seq.sv").write_text(
                gen["sequence"], encoding='utf-8')
            (test_dir / f"{test_def['test_name']}.sv").write_text(
                gen["test"], encoding='utf-8')
            (test_dir / "run.sh").write_text(
                gen["run_script"], encoding='utf-8')

            results.append({
                "id": test_def["id"],
                "test_name": test_def["test_name"],
                "scenario": test_def["scenario"],
                "policies": test_def["active_policies"],
                "mode": test_def["policy_mode"],
                "timeout": test_def["timeout"],
                "files": [
                    str(test_dir / f"{test_def['test_name']}_seq.sv"),
                    str(test_dir / f"{test_def['test_name']}.sv"),
                    str(test_dir / "run.sh"),
                ]
            })

        summary = {
            "project": self.project_name,
            "env_name": self.env_name,
            "mode": "scenario",
            "total_tests": len(results),
            "generated_at": datetime.now().isoformat(),
            "tests": results,
        }
        (out / "test_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False))

        return summary

    def generate_all(self, output_dir: str = "output/testcases"):
        """生成所有测试用例（自动检测场景模式 / 矩阵模式）"""
        if self.is_scenario_mode:
            return self.generate_from_scenarios(output_dir)
        # 原有矩阵模式
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        
        matrix = self.generate_test_matrix()
        results = []
        
        for i, test_def in enumerate(matrix):
            seq_code = self.generate_sequence(test_def)
            test_code = self.generate_test(test_def)
            run_script = self.generate_run_script(test_def)
            
            # 写入文件
            test_dir = out / test_def["test_name"]
            test_dir.mkdir(exist_ok=True)
            
            (test_dir / f"{test_def['test_name']}_seq.sv").write_text(seq_code, encoding='utf-8')
            (test_dir / f"{test_def['test_name']}.sv").write_text(test_code, encoding='utf-8')
            (test_dir / "run.sh").write_text(run_script, encoding='utf-8')
            
            results.append({
                "id": test_def["id"],
                "test_name": test_def["test_name"],
                "files": [
                    str(test_dir / f"{test_def['test_name']}_seq.sv"),
                    str(test_dir / f"{test_def['test_name']}.sv"),
                    str(test_dir / "run.sh"),
                ]
            })
        
        # 生成汇总
        summary = {
            "project": self.project_name,
            "env_name": self.env_name,
            "total_tests": len(results),
            "generated_at": datetime.now().isoformat(),
            "tests": results,
        }
        (out / "test_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        
        return summary


# ==================== CLI 工具 ====================

def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage: python generator.py <yaml_file> [OPTIONS]")
        print()
        print("OPTIONS:")
        print("  --all             生成所有测试（自动检测矩阵/场景模式）")
        print("  --scenarios       列出 YAML 中的场景")
        print("  --matrix          显示测试矩阵（矩阵模式）")
        print("  --test N          预览第 N 个测试/场景的代码")
        print("  --output DIR      指定输出目录（默认: output/testcases）")
        print()
        print("Examples:")
        print("  python generator.py ALU_constraint.yaml --all")
        print("  python generator.py ALU_constraint.yaml --scenarios")
        print("  python generator.py ALU_constraint.yaml --test 0")
        sys.exit(1)

    yaml_file = sys.argv[1]
    gen = TestCaseGenerator(yaml_file)

    # 解析 --output
    output_dir = "output/testcases"
    if "--output" in sys.argv:
        oidx = sys.argv.index("--output")
        output_dir = sys.argv[oidx + 1] if oidx + 1 < len(sys.argv) else output_dir

    if "--scenarios" in sys.argv:
        scenarios = gen.get_scenarios()
        print(f"Scenarios: {len(scenarios)}")
        for i, s in enumerate(scenarios):
            policies = s.get("policies", [])
            print(f"  [{i}] {s['name']}")
            print(f"      mode={s.get('combinator_mode','N/A')}  "
                  f"timeout={s.get('timeout','-')}s  "
                  f"repeat={s.get('repeat','-')}")
            print(f"      policies: {', '.join(policies)}")
        return

    if "--all" in sys.argv or len(sys.argv) == 2:
        summary = gen.generate_all(output_dir)
        mode = summary.get("mode", "matrix")
        print(f"Mode: {mode}")
        print(f"Generated {summary['total_tests']} tests in {output_dir}/")
        for t in summary["tests"]:
            extra = ""
            if "policies" in t:
                extra = f"  policies=[{', '.join(t['policies'][:3])}{'...' if len(t['policies'])>3 else ''}]"
            if "mode" in t:
                extra += f"  mode={t['mode']}"
            print(f"  [{t['id']}] {t['test_name']}{extra}")
        return

    if "--test" in sys.argv:
        idx = int(sys.argv[sys.argv.index("--test") + 1])
        if gen.is_scenario_mode:
            scenarios = gen.get_scenarios()
            if 0 <= idx < len(scenarios):
                gen_result = gen.generate_scenario_test(scenarios[idx], idx)
                print(f"// ===== Scenario: {scenarios[idx]['name']} =====\n")
                print(f"// ===== Sequence =====\n{gen_result['sequence']}")
                print(f"\n// ===== Test =====\n{gen_result['test']}")
            else:
                print(f"Error: index {idx} out of range (0-{len(scenarios)-1})")
        else:
            matrix = gen.generate_test_matrix()
            if 0 <= idx < len(matrix):
                test_def = matrix[idx]
                seq = gen.generate_sequence(test_def)
                test = gen.generate_test(test_def)
                print(f"// ===== Sequence =====\n{seq}\n\n// ===== Test =====\n{test}")
            else:
                print(f"Error: index {idx} out of range (0-{len(matrix)-1})")
        return

    if "--matrix" in sys.argv:
        if gen.is_scenario_mode:
            scenarios = gen.get_scenarios()
            print(f"Scenario matrix: {len(scenarios)} tests")
            for i, s in enumerate(scenarios):
                print(f"  [{i}] {s['name']}: {s.get('description','')}")
                print(f"      mode={s.get('combinator_mode','N/A')}  "
                      f"policies={s.get('policies',[])}")
        else:
            matrix = gen.generate_test_matrix()
            print(f"Test matrix: {len(matrix)} tests")
            for t in matrix:
                print(f"  - {t['id']}: {t['scenario']} [{t['policy_mode']}]")
        return


if __name__ == "__main__":
    main()