"""flow_tools 共享只读辅助 —— 运行目录解析 / JSON(JSONL) 读取 / 产物体检。

`api.py` 按域拆开后，这是所有域共用的最小公共面；**只读、不抛异常**。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROLE_ARTIFACT_DIRS: Dict[str, tuple] = {
    "design":   (("rtl", "RTL"),),
    "model":    (("model", "参考模型"),),
    "verify":   (("agents", "UVM 组件"), ("env", "环境"),
                 ("assertions", "断言"), ("inputs", "输入 YAML")),
    "ops":      (("sim", "仿真 / 回归"),),
    "coverage": (("coverage", "覆盖率"),),
    "debug":    (),
    "audit":    (),
}


MAX_FILES_PER_DIR = 40


def _stages_of(events: List[Dict[str, Any]], role: str) -> List[Dict[str, Any]]:
    """该 agent 的阶段事件 → 行。用 finished/failed（它们带状态与耗时）。"""
    rows: List[Dict[str, Any]] = []
    for event in events:
        if str(event.get("agent", "")) != role:
            continue
        if event.get("kind") not in ("stage.finished", "stage.failed"):
            continue
        rows.append({
            "stage": str(event.get("stage", "")),
            "title": str(event.get("title") or event.get("stage") or ""),
            "round": int(event.get("round", 0) or 0),
            "status": str(event.get("status", "")),
            "duration_s": round(float(event.get("duration_s", 0.0) or 0.0), 2),
            "summary": _payload_line(event.get("payload") or {}),
        })
    return rows


def _payload_line(payload: Dict[str, Any]) -> str:
    """阶段事件 payload → 一行摘要。`delta` 是节点写回的全量状态，别整个铺出来。"""
    if not isinstance(payload, dict):
        return ""
    bits = [f"{key}={payload[key]}" for key in
            ("status", "passed", "failed", "count", "score", "reason",
             "coverage", "verdict", "message") if key in payload]
    if bits:
        return " ".join(bits)
    delta = payload.get("delta")
    if isinstance(delta, dict):
        return "、".join(sorted(str(k) for k in delta)[:6])
    error = payload.get("error")
    return str(error) if error else ""


def _artifacts_of(root: Path, role: str) -> tuple:
    """该 agent 的产物目录 → 每个目录一行（含文件数与文件名，超量截断并记账）。"""
    rows: List[Dict[str, Any]] = []
    notes: List[str] = []
    for dirname, title in ROLE_ARTIFACT_DIRS.get(role, ()):
        target = root / dirname
        if not target.is_dir():
            continue
        files = sorted(p for p in target.rglob("*") if p.is_file())
        listed = files[:MAX_FILES_PER_DIR]
        rows.append({
            "dir": dirname,
            "title": title,
            "file_count": len(files),
            "files": [{"name": str(p.relative_to(target)),
                       "size_kb": _size_kb(p)} for p in listed],
        })
        if len(files) > len(listed):
            # 截断要记账 —— 静默截断会让人以为"产出就这么多"
            notes.append(f"{dirname}/ 有 {len(files)} 个文件，界面只列前 "
                         f"{MAX_FILES_PER_DIR} 个。")
    return rows, notes


def _resolve_run_dir(run_dir: str):
    """(Path, error) —— 给四个入口共用同一套「目录得像个运行目录」的检查。

    出来的一定是**绝对路径**：下面报出去的 `db` / `report` / `wave` / `cov` 都是
    在这个 root 上拼出来的，root 相对，报出来的产物路径就全是相对的 —— 而界面拿
    这些路径去 `QUrl.fromLocalFile()` 打开时，相对路径**什么都不做也不报错**。
    在这里落一次绝对化，四个入口一起修好，好过在每个调用点各拼一次。
    """
    if not isinstance(run_dir, str) or not run_dir.strip():
        return None, {"error": "没有给运行目录（先在「运行历史」里选一次运行）"}
    root = Path(run_dir)
    if not root.exists():
        return None, {"error": f"运行目录不存在：{root}"}
    if not root.is_dir():
        return None, {"error": f"运行目录不是目录（是个文件）：{root}"}
    return root.resolve(), None


def _read_json(path: Path) -> Optional[Dict[str, Any]]:
    """读 JSON；不在 / 坏了一律返回 None（由调用方按"缺失"处理，不抛）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    """逐行读 JSONL；坏行跳过（与 `_read_journal` 同一纪律）。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _read_journal(root: Path) -> List[Dict[str, Any]]:
    """读 `docs/run_events.jsonl`。**逐行解析、坏行跳过** —— 日志是追加写的，
    进程被杀时最后一行可能只写了一半，那一行不该让整份日志读不出来。

    只读磁盘，不调 run_service：工具层不该依赖 L2 的读接口。
    """
    path = root / "docs" / "run_events.jsonl"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    events: List[Dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue                      # 半行 —— 跳过，不因它丢掉整份日志
        if isinstance(item, dict):
            events.append(item)
    return events


def _size_kb(path: Path) -> float:
    try:
        return round(path.stat().st_size / 1024, 1)
    except OSError:
        return 0.0


def _short(value: Any, limit: int = 80) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _num(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


UVM_SCHEMA = "uvm_config"


def _spec_of_run(root: Path) -> Dict[str, Any]:
    """运行目录里的 `spec.json` —— `find_case_model` 认 `specs/<模块>/` 时要用它。"""
    return _read_json(root / "spec.json") or {}


def _rel_to(path, root: Path, fallback: str = "") -> Path:
    """展示用：能相对化就相对化，不能就原样；**`None` 退回 `fallback`**。

    `path` 会是 `None`（模型没找到），而调用方那边是 `root / rel` —— 直接把
    `None` 传下去就是 `TypeError`，而那个异常会**把前面攒的 notes 一起带走**
    （实测：页面上一句解释都没有，只剩一张空表）。
    """
    if path is None:
        return Path(fallback) if fallback else Path(".")
    try:
        return path.relative_to(root)
    except ValueError:
        return path


def _artifact(root: Path, rel: Path, group: str, schema: Optional[str]) -> Dict[str, Any]:
    """一份产物的体检：在不在 / 多大 / 什么哈希 / schema 过不过。"""
    path = root / rel
    exists = path.is_file()
    out: Dict[str, Any] = {
        "path": str(rel).replace("\\", "/"),
        "name": rel.name,
        "group": group,
        "schema": schema,
        "exists": exists,
        "size_kb": _size_kb(path) if exists else 0.0,
        "sha256": "",
        "issues": 0,
        "errors": 0,
        "warnings": 0,
        "messages": [],
    }
    if not exists:
        return out

    from src.layers.l1_infrastructure.infrastructure import sha256_file
    out["sha256"] = sha256_file(path)          # 与证据链同一份哈希实现

    if schema:
        issues = _schema_issues(path)
        out["issues"] = len(issues)
        out["errors"] = sum(1 for i in issues if i.get("severity") == "error")
        out["warnings"] = sum(1 for i in issues if i.get("severity") == "warning")
        # 只带前几条给界面定位用 —— 诊断面板是给人扫读的，不是日志转储
        out["messages"] = [
            {"severity": i.get("severity"), "line": i.get("line"),
             "text": _short(i.get("message", ""), 120)}
            for i in (issues if out["errors"] else issues[:2])[:5]
        ]
    return out


def _schema_issues(path: Path) -> List[Dict[str, Any]]:
    """按 UVM schema 校验一份 YAML，转成可 JSON 化的 dict 列表。

    校验器加载一次缓存着 —— 一张审查台上每次点开文件都重新 parse 一遍 schema
    是纯浪费，而 schema 是仓库里的静态文件。
    """
    try:
        from src.tools.generation.uvm_tools.tool_uvm.schema_check import get_checker

        issues = get_checker().check([path])
    except Exception as exc:                   # 依赖缺失 / schema 坏 —— 别把界面拖挂
        return [{"severity": "error", "line": None,
                 "message": f"schema 校验没能跑起来：{exc}"}]
    out = []
    for issue in issues:
        out.append({
            "severity": getattr(issue, "severity", "error"),
            "line": _line_of(getattr(issue, "target", ""), path),
            "message": str(issue),
        })
    return out


def _line_of(target: str, path: Path) -> Optional[int]:
    """从 issue 的 target（形如 `bench.yaml::bench.agents`）找它在文件里的行号。

    找不到就算了 —— 点不过去总比跳到一个错的行号好（那会让人以为问题在别处）。
    """
    if not target:
        return None
    field = target.split("::")[-1].split(".")[-1]
    if not field:
        return None
    try:
        for index, line in enumerate(path.read_text(encoding="utf-8",
                                                   errors="replace").splitlines(), 1):
            if line.strip().startswith(f"{field}:"):
                return index
    except OSError:
        return None
    return None


_COV_FIELDS = (("overall_pct", "总覆盖率"), ("functional_pct", "功能覆盖率"),
               ("statement_pct", "语句"), ("branch_pct", "分支"),
               ("toggle_pct", "翻转"), ("condition_pct", "条件"))
