"""
文件级证据链 —— git diff + 修改理由统一记录

无论修改了什么文件（RTL/Env/Model/TB），都记录:
  - 文件路径
  - git diff（修改内容）
  - 修改理由（为什么改）
  - 修改者（哪个 Agent 触发的）
  - SHA256 hash（防篡改）

这是"统一证据链"支柱的核心实现。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class FileChangeRecord:
    """单次文件修改记录"""
    file_path: str
    reason: str
    agent: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    git_diff: str = ""
    content_hash: str = ""
    hash: str = ""
    # 链内序号：用于连续性检查。DB 侧审计链（repository.verify_audit_chain）
    # 早就有 chain_index 连续性校验，文件级链一直缺这一项。
    seq: int = -1


class FileAuditTrail:
    """文件级审计链：记录所有文件修改的 git diff + 理由"""

    def __init__(self, repo_root: str = "."):
        self.repo_root = Path(repo_root)
        self.records: List[FileChangeRecord] = []
        self.prev_hash = ""

    def record(self, file_path: str, reason: str, agent: str = "") -> FileChangeRecord:
        """记录一次文件修改（git diff + 内容 hash + 理由 + hash 链）。

        `agent` 是**修改者**（字段名沿用历史的说法，不另开字段 —— 见 `open()`
        的说明）。它的取值空间现在有两类：
            · 一个 agent 角色名（`design` / `verify` / …）—— AI 干的
            · `human:<用户名>` —— 人干的
        """
        diff = self._git_diff(file_path)
        content_hash = self._content_hash(file_path)
        rec = FileChangeRecord(
            file_path=file_path, reason=reason, agent=agent,
            git_diff=diff, content_hash=content_hash, seq=len(self.records),
        )
        rec.hash = self._digest(rec, self.prev_hash)
        self.prev_hash = rec.hash
        self.records.append(rec)
        return rec

    # ════════════════════════════════════════════════════════════
    # 载入 / 落盘 —— 链要能**接着写**
    # ════════════════════════════════════════════════════════════

    @classmethod
    def open(cls, path: str | Path, repo_root: str = ".") -> "FileAuditTrail":
        """打开一条**已有的**链接着写（文件不存在就当新建）。

        为什么必须能续写：人工变更链是跨运行、跨天累积的。若只会「在内存里
        record() 然后整份覆盖」，每保存一次就抹掉之前所有人的编辑 —— 链看着还在，
        历史没了。这与 `n_finalize` 里那次落盘不同：那边是**一次运行一条新链**，
        本来就该从零开始。

        **关于"谁"**：记录里没有单独的 `author` 字段，用的是既有的 `agent`。
        它的 docstring 一直写着"修改者（哪个 Agent 触发的）"——语义本来就对，
        只是取值空间要加上 `human:<name>`。这样做还有个实际好处：`agent` **已经
        在 `_digest` 里**，所以人工编辑同样受哈希链保护。新开一个字段而不把它
        纳入 `_digest`，人工编辑就成了链上唯一可以随便改而不会被发现的部分；
        把它纳入 `_digest`，则**所有历史链全部作废**（`verify_persisted` 会把
        每一条旧记录判成 `hash_broken`）。复用既有字段两头都躲开了。
        """
        trail = cls(repo_root)
        p = Path(path)
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                data = {}
            for raw in data.get("records", []) or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    # 别写成 `int(raw.get("seq", -1) or -1)` —— `seq=0` 是**第一条
                    # 记录的合法值**，`or` 会把 0 当假值换成 -1，于是整条链从第一
                    # 条起就断（verify 的 `seq == i` 判不过）。踩过一次。
                    seq = int(raw.get("seq", -1))
                except (TypeError, ValueError):
                    seq = -1
                trail.records.append(FileChangeRecord(
                    file_path=str(raw.get("file_path", "")),
                    reason=str(raw.get("reason", "")),
                    agent=str(raw.get("agent", "")),
                    timestamp=str(raw.get("timestamp", "")),
                    git_diff=str(raw.get("git_diff", "")),
                    content_hash=str(raw.get("content_hash", "")),
                    hash=str(raw.get("hash", "")),
                    seq=seq,
                ))
            trail.prev_hash = str(data.get("final_hash") or
                                  (trail.records[-1].hash if trail.records else ""))
        return trail

    def save_default(self) -> Optional[Dict[str, Any]]:
        """把链增量落盘到 `<repo_root>/docs/file_change_chain.json`。

        原先这条链**只在 `n_finalize` 落一次**，于是中途失败/中断的 run
        在 `docs/` 下什么都没留下 —— 实测 `output_...152822`（没走到 finalize）
        只有一份 0 行的 tool_receipts.jsonl。而恰恰是失败的时候最需要审计。

        每记录一批文件调一次，磁盘上的链就始终是当前进度；`n_finalize` 那次
        带回读复核的写仍然是权威版本，会覆盖这里写的中间态。
        """
        try:
            return self.save(self.repo_root / "docs" / "file_change_chain.json")
        except OSError as e:
            # 落盘失败不该打断验证流程（证据缺失是问题，但不是致命问题）
            print(f"[warn] 文件审计链增量落盘失败: {e}")
            return None

    def save(self, path: str | Path) -> Dict[str, Any]:
        """落盘整条链（含 `final_hash` 与自校验结果）。

        自校验结果随文件一起写：读的人不必先会算哈希才能判断这条链完不完整。
        （要发现**落盘后被裁剪**，仍得用 `verify_persisted()` 回读复核。）
        """
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = self.to_dict()
        data["chain_valid"] = self.verify()
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                     encoding="utf-8")
        return data

    @staticmethod
    def _digest(rec: Any, prev_hash: str) -> str:
        """链哈希：文件 + 内容 hash + diff + 理由 + agent + 序号 + 前一个 hash。

        把 seq 纳入哈希，使「重排序号」也无法在不破坏链的前提下完成。
        """
        content = json.dumps({
            "file": rec.file_path if hasattr(rec, "file_path") else rec.get("file_path"),
            "reason": rec.reason if hasattr(rec, "reason") else rec.get("reason"),
            "agent": rec.agent if hasattr(rec, "agent") else rec.get("agent"),
            "diff": rec.git_diff if hasattr(rec, "git_diff") else rec.get("git_diff"),
            "content_hash": (rec.content_hash if hasattr(rec, "content_hash")
                             else rec.get("content_hash")),
            "seq": rec.seq if hasattr(rec, "seq") else rec.get("seq"),
        }, sort_keys=True, default=str) + prev_hash
        return hashlib.sha256(content.encode()).hexdigest()

    def _git_diff(self, file_path: str) -> str:
        """用 git diff 获取文件修改内容。"""
        try:
            r = subprocess.run(
                ["git", "diff", "--", file_path],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=10, cwd=str(self.repo_root),
            )
            return r.stdout if r.returncode == 0 else ""
        except Exception:
            return ""

    def _content_hash(self, file_path: str) -> str:
        """计算文件内容 SHA256（新文件 git diff 为空，但内容 hash 仍可防篡改）。

        **相对路径按 `repo_root` 解析**：项目级人工链里存的就是仓库相对路径
        （存绝对路径的话，换台机器同一次编辑会变成另一条记录），照着 cwd 去找会
        恒找不到、`content_hash` 恒为空 —— 而"内容哈希"正是防篡改的那一半。
        agent 侧传的是绝对路径，`is_absolute()` 直接放行，行为不变。

        哈希**委托给 `sha256_file`**，不自己再写一遍：那一份的 docstring 明写着
        「唯一哈希实现…避免再出现『一份分块、一份整读』的两套哈希」。这里原来就是
        `read_bytes()` 整读，与 L1 的分块实现并存 —— 小文件上看不出差别，但
        "同一份字节两套算法"正是那条规矩要挡的事，而且 `evidence check` 要拿
        同一条链的哈希去比对工作区文件，两边算法必须是一份。
        （分块与整读算出来的 hexdigest 相同，所以换过去对既有链**没有影响**。）
        """
        try:
            from src.runtime_plane.infrastructure.infrastructure import sha256_file

            p = Path(file_path)
            if not p.is_absolute():
                p = self.repo_root / p
            return sha256_file(p)
        except Exception:
            return ""

    def to_dict(self) -> dict:
        return {
            "records": [asdict(r) for r in self.records],
            "final_hash": self.prev_hash,
            "total_changes": len(self.records),
        }

    def verify(self) -> bool:
        """验证**内存中**的审计链完整性（含序号连续性与内容 hash 防篡改）。

        注意：本方法只校验内存里的 records —— 删掉尾部记录后，链会从剩下的
        记录重新算起，依然「通过」。要发现落盘后被裁剪，请用 verify_persisted()。
        """
        prev = ""
        for i, r in enumerate(self.records):
            if r.seq != i:
                return False
            if r.hash != self._digest(r, prev):
                return False
            prev = r.hash
        return True

    @classmethod
    def verify_persisted(cls, path: str | Path) -> Dict[str, Any]:
        """从**磁盘**回读并校验审计链。

        这是与 verify() 的关键区别：verify() 等于「自己验自己」——内存里剩什么
        就验什么，尾部被删不可检测。本方法重新读盘，因此能发现：
          - index_gap     序号不连续（中间被抽走一条）
          - hash_broken   某条内容的哈希与记录不符（被改写）
          - tail_truncated final_hash 与最后一条记录不一致（尾部被裁掉）
        返回 {valid, total, final_hash, issues}。
        """
        p = Path(path)
        if not p.exists():
            return {"valid": False, "total": 0, "final_hash": "", "issues": [
                {"type": "missing", "detail": f"{p} 不存在"}]}

        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            return {"valid": False, "total": 0, "final_hash": "",
                    "issues": [{"type": "unreadable", "detail": str(e)[:200]}]}

        records = data.get("records", []) or []
        issues: List[Dict[str, Any]] = []
        prev = ""
        for i, r in enumerate(records):
            if r.get("seq", i) != i:
                issues.append({"type": "index_gap", "at": i,
                               "expected": i, "actual": r.get("seq")})
            expect = cls._digest(r, prev)
            if r.get("hash") != expect:
                issues.append({"type": "hash_broken", "at": i,
                               "file": r.get("file_path")})
                break  # 链已断，后续比较无意义
            prev = r["hash"]

        # 尾部指针必须等于最后一条记录的 hash —— 删掉尾部记录会在这里暴露
        declared = data.get("final_hash", "")
        last = records[-1].get("hash") if records else ""
        if declared != last:
            issues.append({"type": "tail_truncated",
                           "final_hash": declared, "last_record_hash": last})

        return {"valid": not issues, "total": len(records),
                "final_hash": declared, "issues": issues}


# 全局单例（可选）
_global_trail: Optional[FileAuditTrail] = None


def get_file_audit_trail(repo_root: str = ".") -> FileAuditTrail:
    """获取全局文件审计链单例。"""
    global _global_trail
    if _global_trail is None:
        _global_trail = FileAuditTrail(repo_root)
    return _global_trail


def record_file_change(file_path: str, reason: str, agent: str = "",
                       repo_root: str = ".") -> dict:
    """便捷入口：记录一次文件修改。"""
    trail = get_file_audit_trail(repo_root)
    rec = trail.record(file_path, reason, agent)
    return asdict(rec)
