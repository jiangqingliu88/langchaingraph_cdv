"""集成设计环境的「声明式 YAML」工具 —— 读一份 YAML，按 schema 校验，吐诊断。

**两类声明，一套实现**（`Decl` 描述符把各自的专属信息收在一处）：

    manual_nodes   流程人工节点        界面编辑器 / 闭环读它
    ip_spec        IP 规格（接口/寄存器） 界面编辑器

两个入口：

    run_<decl>(path)      → schema 校验结果（界面用）
    load_manual_nodes(path) → 节点 dict 列表（**闭环用**；ip_spec 目前无闭环消费者）

`load_manual_nodes` 是后加的，也是这一层存在的第二个理由：在此之前这份声明
**只有校验、没有解析** —— 闭环（`graph.py`）无从读起，于是它一直只是一份
"看起来像配置"的文档。

它复用 casemodel 那套 **schema 无关**的 `SchemaChecker`
（`src/layers/l3_decision/casemodel/analysis/schema_check.py`）—— 把 schema 路径换成
`manual_nodes.schema.json` 即可，校验与中文诊断口径完全一致。

失败**响亮**（与全仓库一致）：没有路径 / 文件不在 / YAML 坏 —— 返回
`{"error": ...（怎么修）"}` 而不是抛异常。校验**不通过不是 error 返回**：
那是正常结果，`{"valid": false, "issues": [...]}` 交给界面显示。

返回值一律是 **dict**，不是 JSON 字符串（`load_manual_nodes` 返回列表，见其说明）。
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

def _schema_checker(schema_path):
    """延迟加载 casemodel 的 SchemaChecker。

    3.0 后实现位于 `l3_decision.casemodel`（L3）。工具层**模块级** import L3 会
    构成静态方向逆流；函数内加载只在真正校验时才建立运行期依赖。
    """
    from src.layers.l3_decision.casemodel.analysis.schema_check import (
        SchemaChecker,
    )
    return SchemaChecker(schema_path)


@dataclass(frozen=True)
class Decl:
    """一份「声明式 YAML」的全部专属信息。

    工具层做的事（读文件、按 schema 校验、把诊断整理成界面吃得下的形状）对每份
    声明都**一模一样**，不同的只有下面这几项。抽成描述符是为了加第二份声明时
    不必把本模块复制一遍 —— 复制出来的两份迟早会漂移（这个仓库已经有前科：
    `VerificationOS` 的签名就因为写死参数列表而掉过队）。
    """
    name: str                      # 声明名，同时也是 schema 文件名（去掉 .schema.json）
    skeleton_keys: tuple           # YamlEditor 高亮用的结构键
    enum_values: tuple             # YamlEditor 高亮用的枚举值（与 schema 的 enum 对齐）
    default_path: str              # 仓库相对的默认位置

    @property
    def schema_path(self) -> Path:
        return Path(__file__).resolve().parent / "schema" / f"{self.name}.schema.json"


MANUAL_NODES = Decl(
    name="manual_nodes",
    skeleton_keys=(
        "version", "project", "nodes",
        "id", "title", "kind", "after", "action", "prompt",
        "default", "timeout_s", "required",
    ),
    enum_values=(
        # node.kind
        "approval", "review", "manual_step",
        # node.default
        "proceed", "reject", "skip",
        # node.after（闭环既有阶段）
        "design", "model", "verify", "env_arch_check", "ops",
        "coverage", "debug_functional", "decide", "audit",
    ),
    default_path="config/ide/manual_nodes.yaml",
)

IP_SPEC = Decl(
    name="ip_spec",
    skeleton_keys=(
        "version", "project", "ips",
        "name", "category", "function", "tags", "status", "revision",
        "interface", "protocols", "ports", "registers",
        "dir", "width", "protocol", "description",
        "offset", "access", "reset",
    ),
    enum_values=(
        # ip.status
        "planned", "implemented", "verified", "deprecated",
        # port.dir
        "input", "output", "inout",
        # register.access
        "rw", "ro", "wo", "w1c",
        # protocol（与 UVM 生成工具认的那组一致）
        "apb", "uart", "intr", "axi", "clock", "reset", "generic",
    ),
    default_path="config/ide/ip_spec.yaml",
)

#: 声明名 → 描述符
DECLS: Dict[str, Decl] = {d.name: d for d in (MANUAL_NODES, IP_SPEC)}

# ── 以下两个常量是 manual_nodes 的旧名，保留兼容（模块与测试都在用）──
#: 本工具的 schema —— 与 api.py 同包，放在 schema/ 下（对齐 casemodel_tools 的布局）
SCHEMA_PATH = MANUAL_NODES.schema_path

#: 声明的默认位置（相对仓库根）。闭环在没被显式告知时读它。
DEFAULT_MANUAL_NODES = MANUAL_NODES.default_path

#: 高亮用的结构键 / 枚举值（YamlEditor 参数）。
SKELETON_KEYS = MANUAL_NODES.skeleton_keys
ENUM_VALUES = MANUAL_NODES.enum_values

#: 一个节点里**有意义的键** —— 解析时只取这些。
#: 不收的键一律丢弃：声明里多写的东西不该悄悄影响闭环行为（`additionalProperties:
#: false` 已经在 schema 层挡了，这里再挡一道，免得解析器成为绕过校验的后门）。
NODE_KEYS = ("id", "title", "kind", "after", "action", "prompt",
             "default", "timeout_s", "required")


def run_decl(path: str = "", decl: Decl = MANUAL_NODES) -> Dict[str, Any]:
    """一份声明 YAML → schema 校验结果。界面用。

    返回：`{"valid", "error_count", "warning_count", "issues": [...]}`
    """
    if not isinstance(path, str) or not path.strip():
        return {"error": f"没有给 {decl.name}.yaml 的路径"}

    target = Path(path)
    if not target.exists():
        return {"error": f"找不到 {decl.name} 文件：{target}"
                         f"（清单里模块的 `input:` 指向它，相对清单目录解析）"}
    if target.is_dir():
        return {"error": f"{decl.name} 路径是一个目录而不是文件：{target}"}

    checker = _schema_checker(decl.schema_path)
    return _summarise(checker.check_file(target))


def run_manual_nodes(path: str = "") -> Dict[str, Any]:
    """manual_nodes.yaml → schema 校验结果。"""
    return run_decl(path, MANUAL_NODES)


def run_ip_spec(path: str = "") -> Dict[str, Any]:
    """ip_spec.yaml → schema 校验结果。"""
    return run_decl(path, IP_SPEC)


def validate_decl_text(text: str, decl: Decl = MANUAL_NODES,
                       name: str = "<编辑器>") -> Dict[str, Any]:
    """编辑器用：直接校验一段文本，不必先落盘（口径与 run_decl 一致）。"""
    return _summarise(_schema_checker(decl.schema_path).check_text(text, name=name))


def load_decl_issues(text: str, decl: Decl = MANUAL_NODES,
                     name: str = "<编辑器>") -> List[Any]:
    """编辑器用：直接拿 `Issue` 对象列表（IssuePanel 要的是对象，不是 dict）。"""
    return _schema_checker(decl.schema_path).check_text(text, name=name)


def load_manual_nodes(path: str = "") -> List[Dict[str, Any]]:
    """manual_nodes.yaml → 节点 dict 列表。**闭环读它**（在此之前它只被校验过）。

    给 `graph.py` 用：`n_approval` 拿它决定"哪些动作要人批、超时怎么办、提示语是什么"。

    **坏文件等于空声明，不抛异常。** 这一点是刻意的：如果文件坏了就抛，那么
    "没人写声明"和"声明写坏了"会变成同一件事 —— 而它们不该是同一件事（见下）。
    真出问题时由 `run_manual_nodes` 在界面上报出来，闭环这边保持能跑。

    缺省路径是仓库相对的 `config/ide/manual_nodes.yaml`；找不到就返回 `[]`
    （**不是错误** —— 没写声明是完全正常的状态，闭环有 legacy 兜底，见 `n_approval`）。

    只取 `NODE_KEYS` 里的键。少 `id` / `after` 的条目直接丢弃 —— 没有挂载点的
    节点对闭环没有意义，留着只会在匹配时制造意外。
    """
    from pathlib import Path as _Path

    import yaml

    target = _Path(path or DEFAULT_MANUAL_NODES)
    if not target.is_file():
        return []
    try:
        data = yaml.safe_load(target.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(data, dict):
        return []

    nodes: List[Dict[str, Any]] = []
    for raw in data.get("nodes") or []:
        if not isinstance(raw, dict):
            continue
        if not raw.get("id") or not raw.get("after"):
            continue
        node = {key: raw[key] for key in NODE_KEYS if key in raw}
        node.setdefault("kind", "approval")
        node.setdefault("default", "skip")
        node.setdefault("required", True)
        nodes.append(node)
    return nodes


def validate_text(text: str, name: str = "<编辑器>") -> Dict[str, Any]:
    """编辑器用：直接校验一段文本（manual_nodes 的旧名，保留兼容）。"""
    return validate_decl_text(text, MANUAL_NODES, name)


def _summarise(issues: List[Any]) -> Dict[str, Any]:
    errors = [i for i in issues if i.is_error]
    warnings = [i for i in issues if i.severity == "warning"]
    return {
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": [{"severity": i.severity, "rule": i.rule, "target": i.target,
                    "message": i.message, "category": i.category}
                   for i in issues],
    }


def load_issues(text: str, name: str = "<编辑器>") -> List[Any]:
    """编辑器用：直接拿 `Issue` 对象列表（manual_nodes 的旧名，保留兼容）。"""
    return load_decl_issues(text, MANUAL_NODES, name)
