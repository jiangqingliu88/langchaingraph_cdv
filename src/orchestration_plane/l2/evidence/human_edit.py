"""人工变更 → 证据链。

在此之前，**人在界面上改了什么，一条痕迹都不留**：GUI 的保存就是一句
`Path.write_text`（`modules/ide/manual_nodes/module.py:224`、
旧的 case 建模界面已删除），哈希链、运行日志、五层证据里都没有。
对一个把"可审计、可追溯"当第一承诺的产品，这是正中间那个洞。

为什么人工编辑**不能**写进某次运行的 `file_change_chain.json`
    `n_finalize` 是拿**内存里的** `rt.file_audit` 整份覆盖落盘的
    （`graph.py:942-950`）。也就是说那份链只装"这次运行期间、这个进程内存里
    agent 改过的文件"。往里塞人工编辑有两个必然后果：

      · 运行**暂停期间**（检查点等人）人的编辑，会在收尾落盘时被覆盖掉；
      · 运行**结束之后**人的编辑，根本没有运行上下文可挂。

    而人工编辑的真实生命周期更长：改的是**仓库里的文件**，一次编辑会影响后续
    多次运行，一次运行也可能横跨多次编辑。硬塞进运行链，语义就错了。

所以人工变更走**自己的项目级链**：`.signoffai/human_edits.json`
    —— 跨 run、跨天累积，与 `.signoffai/rl_policy.json` 同一个成长目录。
    用的是**同一份 `FileChangeRecord` 和同一份 `_digest`**：哈希链绝不能有两套
    实现，否则两边的防篡改强度会悄悄不一致。

与某次运行的关系靠**日志锚点**，不靠复制
    编辑发生时若指定了 `run_id`，就往那次运行追加一条 `human.edit` 事件。日志是
    追加写的，不会被谁覆盖，而且**时序落在那儿** —— 时间线上能看出一轮回归之前
    人改了什么。复制进运行链则是第二份真相。
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

logger = structlog.get_logger()

#: 项目级人工变更链的位置（相对仓库根）
CHAIN_RELPATH = Path(".signoffai") / "human_edits.json"

#: 没填理由时写进链里的字面量。**不编一个像样的理由** —— 那比空着更糟：
#: 读链的人分不清"这是人写的理由"还是"系统补的"。
NO_REASON = "（未填理由）"


def project_chain_path(repo_root: str | Path = ".") -> Path:
    """项目级人工变更链的完整路径。"""
    return Path(repo_root).resolve() / CHAIN_RELPATH


from src.runtime_plane.core.runtime.identity import resolve_author  # noqa: F401


def record_human_edit(path: str, reason: str = "", author: str = "",
                      run_id: str = "", repo_root: str = ".") -> Dict[str, Any]:
    """记一次人工编辑：进项目级链；若给了 `run_id`，再往那次运行写一条日志事件。

    **两个参数是必给的**：`path`（改的是哪个文件）和至少一个能说明"为什么"的
    `reason`。理由留空不算失败 —— 链里会写 `（未填理由）`，不编一个像样的理由
    顶上去。少写理由是工作流的选择，编理由是证据的问题。

    返回一份自陈，调用方（界面）据此提示"已记账"。
    """
    target = Path(path)
    if not target.is_absolute():
        target = Path(repo_root).resolve() / target
    if not target.is_file():
        return {"recorded": False, "error": f"文件不存在：{target}"}

    who = resolve_author(author)
    chain_path = project_chain_path(repo_root)

    from .file_audit import FileAuditTrail

    trail = FileAuditTrail.open(chain_path, repo_root=str(repo_root))
    before = len(trail.records)
    record = trail.record(_chain_relative(target, repo_root),
                          (reason or "").strip() or NO_REASON,
                          f"human:{who}")
    trail.save(chain_path)

    out: Dict[str, Any] = {
        "recorded": True, "author": who, "reason": record.reason,
        "file": record.file_path,
        "seq": record.seq, "hash": record.hash,
        "content_hash": record.content_hash,
        "chain": str(chain_path), "total_changes": len(trail.records),
        "appended": len(trail.records) - before,
        "journal": None,
    }
    if run_id:
        out["journal"] = _note_in_run(run_id, record, who, repo_root)
    logger.info("人工编辑已记账", file=record.file_path, author=who,
                seq=record.seq, run_id=run_id or "-")
    return out


def _chain_relative(target: Path, repo_root: str | Path) -> str:
    """链里存**相对仓库根**的路径。

    存绝对路径的话，换台机器、换个检出目录，同一次编辑就变成了两条不同记录，
    「改的是哪个文件」这件事也没法比对。
    """
    try:
        return str(target.relative_to(Path(repo_root).resolve())).replace("\\", "/")
    except ValueError:
        return str(target)


def _note_in_run(run_id: str, record: Any, author: str,
                 repo_root: str | Path) -> Optional[int]:
    """往某次运行的日志里追加一条 `human.edit`。返回 seq，写不进去返回 None。

    运行目录从 run_id 反解，走的是 `RunRepository` 那**唯一一套**"哪儿找运行"的
    逻辑（它两种落盘布局都认：`output/<名>/` 与 `output_<用户>_<时间戳>/`）。
    """
    try:
        from src.orchestration_plane.l2.run_journal import RunJournal
        from src.orchestration_plane.l2.run_repository import RunRepository
    except Exception as exc:                      # pragma: no cover - 导入失败即环境问题
        logger.warning("人工编辑未能写进运行日志", error=str(exc))
        return None

    try:
        # 用**绝对**基准：`RunRepository` 会扫 `<base>/*` 与 `<base>_*` 两种落盘
        # 布局，基准一旦是相对路径就跟着 cwd 走 —— 而人工编辑的调用方（GUI）与
        # 复查方（CLI、另一次运行）未必站在同一个目录下。
        base = Path(repo_root).resolve() / "output"
        root = RunRepository(str(base)).run_dir(run_id)
        if root is None or not Path(root).exists():
            return None
        journal = RunJournal(root, run_id=run_id)
        event = journal.record(
            "human.edit", agent=f"human:{author}", status="edited",
            payload={"file": record.file_path, "reason": record.reason,
                     "content_hash": record.content_hash, "hash": record.hash,
                     "seq": record.seq})
        return event.seq
    except Exception as exc:
        # 日志写不进去不该让人白干一场：链已经记上了，这里只降级。
        logger.warning("人工编辑未能写进运行日志", run_id=run_id, error=str(exc))
        return None


def reconcile(repo_root: str | Path = ".", *, limit: int = 500) -> Dict[str, Any]:
    """对账：**工作区里改过、链里却没有的文件**。

    为什么这是这一块里最要紧的一个动作
        一条只在"你记得记账时才记账"的链，审计上是**不可信的**：读链的人无法区分

            「这段时间没人改」  与  「有人改了但没记」

        两者在链上长得一模一样 —— 都是一片空白。链的价值因此不在"记了的有痕迹"
        （那是记账的本分），而在"**没记的能被发现**"。实测踩过一次同构的坑：测试
        往这条链里写了 16 条垃圾记录，自校验照样通过，谁也不会发现。

    怎么判"改过"
        拿 `git status --porcelain` 当**改动清单**（git 是唯一真相，与铁律一同一
        个道理），再拿内容哈希去链里找 `(文件, 内容哈希)` 是否命中。
        用内容哈希而不是"有没有这个文件的记录"，是因为同一个文件可能被改过多次、
        也可能改回原样 —— 只有哈希能回答"**当前这份内容**被记过账吗"。

    局限（如实写在返回值里，不假装周全）
        · 只在 git 仓库里有效；不在仓库里就没有"改动清单"可比，直接返回 skipped。
        · 新增但未跟踪的文件（`??`）也算"改过" —— 新写的 RTL/YAML 同样需要痕迹。
        · 链里记的是**人**的编辑；agent 改的文件走各次运行自己的链，不在这里对账。
    """
    root = Path(repo_root).resolve()
    changes = _git_changed_files(root, limit=limit)
    if changes is None:
        return {"checked": False, "reason": "不是 git 仓库（或 git 不可用），无法确定改动清单",
                "unrecorded": [], "recorded": [], "total_changed": 0}

    chain = read_human_edits(root)
    known = {(str(r.get("file_path", "")).replace("\\", "/"), str(r.get("content_hash", "")))
             for r in chain["records"]}

    from src.runtime_plane.infrastructure.infrastructure import sha256_file

    unrecorded, recorded = [], []
    for rel in changes:
        digest = sha256_file(root / rel)
        if not digest:                       # 目录、或读不了 —— 不当成"未记账"来冤枉它
            continue
        (recorded if (rel, digest) in known else unrecorded).append(rel)

    return {
        "checked": True,
        "chain_valid": chain["chain_valid"],
        "chain_total": chain["total_changes"],
        "total_changed": len(changes),
        "recorded": sorted(recorded),
        "unrecorded": sorted(unrecorded),
        "ok": not unrecorded and chain["chain_valid"],
    }


#: 对账时**不看**的路径前缀。这些都是"机器自己会长"的东西，不是人工编辑：
#:
#:   · `.signoffai/` —— 跨运行的成长目录（经验库、`rl_policy.json`，**以及本链
#:     自己**）。不排除的话每记一笔账就改动了链文件本身，下一轮 `check` 立刻
#:     报"未记账"，自己追自己；那几个 `.db` 也会每次运行都变。
#:   · `output*/`、`logs/`、`generated/` —— 运行产物。`.gitignore` 已经挡住了，
#:     这里再挡一道：对账的正确性不该依赖 `.gitignore` 有没有写漏。
_EXCLUDED_PREFIXES = (".signoffai/", "output/", "output_", "logs/", "generated/")


def _git_changed_files(root: Path, *, limit: int = 500) -> Optional[List[str]]:
    """`git status --porcelain` → 相对仓库根的改动文件清单。不是 git 仓库返回 None。

    解析 `XY <path>`：状态两列各占一位，第三位起是路径。重命名写的是
    `R  old -> new`，取"新"那一侧 —— 对账要的是**现在盘上那份**。
    未跟踪的**目录**（`?? 某个目录/`）会被后面按哈希过滤掉（目录算不出哈希），
    所以不必在这里展开。
    """
    import subprocess

    try:
        r = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30, cwd=str(root))
    except Exception:
        return None
    if r.returncode != 0:
        return None

    out: List[str] = []
    for line in (r.stdout or "").splitlines():
        if len(line) < 4:
            continue
        path = line[3:].strip()
        if " -> " in path:                   # 重命名：取新名字
            path = path.split(" -> ", 1)[1].strip()
        path = path.strip('"').replace("\\", "/")
        if not path or path.startswith(_EXCLUDED_PREFIXES):
            continue
        out.append(path)
    return out[:limit]


def read_human_edits(repo_root: str | Path = ".") -> Dict[str, Any]:
    """读回项目级人工变更链 + 完整性自校验（只读，给界面/签核用）。"""
    from .file_audit import FileAuditTrail

    chain_path = project_chain_path(repo_root)
    if not chain_path.is_file():
        return {"exists": False, "records": [], "total_changes": 0,
                "final_hash": "", "chain_valid": True, "path": str(chain_path)}
    trail = FileAuditTrail.open(chain_path, repo_root=str(repo_root))
    persisted = FileAuditTrail.verify_persisted(chain_path)
    data = {
        "exists": True,
        "records": [r.__dict__ for r in trail.records],
        "total_changes": len(trail.records),
        "final_hash": trail.prev_hash,
        # 内存自校验 + 回读复核：后者才能发现落盘后被裁剪
        "chain_valid": bool(trail.verify()) and bool(persisted.get("valid")),
        "issues": persisted.get("issues", []),
        "path": str(chain_path),
    }
    return data
