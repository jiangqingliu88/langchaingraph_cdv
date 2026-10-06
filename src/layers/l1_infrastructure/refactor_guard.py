"""改 RTL 的**事务性**保证 —— 改前快照、改后按影响面重跑、破坏了就回滚。

闭环会为了修一个 bug 去改 RTL，而改动**可能把已经好的功能改坏**。原来没有任何
东西在改完之后验证这一点：

  · 守卫（`GuardianAgent`）要的"黄金基线"只在**收敛时**才存，而这个闭环从没
    收敛过 —— 于是每一次改 RTL 都被「无黄金基线，跳过守卫」放行；
  · 改完直接进下一轮，轮次用尽时**直接进 audit** —— "改动前后"从来没有对比。

所以这里做三件事，**不依赖黄金基线**（基线就是"上一轮跑通的那些用例"，现成的）：

  1. `snapshot()` 改前：RTL 文件内容 + 哈希，以及**上一轮通过的用例集**
  2. `scope()`    改后跑多少：改动只落在一个 IP 上 → 只跑相关 tag 的用例；
                  动了顶层/认不出来 → 全量（宁可多跑，不可漏跑）
  3. `verify()`   重跑 + 比对：**原先通过的现在还过吗**；不过 → `rollback()` 把
                  RTL 恢复成快照（不依赖 git —— 运行目录不一定在版本控制里）

判断标准只有一条：**"改动前通过的用例，改动后必须仍然通过"**。修没修好那个
bug 是另一回事（下一轮 ops 会看），这里只管"别把好的改坏"。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


#: 顶层/共享文件改动的判据：文件名等于设计名（`apb_uart.sv`）时，影响的不是一个
#: IP 而是整条集成，**必须全量**。
def _is_top_level(stem: str, design_name: str) -> bool:
    return bool(design_name) and stem.lower() == design_name.lower()


@dataclass
class Snapshot:
    """改 RTL 之前的状态。"""
    files: Dict[str, bytes] = field(default_factory=dict)   # 相对 rtl/ 的路径 → 内容
    hashes: Dict[str, str] = field(default_factory=dict)
    passing: List[str] = field(default_factory=list)        # 上一轮通过的用例名（已剥 test_）


class RefactorGuard:
    """一次"改 RTL"的事务边界。"""

    def __init__(self, output_root: Path, design_name: str = ""):
        self.root = Path(output_root)
        self.rtl_dir = self.root / "rtl"
        self.design_name = design_name

    # ── 1. 改前 ────────────────────────────────────────────────

    def snapshot(self) -> Snapshot:
        """记下 RTL 的全部内容 + 上一轮通过的用例集。

        内容而不是只记哈希 —— 回滚要用它把文件写回去。
        """
        snap = Snapshot()
        if self.rtl_dir.is_dir():
            for f in sorted(self.rtl_dir.rglob("*.sv")):
                data = f.read_bytes()
                rel = str(f.relative_to(self.rtl_dir)).replace("\\", "/")
                snap.files[rel] = data
                snap.hashes[rel] = _sha256(data)
        snap.passing = self._last_passing_tests()
        return snap

    def _last_passing_tests(self) -> List[str]:
        """上一轮回归里**通过**的用例名（`test_` 前缀剥掉，与框架里的口径一致）。"""
        report = self.root / "regression_run" / "report.json"
        if not report.exists():
            return []
        try:
            data = json.loads(report.read_text(encoding="utf-8", errors="replace"))
        except (OSError, ValueError):
            return []
        out = []
        for task in data.get("tasks") or []:
            name = str(task.get("name", ""))
            if name and str(task.get("status", "")).lower() == "pass":
                out.append(name[len("test_"):] if name.startswith("test_") else name)
        return sorted(set(out))

    # ── 2. 改后：改动落在哪 ─────────────────────────────────────

    def changed_files(self, snap: Snapshot) -> List[str]:
        """相对快照，**内容变了的 RTL 文件**（新增的也算）。"""
        changed = []
        for rel, old_hash in snap.hashes.items():
            f = self.rtl_dir / rel
            if not f.exists():
                changed.append(rel)                      # 被删了 —— 也算改动
            elif _sha256(f.read_bytes()) != old_hash:
                changed.append(rel)
        known = set(snap.hashes)
        if self.rtl_dir.is_dir():
            for f in sorted(self.rtl_dir.rglob("*.sv")):
                rel = str(f.relative_to(self.rtl_dir)).replace("\\", "/")
                if rel not in known:
                    changed.append(rel)                  # 新增文件
        return sorted(set(changed))

    def scope(self, snap: Snapshot, plan: Optional[dict] = None) -> dict:
        """这次改动**跑多少回归** —— 由**根因的验证计划 + 改动面**共同决定。

        `plan` 来自决策层的 `verification_plan(root_cause)`（CDC 全量、协议/复位
        按 tag、编译类只编译、死代码交人）。没有 plan 时按改动面猜（老路径）。

        改动面这一侧：
          · 动了顶层（`<design>.sv`）→ 全量（影响整条集成）
          · 改动文件名能拼出 tag（`uart_tx.sv` → `uart`）→ 只跑带这个 tag 的用例
          · 拼不出 tag → 全量

        **两个来源取更宽的那个**：计划说全量就全量；计划说按 tag 而改动面拼不出
        tag 也全量 —— 多跑一轮的代价是几十秒，漏跑的代价是"改坏了不知道"。
        """
        changed = self.changed_files(snap)
        if not changed:
            return {"mode": "none", "tags": "", "changed": [], "why": "RTL 没变，无需重跑"}

        by_change = self._scope_by_change(changed)
        if not plan:
            return by_change

        want = plan.get("scope", "by_change")
        if want == "full":
            return {**by_change, "mode": "full", "tags": "",
                    "why": f"根因验证计划要求全量（{plan.get('why', '')}）"}
        if want == "compile":
            return {**by_change, "mode": "compile", "tags": "",
                    "why": f"根因只影响编译（{plan.get('why', '')}）—— 不必全仿真"}
        if want == "human":
            return {**by_change, "mode": "human", "tags": "",
                    "why": f"根因需人工判定（{plan.get('why', '')}）"}
        if want == "tagged":
            tags = self._pick_tags(plan.get("tags", ""), changed)
            if tags:
                return {**by_change, "mode": "subset", "tags": tags,
                        "why": f"根因要求带上 {tags} 定向用例（{plan.get('why', '')}）"}
            return {**by_change, "mode": "full",
                    "why": f"根因要求 {plan.get('tags')} 定向用例，但回归里没有这些 tag "
                           f"—— 退回全量（宁可多跑）"}
        return by_change                                  # by_change：按改动面

    def _scope_by_change(self, changed: List[str]) -> dict:
        if any(_is_top_level(Path(c).stem, self.design_name) for c in changed):
            return {"mode": "full", "tags": "", "changed": changed,
                    "why": f"动了顶层 {self.design_name} —— 影响整条集成"}
        tokens = self._pick_tags("", changed)
        if not tokens:
            return {"mode": "full", "tags": "", "changed": changed,
                    "why": f"改动（{', '.join(changed)}）拼不出已知 tag，按全量跑"}
        return {"mode": "subset", "tags": tokens, "changed": changed,
                "why": f"改动只落在 {tokens} 相关文件上"}

    def _pick_tags(self, wanted: str, changed: List[str]) -> str:
        """哪些 tag 该跑。

        **计划点名了就以计划为准**（哪怕一个都对不上 → 返回空 → 调用方退回全量）。
        这里**不许**悄悄换成"从改动文件拼出来的 tag" —— 那等于把"这类 bug 该验的
        `reset` 用例"换成"改过的 uart 用例"，看着跑了、其实没验该验的（这个漏洞
        写出来就被测试抓到了）。只有计划**没点名**时才按改动文件拼。
        """
        available = self._available_tags()
        if wanted:
            picked = {t.strip().lower() for t in wanted.split(",") if t.strip()}
            return ",".join(sorted(picked & available))
        tokens = set()
        for rel in changed:
            for part in Path(rel).stem.lower().split("_"):
                if len(part) >= 3 and part in available:
                    tokens.add(part)
        return ",".join(sorted(tokens))

    def _available_tags(self) -> set:
        """回归配置里出现过的 tag（小写）—— 用来判断"改动能不能对上用例"。"""
        cfg = self.root / "inputs" / "yaml" / "regression.yaml"
        if not cfg.exists():
            return set()
        tags = set()
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return set()
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("tags:") and "[" in line:
                inner = line[line.index("[") + 1:line.rindex("]")]
                for tag in inner.split(","):
                    tag = tag.strip().strip('"').strip("'").lower()
                    if tag:
                        tags.add(tag)
        return tags

    # ── 3. 重跑 + 比对 + 回滚 ───────────────────────────────────

    def verify(self, snap: Snapshot, run_regression=None, plan: Optional[dict] = None) -> dict:
        """重跑（按 `scope` 定的范围）并比对"原先通过的现在还过吗"。

        `run_regression` 可注入（测试用）；默认走 `InfrastructureManager`。
        """
        scope = self.scope(snap, plan)
        result = {"scope": scope, "before": list(snap.passing), "regressed": [],
                  "after": [], "ran": False, "error": "",
                  "fix_kind": self.classify_fix_kind(scope["changed"])}
        if scope["mode"] == "none":
            return result
        if scope["mode"] in ("compile", "human"):
            # 这两类**不进回归比对**，理由写进结果（不是"跳过"而是"不该跑"）：
            # 编译类只需编译门禁（design agent 已经跑过 vlog）；死代码类要人判。
            result["error"] = scope["why"]
            return result
        if not snap.passing:
            # 没有"原先通过的用例"就无从比对 —— 如实说，不当成通过
            result["error"] = "上一轮没有通过的用例记录，无法比对（跳过验证）"
            return result

        try:
            if run_regression is None:
                from src.layers.l1_infrastructure.infrastructure import InfrastructureManager
                run_regression = InfrastructureManager(self.root).run_regression
            kwargs = {"tags": scope["tags"]} if scope["mode"] == "subset" else {}
            outcome = run_regression(**kwargs) or {}
        except Exception as e:                        # noqa: BLE001 重跑失败不该拖垮闭环
            result["error"] = f"重跑失败: {e}"[:200]
            return result

        result["ran"] = True
        result["run"] = {k: outcome.get(k) for k in ("status", "passed", "failed", "total")}
        after_passing = set(self._last_passing_tests())
        result["after"] = sorted(after_passing)

        # **比对的是"原先通过的用例"**：现在不在通过集里就算被改坏了。
        # 注意 subset 模式下只跑了部分用例 —— 没跑的用例不在 after 里，
        # 所以只在**跑过的**用例上比对（用 scope 的 tag 圈定范围）。
        if scope["mode"] == "subset":
            watched = [t for t in snap.passing if self._matches_tags(t, scope["tags"])]
        else:
            watched = list(snap.passing)
        result["watched"] = watched
        result["regressed"] = sorted(t for t in watched if t not in after_passing)
        return result

    @staticmethod
    def _matches_tags(test_name: str, tags: str) -> bool:
        """用例名里含某个 tag 就算落在范围内（框架的 tag 来自用例的 scenario）。"""
        low = test_name.lower()
        return any(t and t in low for t in tags.split(","))

    #: 「这次是怎么修的」—— 从 **diff 判**，不是事前猜。
    #: 事前只能判"根因是哪一类"（`FIX_*_bug`），"用了什么手段"是改完才知道的事。
    _FIX_KIND_TOKENS = (
        ("sync_reset", ("always_ff", "sync", "synchronizer", "async_fifo", "gray",
                        "cdc", "复位", "rst_n")),
        ("protocol", ("ready", "valid", "handshake", "skid", "backpressure")),
        ("pipelining", ("<= ", "reg ", "pipeline", "stage")),
        ("param", ("localparam", "parameter", "generate", "`ifdef", "WIDTH")),
    )

    def classify_fix_kind(self, changed: List[str], snap: Optional[Snapshot] = None) -> str:
        """**修复手段**：从改动内容判（`logic` / `structural` / `pipelining` /
        `sync_reset` / `protocol` / `param` / `integration`）。

        这是**记录字段**，不驱动行为 —— 手段是改完才知道的，拿它当决策依据等于
        事前猜。写进证据链供人复盘："这次是加同步器解决的，还是改了个条件"。

        粗，但**是读出来的而不是编的**：读改动后的文件、按关键词与改动幅度归类；
        判不出就是 `logic`（最常见的那类：改条件/赋值/优先级）。
        """
        if not changed:
            return ""
        if all(_is_top_level(Path(c).stem, self.design_name) for c in changed):
            return "integration"
        added = ""
        long_lines = 0
        for rel in changed:
            f = self.rtl_dir / rel
            if not f.exists():
                continue
            text = f.read_text(encoding="utf-8", errors="replace")
            added += text.lower() + "\n"
            long_lines += text.count("\n")
        for kind, tokens in self._FIX_KIND_TOKENS:
            if sum(added.count(t.lower()) for t in tokens) >= 2:
                return kind
        # 改动幅度：相对快照新增的行数多，就按结构重构算
        if snap is not None:
            old_lines = sum(v.count(b"\n") for v in snap.files.values())
            if old_lines and long_lines > old_lines * 1.5:
                return "structural"
        return "logic"

    def rollback(self, snap: Snapshot) -> List[str]:
        """把 RTL 写回快照状态，返回被恢复的文件（相对路径）。

        用快照内容恢复而不是 `git checkout`：运行目录不一定在版本控制里，
        而且改动可能压根没提交过。
        """
        restored = []
        for rel, data in snap.files.items():
            f = self.rtl_dir / rel
            if not f.exists() or f.read_bytes() != data:
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_bytes(data)
                restored.append(rel)
        return sorted(restored)
