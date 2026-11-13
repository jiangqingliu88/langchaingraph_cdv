"""**规则草案** —— 让规则库"从失败里长"，而不是只靠人手写。

## 现在缺的是哪一环

规则库要能长大，需要三个动作：**发现 → 记录 → 归纳成规则**。这个仓库已经有的：

  · 发现：debug agent 把失败**取指纹 + 归类**（`debug.fingerprint_error`）；
    ops 也把 bench 侧的挂死按指纹归过（`harness_triage`）
  · 记录：`rule_stats` 记「哪条规则命中过多少次」（上一轮加的）
  · 归纳：**没有** —— 定案之后那句"这类错以后这么判"没人接

于是规则只能靠人回头读日志再手写一条 `@rule`。这个仓库里两条现成的规则
（`is_elab_failure_line` 从误判事故收窄、`port_not_in_txn` 从端口归属问题长出来）
都是**这么来的** —— 说明这个动作在发生，只是没有落点。

## 这里做什么、不做什么

**只起草，不自动生效。** 一条校验规则会改变"什么算错"，那是判断，不是统计：
机器把指纹、归类、证据摆出来，并附上**可直接粘贴的 `@rule` 骨架**，由人拍板。
这与项目里其它不可逆动作（豁免审批、RTL 回滚）同一个口径 —— **机器提议、人提交**。

草案落在 `<运行目录>/docs/rule_drafts.jsonl`（一行一条，追加、按指纹去重），
同时写一份 `rule_drafts.md`：那是给人看的，带粘贴骨架。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 草案的三种去处 —— 决定"这条规则该拦在哪一步"
STAGE_TITLES = {
    "generate": "生成时拦（写进 `semantic_check` 的 @rule，产出时就判）",
    "regress": "回归时拦（写进 ops 的判据，跑完就判）",
    "signoff": "签核时拦（写进 audit 门禁，签之前判）",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rule_skeleton(draft: Dict[str, Any]) -> str:
    """可以**直接粘贴**的 `@rule` 骨架 —— 附上测试骨架。

    生成的是骨架不是成品：判据得人写（"这类错怎么认"是领域知识），
    但样板（装饰器、签名、注册位置、测试文件）不该让人再抄一遍。
    """
    kind = str(draft.get("kind") or "agent")
    rule_id = str(draft.get("rule_id") or "TBD")
    severity = str(draft.get("severity") or "warning")
    doc = str(draft.get("doc") or "TODO: 一句话说明这条规则拦什么")
    return f'''# 规则草案（{draft.get("run_id", "")} · 指纹 {draft.get("fingerprint", "")[:12]}）
# 证据：{str(draft.get("note", ""))[:160]}
# 落到 src/generation/uvm_tools/tool_uvm/semantic_check.py：

@rule("{kind}", "{rule_id}", "{severity}", "{doc}")
def _{rule_id}(item) -> List[str]:
    """TODO：判据（"这类错怎么认"是领域知识，得人写）。"""
    return []


# 配套一条测试（tests/ 或语义检查自己的测试文件）：
def test_{rule_id}_catches_the_real_case():
    """钉住它拦的那个真实案例 —— 用抓到这条草案的那次证据。"""
    raise NotImplementedError("{doc}")
'''


def draft_from_failure(fingerprint: str, category: str = "", note: str = "",
                       run_id: str = "", stage: str = "regress",
                       kind: str = "agent",
                       severity: str = "warning") -> Dict[str, Any]:
    """一次定案的失败 → 一条规则草案。

    **`rule_id` 从 `category` 派生**（人只改词，不用从零起名）；取不到 category
    就用指纹前 8 位 —— 名字难看但唯一，好过占一个通用名把后来的草案撞掉。
    """
    import re

    slug = re.sub(r"[^a-z0-9]+", "_", str(category or "").lower()).strip("_")
    rule_id = f"learned_{slug}" if slug else f"learned_{str(fingerprint)[:8]}"
    return {
        "run_id": run_id,
        "fingerprint": str(fingerprint),
        "category": str(category or ""),
        "note": str(note or "")[:300],
        "stage": stage if stage in STAGE_TITLES else "regress",
        "kind": kind,
        "severity": severity,
        "rule_id": rule_id,
        "created_at": _now(),
    }


def drafts_path(run_dir: Path) -> Path:
    return Path(run_dir) / "docs" / "rule_drafts.jsonl"


def write_drafts(run_dir: Path, drafts: List[Dict[str, Any]]) -> int:
    """追加写草案（**按指纹去重** —— 同一个错跑十次只该有一条草案）。

    返回新写入的条数。失败不抛：起草是旁路，不该拖垮运行。
    """
    if not drafts:
        return 0
    try:
        root = Path(run_dir)
        path = drafts_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        known = {d.get("fingerprint") for d in collect_drafts(root)}
        fresh = [d for d in drafts if d.get("fingerprint") not in known]
        if not fresh:
            return 0
        with path.open("a", encoding="utf-8") as fh:
            for draft in fresh:
                fh.write(json.dumps(draft, ensure_ascii=False) + "\n")
        # 给人看的那份：带粘贴骨架
        md = root / "docs" / "rule_drafts.md"
        with md.open("a", encoding="utf-8") as fh:
            for draft in fresh:
                fh.write(f"\n## {draft['rule_id']}（{draft['run_id']}）\n\n")
                fh.write(f"- 该拦在哪：{STAGE_TITLES[draft['stage']]}\n")
                fh.write(f"- 证据：{draft['note']}\n\n")
                fh.write("```python\n" + rule_skeleton(draft) + "```\n")
        return len(fresh)
    except Exception:                                  # noqa: BLE001
        return 0


def collect_drafts(run_dir: Path) -> List[Dict[str, Any]]:
    """读回草案（界面/CLI 用）。坏行跳过，**读不到就给空列表**。"""
    path = drafts_path(Path(run_dir))
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and item.get("fingerprint"):
                out.append(item)
    except OSError:
        return []
    return out


def drafts_from_triage(triage: List[Dict[str, Any]], run_id: str) -> List[Dict[str, Any]]:
    """把 `harness_triage` 那种指纹归类结果翻成草案。

    这一路专治"bench 侧挂死"：它反复出现、有指纹、却**没有任何规则在拦它** ——
    正是最该长出一条规则的地方（拦在回归时：这类挂死不该把整批结果污染）。
    """
    out = []
    for item in triage or []:
        fp = str(item.get("fingerprint", "") or "")
        if not fp:
            continue
        out.append(draft_from_failure(
            fingerprint=fp,
            category=str(item.get("category", "") or "bench_hang"),
            note=str(item.get("note", "") or ""),
            run_id=run_id, stage="regress", severity="warning"))
    return out


def _accepted_path(run_dir: Path) -> Path:
    return Path(run_dir) / "docs" / "rule_drafts.accepted.json"


def accepted_ids(run_dir: Path) -> List[str]:
    """已经被人接受过的草案 id。"""
    path = _accepted_path(run_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(x) for x in (data.get("accepted") or [])] if isinstance(data, dict) else []


def mark_accepted(run_dir: Path, rule_id: str, by: str = "") -> bool:
    """**人拍板**：这条草案我接了（去写进 semantic_check）。

    接受是**人的动作**，所以记在单独一份文件里，不和机器写的草案混在一起 ——
    证据链要能分开"机器提议了什么"与"人接受了什么"。
    """
    if not rule_id:
        return False
    try:
        root = Path(run_dir)
        path = _accepted_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"accepted": accepted_ids(root), "records": []}
        if path.exists():
            try:
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    data = {"accepted": [str(x) for x in (loaded.get("accepted") or [])],
                            "records": list(loaded.get("records") or [])}
            except ValueError:
                pass
        if rule_id not in data["accepted"]:
            data["accepted"].append(rule_id)
            data["records"].append({"rule_id": rule_id, "by": str(by or ""), "at": _now()})
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except Exception:                                  # noqa: BLE001
        return False
