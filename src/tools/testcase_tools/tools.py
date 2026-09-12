"""
测试用例工具集 —— 供 TestAgent 调用

  parse_test_points     — spec JSON → 结构化 test 列表
  map_policies_to_tests — test 分类 → 策略场景映射（通用，按 spec.features 推断）
  build_scenario_yaml   — 场景 JSON → 完整 constraint YAML
  build_priority_rules  — 策略列表 → 权重规则
  generate_test_cases   — YAML → SV 测试代码（调用 CLI）
  check_test_coverage   — 覆盖率检查
"""
import json, yaml, os, subprocess, tempfile
from datetime import datetime
from pathlib import Path
from typing import Dict

from langchain.tools import tool


# ═══════════════════════════════════════════════════════════════
# 通用策略推断 — 不硬编码模块名
# ═══════════════════════════════════════════════════════════════

def _infer_policies_from_features(features: list) -> list:
    """根据 spec.features 文本推断适用的约束策略（通用，不限模块类型）。"""
    feature_text = " ".join(str(f).lower() for f in features)

    policies = []
    # 寄存器 / 配置 → 配置一致性
    if any(kw in feature_text for kw in ["寄存器", "register", "配置", "config", "apb", "axi"]):
        policies.append("config_consistency")
    # 数据发送/接收 → 数据完整性
    if any(kw in feature_text for kw in ["发送", "接收", "transmit", "receive", "tx", "rx", "串行", "serial"]):
        policies.append("data_integrity")
    # FIFO / 缓冲区 → 容量边界
    if any(kw in feature_text for kw in ["fifo", "缓冲", "buffer", "满", "空", "溢出"]):
        policies.append("capacity_boundary")
    # 中断 → 事件触发
    if any(kw in feature_text for kw in ["中断", "interrupt", "irq", "事件"]):
        policies.append("event_trigger")
    # 波特率 / 时钟 / 频率 → 时序约束
    if any(kw in feature_text for kw in ["波特", "baud", "时钟", "clock", "频率", "时序", "timing"]):
        policies.append("timing_constraint")
    # 低功耗 → 功耗模式
    if any(kw in feature_text for kw in ["功耗", "power", "低功耗", "idle", "sleep"]):
        policies.append("power_mode")
    # 错误 / 异常 → 错误注入
    if any(kw in feature_text for kw in ["错误", "error", "异常", "fault", "注入", "inject"]):
        policies.append("error_injection")
    # 并发 / 多端口 → 并发访问
    if any(kw in feature_text for kw in ["并发", "concurrent", "多端口", "multi-port"]):
        policies.append("concurrent_access")
    # 回环 → 回环测试
    if any(kw in feature_text for kw in ["回环", "loopback", "loop"]):
        policies.append("loopback_test")

    # 始终包含基础策略
    if not policies:
        policies = ["basic_check", "random_stress"]
    return policies


def _infer_transactions_from_features(features: list, interfaces: list) -> list:
    """根据 spec.interfaces 和 features 推断 transaction 类型。"""
    transactions = []
    iface_names = [i.get("name", "").upper() for i in interfaces]
    feature_text = " ".join(str(f).lower() for f in features)

    if any("APB" in n for n in iface_names) or any(kw in feature_text for kw in ["寄存器", "register", "apb"]):
        transactions.append({"name": "reg_rw", "type": "register_access",
                            "desc": "Read/write configuration registers via bus"})
    if any("UART" in n for n in iface_names) or any(kw in feature_text for kw in ["uart", "串行", "serial", "tx", "rx"]):
        transactions.append({"name": "uart_frame", "type": "serial_frame",
                            "desc": "UART frame transmission/reception"})
    if any("INTR" in n for n in iface_names) or any(kw in feature_text for kw in ["中断", "interrupt", "irq"]):
        transactions.append({"name": "irq_event", "type": "interrupt_event",
                            "desc": "Interrupt request and service"})
    if any("AXI" in n for n in iface_names) or "axi" in feature_text:
        transactions.append({"name": "axi_burst", "type": "axi_transfer",
                            "desc": "AXI burst read/write transfer"})
    if any("SPI" in n for n in iface_names) or "spi" in feature_text:
        transactions.append({"name": "spi_transfer", "type": "spi_frame",
                            "desc": "SPI master/slave transfer"})

    if not transactions:
        transactions.append({"name": "generic_op", "type": "generic",
                            "desc": "Generic operation"})
    return transactions


def _infer_combinator(policies: list) -> dict:
    """根据策略数量推断 combinator 配置。"""
    return {
        "mode_sequence": "APPLY_SEQUENTIAL" if len(policies) <= 3 else "APPLY_WEIGHTED",
        "mode_all": "APPLY_ALL",
        "mode_single": "APPLY_FIRST_MATCH",
        "enable_chain": len(policies) >= 3,
        "enable_weighted": len(policies) >= 4,
    }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

@tool("parse_test_points")
def parse_test_points(spec_json: str) -> str:
    """从 spec JSON 提取 test_points，返回结构化测试列表。

    支持两种 spec 格式:
      1. 嵌套格式: test_points = [{category: "xxx", tests: [{name, description}, ...]}]
      2. 平铺格式: test_points = [{id, feature, priority, description, acceptance}, ...]
         → 按 feature 字段分组为 category
    """
    try:
        data = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON input"}, ensure_ascii=False)

    tp = data.get("test_points", data if isinstance(data, list) else [])
    if isinstance(tp, dict):
        tp = [tp]
    if not isinstance(tp, list) or len(tp) == 0:
        return json.dumps({"total_categories": 0, "total_tests": 0, "categories": []},
                          indent=2, ensure_ascii=False)

    first = tp[0]
    result = {"total_categories": 0, "total_tests": 0, "categories": []}

    # ---- 格式检测 ----
    is_flat = isinstance(first, dict) and "tests" not in first

    if is_flat:
        # ---- 平铺格式: 按 feature 字段分组 ----
        groups = {}  # feature → [test_points]
        for item in tp:
            if not isinstance(item, dict):
                continue
            feature = item.get("feature", item.get("category", "general"))
            groups.setdefault(feature, []).append(item)
        for feature, items in groups.items():
            cat_tests = []
            for it in items:
                cat_tests.append({
                    "name": it.get("id", it.get("name", "?")),
                    "description": it.get("description", ""),
                    "priority": it.get("priority", "P2"),
                    "acceptance": it.get("acceptance", ""),
                })
            result["total_tests"] += len(cat_tests)
            result["total_categories"] += 1
            result["categories"].append({
                "category": feature,
                "test_count": len(cat_tests),
                "tests": cat_tests,
            })
    else:
        # ---- 嵌套格式 (原有逻辑) ----
        for cat in tp:
            tests = cat.get("tests", []) if isinstance(cat, dict) else []
            result["total_tests"] += len(tests)
            result["total_categories"] += 1
            result["categories"].append({
                "category": cat.get("category", "unknown") if isinstance(cat, dict) else str(cat),
                "test_count": len(tests),
                "tests": [{"name": t.get("name", t) if isinstance(t, dict) else str(t),
                           "description": t.get("description", "") if isinstance(t, dict) else ""}
                          for t in tests],
            })

    return json.dumps(result, indent=2, ensure_ascii=False)


def _slugify(text: str) -> str:
    """将中文/混合文本转为英文 slug，用于场景命名。"""
    import re
    # 提取 test point ID 中的英文部分 (如 TP_APB_REG_RW → apb_reg_rw)
    m = re.search(r'(?:TP_)?([A-Z][A-Z_0-9]+[A-Z])', text)
    if m:
        return m.group(1).strip('_').lower()
    # 回退: 移除非 ASCII，取前 30 字符
    ascii_text = re.sub(r'[^\x00-\x7F]+', '', text)
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', ascii_text).strip('_').lower()
    return slug[:30] if slug else "scenario"


_POLICIES_BY_KEYWORD = [
    (["寄存器", "register", "config", "apb", "配置", "cfg"], "config_consistency"),
    (["axi", "burst", "transfer"], "axi_transfer"),
    (["tx", "rx", "串行", "serial", "uart", "spi", "发送", "接收", "transmit", "receive", "数据", "data"], "data_integrity"),
    (["fifo", "缓冲", "buffer", "满", "空", "溢出", "overflow", "边界", "boundary"], "capacity_boundary"),
    (["中断", "interrupt", "irq", "事件", "event"], "event_trigger"),
    (["波特", "baud", "时钟", "clock", "频率", "timing", "时序"], "timing_constraint"),
    (["功耗", "power", "低功耗", "idle", "sleep"], "power_mode"),
    (["错误", "error", "fault", "异常", "注入", "inject", "复位", "reset"], "error_injection"),
    (["并发", "concurrent", "多端口", "multi-port", "竞争", "race"], "concurrent_access"),
    (["回环", "loopback", "loop"], "loopback_test"),
]


@tool("map_policies_to_tests")
def map_policies_to_tests(input_json: str) -> str:
    """将 test_points 按分类映射到约束策略 → 返回场景定义。

    每类 test_point 生成一个定向场景；额外追加随机回归 + 压力场景。
    优先级来自 test_point 的 priority 字段 (P0/P1/P2)。"""
    try:
        data = json.loads(input_json) if isinstance(input_json, str) else input_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    categories = data.get("categories", [])
    features = data.get("features", [])
    all_policies = _infer_policies_from_features(features)

    scenarios = []
    for i, cat in enumerate(categories):
        cat_tests = cat.get("tests", [])
        test_count = cat.get("test_count", len(cat_tests))

        # 从 test 的 priority 取最高等级
        priorities = [t.get("priority", "P2") for t in cat_tests]
        scenario_priority = "P0" if "P0" in priorities else ("P1" if "P1" in priorities else "P2")

        # 该分类的策略: 按 keyword 匹配 feature 文本
        cat_text = cat.get("category", "")
        test_descs = " ".join(t.get("description", "") for t in cat_tests)
        combined_text = f"{cat_text} {test_descs}".lower()
        cat_policies = [pn for kwlist, pn in _POLICIES_BY_KEYWORD if any(kw.lower() in combined_text for kw in kwlist)]
        if not cat_policies:
            cat_policies = all_policies[:2] if len(all_policies) >= 2 else all_policies

        # 场景名: 优先用第一个 test ID 的 slug
        first_id = cat_tests[0].get("name", "") if cat_tests else cat.get("category", "")
        slug = _slugify(first_id) if first_id else f"cat_{i}"

        # 模式与规模
        if test_count <= 1:
            mode, timeout, repeat = "APPLY_SEQUENTIAL", 300, 5
        elif test_count <= 3:
            mode, timeout, repeat = "APPLY_WEIGHTED", 600, 10
        else:
            mode, timeout, repeat = "APPLY_ALL", 1800, 20

        priority_rules = []
        for j, pn in enumerate(cat_policies):
            priority_rules.append({"policy": pn, "weight": max(10 - j, 1)})

        scenario = {
            "name": slug,
            "description": cat.get("category", f"category_{i}"),
            "priority": scenario_priority,
            "timeout": timeout,
            "combinator_mode": mode,
            "policies": cat_policies,
            "priority_rules": priority_rules,
            "repeat": repeat,
            "source_tests": [t.get("name", f"test_{j}") for j, t in enumerate(cat_tests)],
        }
        scenarios.append(scenario)

    # 随机压力回归场景
    if len(all_policies) >= 3:
        scenarios.append({
            "name": "random_regression",
            "description": "随机压力回归 — 覆盖所有策略加权组合",
            "priority": "P1",
            "timeout": 3600,
            "combinator_mode": "APPLY_WEIGHTED",
            "policies": all_policies,
            "priority_rules": [{"policy": pn, "weight": max(10 - j, 1)} for j, pn in enumerate(all_policies)],
            "seed": "random",
            "repeat": 100,
            "source_tests": [],
        })

    return json.dumps({
        "scenarios": scenarios,
        "available_policies": all_policies,
    }, indent=2, ensure_ascii=False)


@tool("build_scenario_yaml")
def build_scenario_yaml(scenarios_json: str, output_dir: str = "") -> str:
    """将场景 JSON 转为完整 constraint YAML（TestCaseGenerator 兼容格式）。

    Output YAML 包含: constraint, transactions, policies, combinator, scenarios
    保存到 output_dir/inputs/yaml/constraint.yaml
    """
    try:
        data = json.loads(scenarios_json) if isinstance(scenarios_json, str) else scenarios_json
    except (json.JSONDecodeError, TypeError):
        return "# Error: Invalid JSON input"

    scenarios = data.get("scenarios", [])
    env_name = data.get("env_name", "dut_env")
    project_name = data.get("project_name", data.get("design_name", "project"))
    features = data.get("features", [])
    interfaces = data.get("interfaces", [])
    available_policies = data.get("available_policies", [])

    # 推断 transactions / policies / combinator
    transactions = _infer_transactions_from_features(features, interfaces)
    if not available_policies:
        available_policies = _infer_policies_from_features(features)
    combinator = _infer_combinator(available_policies)

    # 构建完整 YAML 结构
    regress_dir = data.get("regress_dir", "test_regress")

    yaml_data = {
        "constraint": {
            "name": project_name,
            "env_name": env_name,
            "regress_dir": regress_dir,
            "description": f"Constraint configuration for {project_name}",
        },
        "transactions": transactions,
        "policies": [
            {
                "name": pn,
                "description": f"Auto-generated policy: {pn}",
                "enabled": True,
                "weight": max(10 - i, 1),
            }
            for i, pn in enumerate(available_policies)
        ],
        "combinator": {
            "default_mode": combinator["mode_sequence"],
            "supported_modes": [
                "APPLY_ALL", "APPLY_SEQUENTIAL", "APPLY_WEIGHTED",
                "APPLY_FIRST_MATCH"
            ],
            "enable_chain": combinator["enable_chain"],
            "enable_weighted": combinator["enable_weighted"],
        },
        "scenarios": [],
    }

    for s in scenarios:
        entry = {
            "name": s["name"],
            "description": s.get("description", ""),
            "timeout": s.get("timeout", 600),
            "combinator_mode": s.get("combinator_mode", "APPLY_ALL"),
            "policies": s.get("policies", []),
        }
        if s.get("priority"):
            entry["priority"] = s["priority"]
        if s.get("priority_rules"):
            entry["priority_rules"] = s["priority_rules"]
        if s.get("seed"):
            entry["seed"] = s["seed"]
        if s.get("repeat"):
            entry["repeat"] = s["repeat"]
        if s.get("params_override"):
            entry["params_override"] = s["params_override"]
        yaml_data["scenarios"].append(entry)

    yaml_str = yaml.dump(yaml_data, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # 保存到 inputs/yaml/
    if output_dir:
        yaml_dir = Path(output_dir) / "inputs" / "yaml"
        yaml_dir.mkdir(parents=True, exist_ok=True)
        save_path = yaml_dir / "constraint.yaml"
        save_path.write_text(yaml_str, encoding="utf-8", errors="replace")

    return yaml_str


@tool("generate_test_cases")
def generate_test_cases(yaml_spec: str, output_dir: str = "output/testcases") -> str:
    """调用 testcase_tools CLI 从约束 YAML 生成 SV 测试代码。

    等价命令: python -m src.tools.testcase_tools.main <yaml> --all --output <output_dir>/testcases
    """
    testcases_out = str(Path(output_dir) / "testcases")

    # 1. 保存 YAML 到磁盘
    yaml_dir = Path(output_dir) / "inputs" / "yaml"
    yaml_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = yaml_dir / "constraint.yaml"
    yaml_path.write_text(yaml_spec, encoding="utf-8", errors="replace")

    # 2. 调用 CLI
    try:
        r = subprocess.run(
            [sys.executable, "-m", "src.tools.testcase_tools.main",
             str(yaml_path), "--all", "--output", testcases_out],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=120, cwd=str(Path.cwd()),
        )
        if r.returncode != 0:
            return json.dumps({
                "error": f"CLI exit {r.returncode}",
                "stderr": r.stderr[:500],
                "stdout": r.stdout[:500],
            }, ensure_ascii=False)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "CLI timed out"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)

    # 3. 读取生成的汇总
    summary_path = Path(testcases_out) / "test_summary.json"
    if summary_path.exists():
        summary = json.loads(summary_path.read_text(encoding="utf-8", errors="replace"))
        return json.dumps(summary, indent=2, ensure_ascii=False)

    return json.dumps({
        "status": "generated",
        "output_dir": testcases_out,
        "stdout": r.stdout[:1000],
    }, ensure_ascii=False)


@tool("check_test_coverage")
def check_test_coverage(spec_json: str, scenarios_json: str) -> str:
    """对比 spec test_points 和生成的场景，检查覆盖率。"""
    try:
        spec = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
        sc = json.loads(scenarios_json) if isinstance(scenarios_json, str) else scenarios_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    all_tests = []
    for cat in spec.get("test_points", spec.get("categories", [])):
        for t in cat.get("tests", []):
            all_tests.append({"name": t.get("name", str(t)), "category": cat.get("category", "?")})

    covered = set()
    for s in sc.get("scenarios", []):
        for t in s.get("source_tests", []):
            covered.add(t)

    uncovered = [t for t in all_tests if t["name"] not in covered]
    total = len(all_tests) or 1
    result = {
        "total_test_points": len(all_tests),
        "covered": len(covered),
        "uncovered": len(uncovered),
        "coverage_pct": f"{len(covered)*100//total}%",
        "uncovered_items": uncovered[:10],
        "status": "PASS" if not uncovered else "WARN",
    }
    return json.dumps(result, indent=2, ensure_ascii=False)


@tool("build_priority_rules")
def build_priority_rules(policies_json: str) -> str:
    """根据策略列表生成优先级规则（越高权重越优先）。"""
    try:
        data = json.loads(policies_json) if isinstance(policies_json, str) else policies_json
    except (json.JSONDecodeError, TypeError):
        return json.dumps({"error": "Invalid JSON"}, ensure_ascii=False)

    policies = data.get("policies", data if isinstance(data, list) else [])
    rules = []
    for i, p in enumerate(policies):
        rules.append({
            "policy": p if isinstance(p, str) else p.get("name", str(p)),
            "weight": max(10 - i, 1)
        })
    return json.dumps({"priority_rules": rules}, indent=2, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════════
# 功能覆盖率点推断 — 从 spec test_points 语义推断 coverpoint
# ═══════════════════════════════════════════════════════════════

_COVERPOINT_HINTS = [
    # (keywords, coverpoint_type, field, bins_hint)
    (["寄存器", "register", "apb", "读写", "r/w"], "bit [7:0]", "addr",
     ["ADDR_000=8'h00", "ADDR_001=8'h01", "ADDR_002=8'h02", "ADDR_004=8'h04", "ADDR_005=8'h05"]),
    (["波特", "baud", "速率", "rate"], "int", "baud_rate",
     ["BAUD_9600=9600", "BAUD_19200=19200", "BAUD_38400=38400", "BAUD_57600=57600", "BAUD_115200=115200"]),
    (["fifo", "满", "空", "溢出", "buffer", "full", "empty", "overflow"], "bit [3:0]", "fifo_status",
     ["EMPTY", "PARTIAL", "FULL", "OVERFLOW"]),
    (["中断", "interrupt", "irq"], "bit [2:0]", "irq_status",
     ["RX_DONE=3'b001", "TX_DONE=3'b010", "FIFO_OVF=3'b100"]),
    (["发送", "tx", "transmit", "接收", "rx", "receive", "uart", "串行"], "bit [7:0]", "data",
     ["MIN_VAL=8'h00", "MID_VAL=8'h80", "MAX_VAL=8'hFF"]),
    (["功耗", "power", "idle", "active"], "bit [1:0]", "power_state",
     ["LOW_POWER=2'b00", "HIGH_PERF=2'b01", "BALANCED=2'b10"]),
    (["模式", "mode", "profile", "compute"], "bit [3:0]", "op_mode",
     ["CONV2D", "MATMUL", "DEPTHWISE", "POOL"]),
    (["并发", "concurrent", "多端口", "multi-port"], "bit [2:0]", "port_count",
     ["PORT_1=3'd1", "PORT_2=3'd2", "PORT_4=3'd4", "PORT_8=3'd8"]),
    (["复位", "reset", "rst"], "bit", "reset_state",
     ["DEASSERTED=1'b1"]),
    (["精度", "precision", "width"], "bit [2:0]", "precision",
     ["INT8=3'd0", "FP16=3'd1", "FP32=3'd2", "INT16=3'd3"]),
]


def _infer_coverpoints(test_point: dict) -> list:
    """根据 test_point 的 feature + description 推断 coverpoint 定义。"""
    text = f"{test_point.get('feature', '')} {test_point.get('description', '')}".lower()
    cps = []
    seen_fields = set()
    for keywords, cp_type, field, bins_hint in _COVERPOINT_HINTS:
        if field in seen_fields:
            continue
        if any(kw in text for kw in keywords):
            cps.append({
                "type": cp_type, "name": field, "field": field,
                "signal": f"txn.{field}",
                "bins": bins_hint,
                "description": keywords[0],
            })
            seen_fields.add(field)
    # 兜底: 至少一个 coverpoint
    if not cps:
        tp_id = test_point.get("id", "tp").lower()
        cps.append({
            "type": "bit", "name": f"done_{tp_id}", "field": f"done_{tp_id}",
            "signal": f"txn.done_{tp_id}",
            "bins": ["NOT_DONE=1'b0", "DONE=1'b1"],
            "description": "transaction completed",
        })
    return cps


@tool("generate_coverage_points")
def generate_coverage_points(spec_json: str) -> str:
    """从 spec JSON 生成功能覆盖率 SystemVerilog 代码 (covergroup)。

    输入 JSON 格式:
      { "design_name": "...", "env_name": "...",
        "verification_architecture": { "clock_reset": {"clk": "..."} },
        "test_points": [{"id":"TP_xxx","feature":"...","description":"...","priority":"P0","acceptance":"..."}]
      }

    输出: 完整 covergroup SV 文件，每个 test_point 对应一个 covergroup，
          包含与 spec 的追溯注释 (traceability)。
    """
    try:
        data = json.loads(spec_json) if isinstance(spec_json, str) else spec_json
    except (json.JSONDecodeError, TypeError):
        return "// Error: Invalid JSON input"

    tp = data.get("test_points", [])
    if isinstance(tp, dict):
        tp = [tp]
    if not isinstance(tp, list):
        return "// Error: test_points must be a list"

    env_name = data.get("env_name", data.get("design_name", "dut") + "_env")
    project_name = data.get("design_name", data.get("project_name", "dut"))
    clock = data.get("verification_architecture", {}).get("clock_reset", {}).get("clk", "clk")

    test_points = []
    for item in tp:
        if not isinstance(item, dict):
            continue
        cps = _infer_coverpoints(item)
        test_points.append({
            "id": item.get("id", f"TP_{len(test_points):03d}"),
            "feature": item.get("feature", ""),
            "description": item.get("description", ""),
            "priority": item.get("priority", "P2"),
            "acceptance": item.get("acceptance", ""),
            "coverpoints": cps,
        })

    # Jinja2 渲染
    from pathlib import Path as _P
    from jinja2 import Environment, FileSystemLoader
    from datetime import datetime as _dt
    template_dir = _P(__file__).parent / "templates"
    jinja = Environment(loader=FileSystemLoader(str(template_dir)))
    tmpl = jinja.get_template("coverage.sv.j2")
    sv_code = tmpl.render(
        env_name=env_name,
        project_name=project_name,
        clock=clock,
        test_points=test_points,
        timestamp=_dt.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    return sv_code
