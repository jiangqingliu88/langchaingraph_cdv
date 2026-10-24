"""工具的程序化接口 —— 吃 DSL 文本、吐 dict。

四个函数覆盖这个工具的全部能力，**零 LLM 依赖**（不 import langchain /
ToolHub / Qt）：

    run_validate(dsl_text)                     → schema 校验结果
    run_compile(dsl_text, seed=…, max_txns=…)  → IR + 地址分配 + 落盘产物
    run_explain(txn="")                        → 注册表解读（碰撞 / 疑点 / 事务清单）
    run_ops()                                  → op 注册表清单

CLI（`cli.py`）与未来的 Agent 适配器都走这里 —— 语义只此一份，包装各写各的。

返回值一律是 **dict**（不是 JSON 字符串）：需要字符串的调用方自己 `json.dumps`，
需要结构化数据的直接用 —— 两边都不用解析自己刚序列化的东西。

**失败返回 `{"error", "kind", "target", "fix"}`，不抛。**
`kind` 是 `CompileError` 的类名（见 `domain/errors.py` 的十个具名子类），
`target` 是出错的对象，`fix` 是"该改什么"。三件套缺一，报错就只能靠猜。

**v0 没有 `run_encode`** —— 编码器（DSL→IR→32bit）是独立的一轮。
它落地时在同文件加一个 `run_encode(ir_json)`，读 `schema/ops.registry.json`
的 `funct7`，**注册表一行不用改** —— 那正是把编码做成数据的意义。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .analysis import check_dsl_text, load_dsl
from .compile import compile_dsl
from .domain import COMPILE_ERROR_KINDS, CompileError, IsaGenError
from .encode import encode_ir
from .tensors import build_tensors
from .repository import (load_memmap, load_ops_registry, load_txn_registry,
                         registry_provenance)

# ═══════════════════════════════════════════════════════════════
# 工具名 —— CLI / 文档 / 未来的 Agent 适配器共用同一批名字
# ═══════════════════════════════════════════════════════════════

TOOL_VALIDATE = "isa_gen_validate"
TOOL_COMPILE = "isa_gen_compile"
TOOL_EXPLAIN = "isa_gen_explain"
TOOL_OPS = "isa_gen_ops"

TOOL_NAMES = (TOOL_VALIDATE, TOOL_COMPILE, TOOL_EXPLAIN, TOOL_OPS)


def _error(exc: BaseException) -> Dict[str, Any]:
    """异常 → 统一的错误形状。三件套缺一，报错就只能靠猜。"""
    if isinstance(exc, CompileError):
        return exc.to_dict()
    return {"error": str(exc), "kind": "internal", "target": ""}


# ═══════════════════════════════════════════════════════════════
# validate
# ═══════════════════════════════════════════════════════════════

def run_validate(dsl_text: str) -> Dict[str, Any]:
    """DSL 文本 → schema 校验结果。

    只回答「这份 DSL 写对了吗」；引用是否存在、地址放不放得下由
    `run_compile` 回答（那些要先把模型建起来）。
    """
    if not isinstance(dsl_text, str) or not dsl_text.strip():
        return {"valid": False, "error_count": 1, "warning_count": 0,
                "issues": [{"severity": "error", "category": "schema",
                            "rule": "empty_input", "target": "<root>",
                            "message": "dsl_text 为空"}]}

    issues = check_dsl_text(dsl_text)
    errors = [i for i in issues if i.is_error]
    return {
        "valid": not errors,
        "error_count": len(errors),
        "warning_count": len(issues) - len(errors),
        "issues": [i.to_dict() for i in issues],
    }


# ═══════════════════════════════════════════════════════════════
# compile
# ═══════════════════════════════════════════════════════════════

def run_compile(dsl_text: str, *, seed: Optional[int] = None,
                max_txns: Optional[int] = None,
                memmap_path: Optional[str] = None) -> Dict[str, Any]:
    """DSL 文本 → IR（含地址分配、preload、expect 与编译报告）。

    `seed` 是**覆盖**（CLI 的 `--seed` 就是这个意思）；不给则用 `meta.seed`，
    再没有才取时间戳。实际用的 seed 一律回填进 `case.meta.seed`。

    `memmap_path` 不给就用包内样例（`fixtures/memmap.yaml`，**从文档重建的、
    不是冻结版**）—— 冻结版到位后优先自动用它，也可以显式指定。
    """
    try:
        document = load_dsl(dsl_text)
    except IsaGenError as exc:
        # schema 不过也是"这份 DSL 不行"的一种 —— 但它不是 `CompileError`
        # 的子类（那是校验期，还没有模型）。所以在这里补上 kind 与 fix，
        # 否则调用方拿到的是 `kind="internal"` 且没有 fix 的一条 —— 那等于没说。
        return {"error": str(exc), "kind": "schema", "target": "<dsl>",
                "fix": "先跑 `isa_gen validate` 看逐条问题；"
                       "键名对照 schema/dsl.schema.json"}

    try:
        ops = load_ops_registry()
        txns = load_txn_registry(ops=ops)
        memmap = load_memmap(memmap_path) if memmap_path else load_memmap()
        output = compile_dsl(document, txns=txns, ops=ops, memmap=memmap,
                             seed=seed, max_txns=max_txns)
    except COMPILE_ERROR_KINDS as exc:
        return _error(exc)
    except IsaGenError as exc:
        return _error(exc)

    report = output.report.to_dict()

    # ── L3 编码（§3.1）：IR → seq.hex + reg-init.txt ──
    # `allow_inconsistent_flags=True`：有些槽本版本还填不出来（多段拼接地址 /
    # 标量 / cfg），原因已记在 IR 的 `extra.operand_gap` 里。这里**照编不误**，
    # 但把每一条"这个字里有个槽是空的"收进 notes —— 免得 seq.hex 看起来像完整的。
    # **不静默**是这条链上唯一不能让的事。
    encode_out: Dict[str, Any] = {}
    try:
        encoded = encode_ir(output.program.to_dict(), ops,
                            allow_inconsistent_flags=True)
        encode_out = encoded.to_dict()
    except IsaGenError as exc:
        # 编码失败不让整次编译失败 —— IR 已经是完整产物，只是这一层编不出来。
        encode_out = {"error": str(exc), "kind": getattr(exc, "kind", "encode_error"),
                      "fix": getattr(exc, "fix", "")}

    # ── tensor_gen（§3.12.9）：preload 的句柄 → 真的张量数据 ──
    # 确定性（同样的 case_seed + 同样的 preload → 逐字节相同），所以它在
    # `run_compile` 里跑不引入不确定性。
    tensor_out: Dict[str, Any] = {}
    try:
        bundle = build_tensors(output.preload, output.case)
        tensor_out = {
            "entries": [{"name": e.name, "ref": e.ref, "hex": e.hex_text,
                         "manifest": e.manifest, "n_bytes": e.n_bytes,
                         "content_hash": e.content_hash}
                        for e in bundle.entries],
            "registry": bundle.registry,
            "notes": bundle.notes,
        }
    except (IsaGenError, ValueError) as exc:
        tensor_out = {"error": str(exc), "kind": "tensor_gen"}

    return {
        "seed": report["seed"],
        "name": report["name"],
        "isa_rev": output.case["meta"]["isa_rev"],
        "txn_count": report["txn_count"],
        "instruction_count": report["instruction_count"],
        "epoch_count": report["epoch_count"],
        "case": output.case,
        "ir": output.program.to_dict(),
        # seq.hex / reg-init.txt 的内容 —— `export.py` 按它落盘
        "encode": encode_out,
        # tensors/*.hex + manifest/*.json + registry.json 的内容 —— 同上
        "tensors": tensor_out,
        "preload": output.preload,
        "expect": output.expect,
        "allocations": report["allocations"],
        "play_space": report["play_space"],
        "weights": report["weights"],
        "streams": report["streams"],
        "notes": report["notes"],
        "elapsed_ms": report["elapsed_ms"],
        # 用的哪份 memmap 要能回答 —— 冻结版到位后"这次跑的到底是不是它"
        # 是个会被反复问的问题
        "memmap": {"version": output.program.memmap_version,
                   "source": memmap.source},
    }


# ═══════════════════════════════════════════════════════════════
# explain / ops
# ═══════════════════════════════════════════════════════════════

def run_explain(txn: str = "") -> Dict[str, Any]:
    """注册表解读 —— **把表里的疑点原样端出来**。

    这个函数存在的理由是：编码表与文档之间有若干处对不上（同码碰撞、
    类前缀不符、文档列了但表里没有）。工具**没有立场替它们做判断**，
    但必须让使用者看得见 —— 悄悄按一种解释跑下去，是拿仿真时间赌一个猜测。

    `txn` 给了就只讲那一条事务。
    """
    try:
        ops = load_ops_registry()
        txns = load_txn_registry(ops=ops)
    except IsaGenError as exc:
        return _error(exc)

    payload: Dict[str, Any] = {
        "ops_source": registry_provenance(),
        "op_count": len(ops),
        "instruction_count": len(ops.instructions()),
        "non_instruction_count": len(ops.non_instructions()),
        "txn_count": len(txns),
        "available_txn_count": len(txns.available()),
        "groups": txns.groups(),
        "collisions": [c.to_dict() for c in ops.collisions()],
        "class_mismatches": [
            {"name": s.name, "funct7": s.funct7_text,
             "declared": s.op_class.name.lower() if s.op_class else None,
             "derived": (s.op_class_from_funct7.name.lower()
                         if s.op_class_from_funct7 else None)}
            for s in ops.class_mismatches()],
        "deferred_ops": [{"name": s.name, "notes": s.notes}
                         for s in ops.deferred()],
        "deferred_txns": [{"id": t.id, "note": t.note} for t in txns.deferred()],
        "risks": _risk_notes(ops),
    }

    if txn:
        spec = txns.find(txn)
        if spec is None:
            payload["error"] = f"没有事务 {txn!r}"
            payload["kind"] = "unknown_txn"
            payload["fix"] = f"已知：{', '.join(txns.ids()[:12])}…"
            return payload
        payload["transaction"] = spec.to_dict()
        payload["ops"] = [
            {**ops.get(name).to_dict(),
             "declared_class": (ops.get(name).op_class.name.lower()
                                if ops.get(name).op_class else None)}
            for name in spec.ops]
    return payload


def run_ops() -> Dict[str, Any]:
    """op 注册表清单 —— 含"哪些还不能编码"。"""
    try:
        ops = load_ops_registry()
    except IsaGenError as exc:
        return _error(exc)
    return {
        "source": registry_provenance(),
        "count": len(ops),
        "instruction_count": len(ops.instructions()),
        "non_instruction_count": len(ops.non_instructions()),
        "without_encoding": [s.name for s in ops.without_encoding()],
        "deferred": [s.name for s in ops.deferred()],
        "ops": [s.to_dict() for s in ops.all()],
    }


#: 文档里带 ⚠ 的疑点 —— 由 `run_explain` 原样转述
_XL_RISKS = (
    ("XL-02", "GLSU 本核/全局 load-store 同码",
     "`tld_drv_xn` 与 `gtld_drv_xn` 同为 `010_0001` 且 flags 也相同，"
     "靠地址段（local/global）区分。编码器必须知道这个区分规则，"
     "否则会把本核访问编成全局访问。"),
    ("XL-06", "`set_CIMCmode_drv_xn` 已从硬件移除",
     "编码表里没有这条（Control 只有 10 条）。Peer 前端必须**拒绝**它，"
     "而不是当成未知指令忽略。"),
    ("XL-08", "VPU 一码多指令",
     "`vv_v_drv_xn` 与 `vvv_v_drv_xn` 同为 `101_1000`，靠 xd/xs1/xs2 区分。"
     "身份是四元组不是 funct7 —— 只按 funct7 编码会把两条编成同一条。"),
    ("XL-09", "TMV 的 funct7 疑为复制",
     "`bc_drv_xn` 一族共用一个 funct7 段，是否与 NoC 的段重叠待确认。"),
    ("X-00", "文档列了但编码表没有的事务",
     "`rd_csr_txn`（文档 §3.2/§3.11 列为 Control 指令，表里只有非指令 op "
     "`csr_read`）。记为不可用，**不发明编码**。"),
)


def _risk_notes(ops) -> List[Dict[str, str]]:
    """把文档标了 ⚠ 的疑点转述出来，并**顺带核对它在表里还成不成立**。

    核对是必要的：疑点可能已经被编码表修掉了，那时这条提示就成了噪音。
    所以每条都带回一个 `present` 字段 —— 说得清"现在还在不在"。
    """
    out: List[Dict[str, str]] = []
    for code, title, detail in _XL_RISKS:
        out.append({"code": code, "title": title, "detail": detail,
                    "present": "yes" if _risk_present(code, ops) else "no"})
    return out


def _risk_present(code: str, ops) -> bool:
    if code == "XL-02":
        return ops.find("gtld_drv_xn") is not None
    if code == "XL-06":
        return ops.find("set_CIMCmode_drv_xn") is None     # 表里确实没有
    if code == "XL-08":
        a, b = ops.find("vv_v_drv_xn"), ops.find("vvv_v_drv_xn")
        return bool(a and b and a.funct7 == b.funct7)
    if code == "XL-09":
        return ops.find("bc_drv_xn") is not None
    if code == "X-00":
        return ops.find("rd_csr_drv_xn") is None
    return False


#: 工具名 → 实现，供适配器一次性遍历。
#: 与 `TOOL_NAMES` **必须一致**（有测试钉住）。
RUNNERS = {
    TOOL_VALIDATE: run_validate,
    TOOL_COMPILE: run_compile,
    TOOL_EXPLAIN: run_explain,
    TOOL_OPS: run_ops,
}
