"""从 **spec** 合成一份 case 模型 —— 让闭环里的测试点分解不再是空转。

## 为什么需要这个

闭环的 `verify` 阶段会拿一份 case 模型（功能组织树 + 专题 + 维度约束）去分解
测试点。但**闭环里没有任何一步产它**：`_find_case_model` 的三个来源
（`spec["case_model"]` / 人放的 `inputs/casemodel.yaml` / 项目级 `config/casemodel/`）
在自动跑的时候通常**都命不中** —— 于是那一步只留下一句
「这次运行没有 case 模型 —— 跳过测试点分解」，覆盖率的收敛全靠随机激励。

这个模块就是那座桥：**spec 里已经有的东西**（功能点、接口信号、寄存器、中断）
足够撑起一份可用的 case 模型 —— 功能点当功能组织树的叶子，接口信号当维度，
寄存器读写当专题。合成的模型会明确标 `generated_from: spec`，而且**落盘到
运行目录**（`inputs/casemodel.yaml`）—— 人可以打开看、可以直接改，
下次运行就是"人给的那一份"（`_find_case_model` 的来源 2 优先于合成）。

## 不假装

它不是"AI 想出来的验证计划"，而是**把 spec 里已有的字段机械地映射成 case 模型
的结构**：有多少功能点就有多少叶子，有几个数据信号就有几个维度。spec 里没有的
（比如"反压持续时间"这种领域专题）它不会编 —— 那需要人给。
"""
from __future__ import annotations

from typing import Any, Dict, List

#: 数据总线类协议 —— 这些接口信号才当"维度"（时钟/复位不当）。
_DATA_PROTOCOLS = {"apb", "axi", "ahb", "wishbone", "uart", "spi", "i2c", "intr"}

#: 协议 → 编码前缀，给 id 用
_CODE = {"apb": "APB", "axi": "AXI", "ahb": "AHB", "uart": "UART", "spi": "SPI",
         "i2c": "I2C", "intr": "INTR", "wishbone": "WB"}


def _feature_leaves(features: List[dict]) -> List[dict]:
    """功能点 → 功能组织树的叶子。

    功能点本来就是"这个设计要做什么"的清单，和最细一级的被测对象是同一件事，
    所以直接当叶子；`priority` 留在 description 里（叶子上没有优先级字段）。

    **代号必须唯一** —— 组织树里叶子代号重复是硬错误（`UART 发送` 与 `UART 接收`
    都会被拼成 `UART`，实测就是这么撞的）。撞了就补序号。
    """
    leaves = []
    used: Dict[str, int] = {}
    for i, f in enumerate(features, 1):
        if not isinstance(f, dict) or not f.get("name"):
            continue
        name = str(f["name"])
        code = _short_code(name, i)
        used[code] = used.get(code, 0) + 1
        if used[code] > 1:
            code = f"{code}{used[code]}"
        leaves.append({
            "id": f"FEAT-{i:02d}",
            "name": name,
            "code": code,
            "description": str(f.get("description") or f.get("priority") or name),
        })
    return leaves


def _short_code(name: str, i: int) -> str:
    """给叶子拼一个简短的英文码 —— 用名字里的 ASCII 词，拼不出就用序号。"""
    word = "".join(ch for ch in name if ch.isascii() and ch.isalnum())
    return (word[:6].upper() or f"F{i:02d}")


def _signal_dimensions(interfaces: List[dict]) -> List[dict]:
    """数据信号 → 维度（取值按位宽给边界，边界值显式标出来给 SPCL 专题用）。"""
    dims = []
    seen = set()
    for sig in interfaces:
        if not isinstance(sig, dict):
            continue
        raw = str(sig.get("name", ""))
        base = raw.split("[")[0].strip()
        proto = str(sig.get("protocol", "")).lower()
        width = int(sig.get("data_width", 1) or 1)
        if not base or base in seen or proto not in _DATA_PROTOCOLS or width < 2:
            continue
        seen.add(base)
        full = (1 << width) - 1
        # 边界取值：最小、1、中点、最大 —— 覆盖率缺口多半就在两端
        edge = sorted({0, 1, 1 << (width - 1), full})
        dims.append({
            "id": f"D_{base}",
            "name": base,
            "fields": [{
                "name": base,
                "type": "range",
                "min": 0,
                "max": full,
                "boundary": [str(v) for v in edge],
            }],
        })
    return dims


def _interrupt_dimension(interrupts: List[Any]) -> List[dict]:
    """中断 → 一个枚举维度（哪些中断源要被激励到）。"""
    names = []
    for item in interrupts or []:
        if isinstance(item, dict):
            n = item.get("name") or item.get("id")
            if n:
                names.append(str(n))
        elif item:
            names.append(str(item))
    if not names:
        return []
    return [{
        "id": "D_intr_src",
        "name": "中断源",
        "fields": [{"name": "中断源", "type": "enum",
                    "values": ["无"] + names[:8],
                    "boundary": names[:2]}],
    }]


def case_model_from_spec(spec: Dict[str, Any]) -> Dict[str, Any]:
    """spec → case 模型（dict）。空 spec 返回空 dict（调用方据此跳过）。"""
    if not isinstance(spec, dict) or not spec:
        return {}
    design = str(spec.get("design_name") or "dut")
    features = spec.get("features") or []
    leaves = _feature_leaves(features)
    dims = _signal_dimensions(spec.get("interfaces") or [])
    dims += _interrupt_dimension(spec.get("interrupts") or [])
    if not leaves and not dims:
        return {}

    dim_names = [d["name"] for d in dims]
    leaf_names = [leaf["name"] for leaf in leaves]
    themes = []
    if leaves:
        themes.append({
            "id": "TH-P0-FUNC",
            "name": "功能点直通专题",
            "priority": "P0",
            "applies_to": leaf_names,          # 每个功能点都要被直接打到
            "dimensions": dim_names[:1],
            "method": "D",
            "checks": ["CHECK-FUNC"],
            "expected_result": "每个功能点都有定向用例覆盖，且结果符合规格",
            "description": "spec 的功能点清单逐条落地（合成）",
        })
    if dim_names:
        themes.append({
            "id": "TH-P1-RND",
            "name": "维度随机组合专题",
            "priority": "P1",
            "applies_to": [],
            "dimensions": dim_names,
            "method": "RND",
            "checks": ["CHECK-FUNC"],
            "expected_result": "各维度随机组合下行为正确",
            "description": "接口信号取值的组合空间（合成）",
        })
        themes.append({
            "id": "TH-P2-BND",
            "name": "边界取值专题",
            "priority": "P2",
            "applies_to": [],
            "dimensions": dim_names[:2],
            "method": "SPCL",
            "checks": ["CHECK-FUNC"],
            "expected_result": "边界取值下无越界、无溢出",
            "description": "把维度推到端点（合成）",
        })

    cross_matrix = {}
    for i, a in enumerate(dim_names):
        for b in dim_names[i + 1:]:
            cross_matrix[f"{a}×{b}"] = "required" if len(cross_matrix) < 2 else "optional"

    return {
        "version": "1.0",
        #: 标出来源：这是**从 spec 合成的**，不是人写的验证计划 —— 判它好不好之前
        #: 先看这行。人往 `inputs/casemodel.yaml` 放一份就会盖过它。
        "generated_from": "spec",
        # ── 执行指纹与生成策略（界面上「环境」「生成」两页读的就是这两段）──
        #
        # 这一段回答"同一个 case 在什么前提下跑的"：**同一指纹下失败才可复现**。
        # 合成时能如实给的只有"这次的设计"，工具版本/EDA 得等运行期才知道 ——
        # 所以 defaults 里只写推导得出的，其余留空让运行期补（不编一个假的版本号）。
        "environment": {
            "required": ["tool_version", "rtl_version", "constraint_version", "seed"],
            "defaults": {
                "rtl_version": f"{design}_auto",
                "constraint_version": f"{design}_tp_auto",
                "config_profile": "default",
            },
            "description": f"{design} 的自动合成 case 模型；工具/EDA 版本由运行期补",
        },
        "generation": {
            "seed": 42,
            "repeat": 4,
            "max_cases": 200,
        },
        "tests": [{
            "object": design,
            "object_cn": design,
            "object_code": _short_code(design, 1),
            "description": f"{design} 的 case 模型（由 spec 合成）",
            "sub_objects": leaves or [{"id": "DUT-01", "name": design,
                                       "code": "DUT", "description": design}],
            "themes": themes,
        }],
        "dimensions": dims,
        "methods": ["D", "RND", "SPCL"],
        "checks": [{"id": "CHECK-FUNC", "name": "功能检查",
                    "description": "结果是否符合规格"}],
        "cross_matrix": cross_matrix,
    }


def case_model_yaml(spec: Dict[str, Any]) -> str:
    """spec → case 模型 YAML 文本（空 spec 时返回空串）。"""
    import yaml

    model = case_model_from_spec(spec)
    if not model:
        return ""
    return yaml.safe_dump(model, allow_unicode=True, sort_keys=False)
