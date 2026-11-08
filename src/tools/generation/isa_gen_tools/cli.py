"""isa_gen_tools 命令行入口。

    python -m src.tools.generation.isa_gen_tools.cli validate <dsl.yaml>
    python -m src.tools.generation.isa_gen_tools.cli compile  <dsl.yaml> [-o 目录] [--seed N]
    python -m src.tools.generation.isa_gen_tools.cli explain  [--txn <事务名>]
    python -m src.tools.generation.isa_gen_tools.cli ops

退出码：有 error → 1；DSL 或注册表读不了 → 2；正常 → 0。

CLI 只做**参数翻译**，语义全在 `api.py` 里 —— 两处各写一份逻辑，
迟早有一处先改。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── UTF-8 强制编码 ──
# 报告里有 → / ✓ 这些字符，而 Windows 控制台默认是 GBK：不转的话
# `explain` 会在 print 那一步抛 UnicodeEncodeError（用户看到的是一段
# traceback，而不是报告）。与 旧建模 CLI 同一处理。
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")

from .api import run_compile, run_explain, run_ops, run_validate
from .export import NOT_PRODUCED, write_artifacts

__version__ = "0.1"

# ════════════════════════════════════════════════════════════════
# validate
# ════════════════════════════════════════════════════════════════

def cmd_validate(args: argparse.Namespace) -> int:
    text = _read(args.dsl)
    payload = run_validate(text)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if payload.get("valid") else 1

    if payload.get("valid"):
        print(f"✓ {Path(args.dsl).name}：DSL 合法")
    else:
        print(f"✗ {Path(args.dsl).name}：{payload['error_count']} 处 error")
    for issue in payload.get("issues", []):
        print(f"   [{issue['severity']}] {issue['message']}")
        if issue.get("target"):
            print(f"        @ {issue['target']}")
        if issue.get("fix"):
            print(f"        → {issue['fix']}")
    return 0 if payload.get("valid") else 1


# ════════════════════════════════════════════════════════════════
# compile
# ════════════════════════════════════════════════════════════════

def cmd_compile(args: argparse.Namespace) -> int:
    text = _read(args.dsl)
    payload = run_compile(text, seed=args.seed, max_txns=args.max_txns,
                          memmap_path=args.memmap)
    if payload.get("error"):
        _print_error(payload)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    _print_summary(payload)
    if args.out:
        _write_artifacts(Path(args.out), payload)
    return 0


def _print_summary(payload: Dict[str, Any]) -> None:
    print(f"✓ {payload['name']}  seed={payload['seed']}  "
          f"事务={payload['txn_count']}  指令={payload['instruction_count']}  "
          f"epoch={payload['epoch_count']}  {payload['elapsed_ms']}ms")
    print(f"  派生流: {', '.join(payload['streams'])}")
    print(f"  memmap: {payload['memmap']['source']} ({payload['memmap']['version']})")

    objects = payload["allocations"]["objects"]
    if objects:
        print(f"  地址分配 {len(objects)} 个对象：")
        for item in objects:
            print(f"    {item['name']:<12} {item['region']:<16} {item['offset']:>10}")

    anchors = payload["expect"]["anchors"]
    if anchors:
        print(f"  观测点 {len(anchors)} 个：{', '.join(a['tag'] for a in anchors)}")

    for note in payload["notes"]:
        print(f"  注意: {note}")


def _write_artifacts(out: Path, payload: Dict[str, Any]) -> None:
    """按 §3.6 的布局落盘 —— **实现与界面共用 `export.write_artifacts`**。

    两处各写一遍落盘逻辑，迟早有一处先改；而落盘布局是文档规定的契约，
    不是各人的实现细节。这里只负责打印。
    """
    result = write_artifacts(out, payload)
    print(f"\n已写出 → {result['out_dir']}")
    for name in result["written"]:
        print(f"   {name}")
    for item in result["not_produced"]:
        print(f"   （{item['file']} 不在本工具：{item['reason']}）")


# ════════════════════════════════════════════════════════════════
# explain / ops
# ════════════════════════════════════════════════════════════════

def cmd_explain(args: argparse.Namespace) -> int:
    payload = run_explain(args.txn or "")
    if payload.get("error"):
        _print_error(payload)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    _print_explain(payload)
    return 0


def _print_explain(payload: Dict[str, Any]) -> None:
    src = payload["ops_source"]
    print(f"op 注册表：{src['file']}（源：{src['source']}）")
    print(f"  指令 {payload['instruction_count']} 条 + "
          f"非指令 op {payload['non_instruction_count']} 条")
    print(f"  事务 {payload['txn_count']} 条（可用 {payload['available_txn_count']}），"
          f"分组：{', '.join(payload['groups'])}")

    risks = payload["risks"]
    live = [r for r in risks if r["present"] == "yes"]
    if live:
        print(f"\n⚠ 表里现存的疑点 {len(live)} 处（工具不替编码表做判断）：")
        for risk in live:
            print(f"  [{risk['code']}] {risk['title']}")
            print(f"      {risk['detail']}")

    if payload["collisions"]:
        print(f"\n同码指令 {len(payload['collisions'])} 组（靠 flags 或地址段区分）：")
        for item in payload["collisions"]:
            cross = "  ⚠ 跨类！" if item["cross_class"] else ""
            print(f"  {item['funct7']}  {', '.join(item['names'])}{cross}")

    if payload["class_mismatches"]:
        print(f"\nfunct7 前缀与声明类不符 {len(payload['class_mismatches'])} 条：")
        for item in payload["class_mismatches"][:8]:
            print(f"  {item['name']:<26} {item['funct7']}  "
                  f"声明={item['declared']} 推出={item['derived']}")

    for key, title in (("deferred_ops", "标了暂不做的指令"),
                       ("deferred_txns", "不可用的事务")):
        if payload[key]:
            print(f"\n{title} {len(payload[key])} 条：")
            for item in payload[key]:
                name = item.get("name") or item.get("id")
                why = (item.get("notes") or item.get("note") or "").strip()
                print(f"  {name}" + (f" —— {why[:70]}…" if why else ""))

    if "transaction" in payload:
        spec = payload["transaction"]
        print(f"\n事务 {spec['id']}（{spec.get('group', '')}）：")
        print(f"  指令组: {' → '.join(spec['ops'])}")
        for op in payload["ops"]:
            declared = op["declared_class"] or "（非指令）"
            print(f"    {op['name']:<26} {op['funct7'] or '—':<8} "
                  f"flags={op['flags']} {declared}")
        if spec.get("roles"):
            print(f"  角色: {spec['roles']}")
        if spec.get("requires"):
            print(f"  前置: {'；'.join(spec['requires'])}")


def cmd_ops(args: argparse.Namespace) -> int:
    payload = run_ops()
    if payload.get("error"):
        _print_error(payload)
        return 1
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    src = payload["source"]
    print(f"{payload['count']} 条（指令 {payload['instruction_count']} + "
          f"非指令 {payload['non_instruction_count']}）　源：{src['source']}")
    print(f"{'op':<28} {'类':<9} {'funct7':<9} flags")
    print("-" * 66)
    for op in payload["ops"]:
        flags = ",".join(str(v) for v in op["flags"]) if op["flags"] else "—"
        marker = " ←暂不做" if op["deferred"] else ""
        print(f"{op['name']:<28} {(op['op_class'] or '（非指令）'):<9} "
              f"{(op['funct7'] or '—'):<9} {flags}{marker}")
    return 0


# ════════════════════════════════════════════════════════════════
# 参数
# ════════════════════════════════════════════════════════════════

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="isa_gen_tools",
        description="NPU ISA 事务序列生成器 —— 场景 DSL → ISA 事务层 IR。"
                    "文档见 readme.md。")
    parser.add_argument("--version", action="version",
                        version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("validate", help="只做 DSL schema 校验")
    p.add_argument("dsl", help="场景 DSL（YAML）")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("compile", help="DSL → IR（含地址分配与落盘产物）")
    p.add_argument("dsl", help="场景 DSL（YAML）")
    p.add_argument("--out", "-o", metavar="DIR", help="按 §3.6 布局落盘到目录")
    p.add_argument("--seed", type=int, default=None,
                   help="覆盖 DSL 里的 meta.seed（它是覆盖，不是缺省）")
    p.add_argument("--max-txns", type=int, default=None, dest="max_txns",
                   help="最多生成多少条事务（缺省 24）")
    p.add_argument("--memmap", metavar="PATH", default=None,
                   help="memmap.yaml 路径（缺省用包内重建样例）")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("explain", help="注册表解读（碰撞 / 疑点 / 事务清单）")
    p.add_argument("--txn", metavar="ID", default="",
                   help="只看这一条事务的构成")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_explain)

    p = sub.add_parser("ops", help="列出 op 注册表")
    p.add_argument("--json", "-j", action="store_true", dest="json")
    p.set_defaults(func=cmd_ops)

    return parser


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _print_error(payload: Dict[str, Any]) -> None:
    """错误的统一打印 —— `kind` / `target` / `fix` 三件套缺一，报错就只能靠猜。"""
    print(f"✗ [{payload.get('kind', 'error')}] {payload['error']}", file=sys.stderr)
    if payload.get("target"):
        print(f"    @ {payload['target']}", file=sys.stderr)
    if payload.get("fix"):
        print(f"    → {payload['fix']}", file=sys.stderr)


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        print(f"文件不存在: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # 典型场景：`… | head` 把管道读端提前关掉 —— 不是工具的错误
        if getattr(exc, "errno", None) in (22, 32):     # EINVAL / EPIPE
            return 0
        raise


if __name__ == "__main__":
    sys.exit(main())
