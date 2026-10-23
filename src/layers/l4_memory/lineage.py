"""LineageStore —— **血缘**：RTL 版本 / run 基准 / 用例与 bug 挂在哪个 RTL 版本上。

## 为什么需要它（四件事缺的是同一个东西：一级实体）

仓库里已经有一整套证据链：`sha256_file`、`FileAuditTrail`（哈希链）、`manifest`
（字段级哈希）、`compare_runs(baseline, current)`。它们回答的是"**这一次**的产物对不对"。
缺的是**跨 run 的那个实体**：

    run     跟谁比？           → 没有"首次 run = 锚点"，diff 全靠人手选目录
    RTL     这一轮跑的是哪版？ → 只有不透明字节哈希（`manifest.rtl_hashes` 还截成 16 位）
    bug     在哪个版本发现/修好？→ bug 记录里连 RTL 路径都没有
    用例    属于哪个模块哪版？ → `testcase_registry` 只在 name 里**文本**嵌模块名

所以这里补四张表，构成一条可查的血缘链：

    RTL 目录内容哈希 ──► rtl_versions(module, hash) → vN     （内容哈希自动版本）
    run ──────────────► run_rtl_bindings(run_id → vN)         （这一轮跑的是哪版）
    模块首次 run ──────► run_baselines(module → 首次 run)      （基准锚点）
    bug ──────────────► bug_rtl_links(bug_id → found/fixed vN)（bug 关联 RTL 迭代）

## 版本号怎么来：**内容哈希**

用户选定的口径是"内容哈希自动版本"——机器算，不依赖 git（`--rtl <dir>` 把一堆
`.sv` 拷进来时没有 commit 可谈）。同一个模块下，**首次见到**某个内容哈希就分配
`version_no = MAX+1`；同一个哈希再来是幂等的（同一版跑一百次还是 v1）。
哈希是 SHA-256 全 64 位 —— **不能沿用 `archive_rtl` / `manifest.rtl_hashes` 那种
`[:16]` 截断**，那是给人看的短标识，做身份会撞。

## 与 `ic_verification.db` 的分工

bug 本体（描述/严重度/状态）仍在 SQLAlchemy 那边（`VerificationBug`）；这里只放
**链接**（`bug_id ↔ 版本`），用 `bug_id` 作 join 键。跨两个库是可接受的：换 Alembic
迁移的代价远大于一次 join；而且血缘是**可加的**元数据，随时可重建（重扫 manifest 即可）。

同步 sqlite + `threading.Lock`，与 `ExcludeRegistry` 同款：调用点在 run 执行/结束/
记 bug 这些同步上下文里，不该被 async 传染。
"""
from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

#: RTL 源码后缀 —— 与 `execution.py` 把 `--rtl` 拷进 run 时收的范围一致。
#: 只收 `*.sv` 会漏掉 `.v/.svh/.vh`：漏了就等于"改了这些文件版本号不动"，
#: 而那正是要防的事（"这一轮和上一轮是同一版吗"）。
RTL_SUFFIXES = (".sv", ".v", ".svh", ".vh")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rtl_versions (
    module            TEXT NOT NULL,
    content_hash      TEXT NOT NULL,
    version_no        INTEGER NOT NULL,
    first_seen_run_id TEXT NOT NULL DEFAULT '',
    created_at        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (module, content_hash),
    UNIQUE (module, version_no)
);
CREATE TABLE IF NOT EXISTS run_rtl_bindings (
    run_id       TEXT PRIMARY KEY,
    module       TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version_no   INTEGER NOT NULL,
    created_at   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS run_baselines (
    module             TEXT PRIMARY KEY,
    baseline_run_id    TEXT NOT NULL,
    baseline_version_no INTEGER NOT NULL,
    created_at         TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS bug_rtl_links (
    bug_id           TEXT NOT NULL,
    module           TEXT NOT NULL,
    found_version_no INTEGER,
    fixed_version_no INTEGER,
    found_run_id     TEXT NOT NULL DEFAULT '',
    fixed_run_id     TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (bug_id, module)
);
-- 版本号**单调发放**的计数器（每个模块一行）。
--
-- 为什么需要它：原来号是 `MAX(version_no) + 1` 算的 —— 一旦删过行（`prune`），
-- 下一次分配就会**复用**已删掉的号，于是"v3"在不同时间指**不同内容**，
-- 而"同一个内容跑一百轮还是 v1"正是这个功能存在的理由。用一个只增不减的计数器
-- 之后，删旧版本不再影响后续编号。
CREATE TABLE IF NOT EXISTS rtl_module_seq (
    module  TEXT PRIMARY KEY,
    next_no INTEGER NOT NULL
);
"""


def compute_rtl_dir_hash(rtl_dir) -> str:
    """RTL 目录 → **内容哈希**（SHA-256，全 64 位）；空/缺目录返回空串。

    口径要说清（换个口径就换个身份，老记录全对不上）：

      · 收 `RTL_SUFFIXES` 里的**全部**源码，不只是 `*.sv`
      · 按**文件名排序**后逐文件 `sha256_file`（复用 L1 的分块实现，几十 MB 的
        RTL 也不会整份读进内存）
      · 聚合 = `sha256(每条 "相对名\\0哈希\\n" 拼接)` —— 用 `\\0` 分隔是为了
        防"名字改一个字符、内容不变"撞出同一个聚合（`a.sv`+`bc.sv` vs `ab.sv`+`c.sv`）

    **空目录返回空串**，不是某个哨兵哈希：调用方据此**整条跳过**血缘写入 ——
    "没有 RTL" 与 "RTL 是空的" 在这件事上不该长得一样（否则会写出一个
    假版本 v1，而它对应着一份没有内容的目录）。
    """
    d = Path(rtl_dir)
    if not d.is_dir():
        return ""
    from src.layers.l1_infrastructure.infrastructure import sha256_file

    files = sorted(p for p in d.rglob("*")
                   if p.is_file() and p.suffix.lower() in RTL_SUFFIXES)
    if not files:
        return ""
    agg = hashlib.sha256()
    for p in files:
        rel = p.relative_to(d).as_posix()
        agg.update(rel.encode("utf-8"))
        agg.update(b"\0")
        agg.update(sha256_file(p).encode("ascii"))
        agg.update(b"\n")
    return agg.hexdigest()


class LineageStore:
    """血缘状态库（同步 sqlite，跨 run 持久）。

        store = LineageStore()
        v = store.ensure_rtl_version("npu_sched", h, run_id)   # → 1
        store.bind_run(run_id, "npu_sched", h, v)
        store.ensure_baseline("npu_sched", run_id, v)          # 首次即锚
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else Path(".signoffai") / "lineage.db"
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.executescript(_SCHEMA)
            # **老库补种计数器**：`rtl_module_seq` 是后加的，已有库里的模块
            # 一行都没有 —— 从当前 `MAX(version_no)+1` 补上，否则那些模块的
            # 下一个版本号会从 1 重新开始（与已存在的版本撞号）。
            # `INSERT OR IGNORE` 让这件事幂等：已经种过的模块不动。
            self._conn.execute(
                "INSERT OR IGNORE INTO rtl_module_seq (module, next_no) "
                "SELECT module, MAX(version_no) + 1 FROM rtl_versions GROUP BY module")
            self._conn.commit()
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    # ═══════════════════════════════════════════════════════════
    # RTL 版本
    # ═══════════════════════════════════════════════════════════

    def ensure_rtl_version(self, module: str, content_hash: str,
                           run_id: str = "") -> Optional[int]:
        """`(module, content_hash)` → `version_no`（**首次见到就分配下一个号**）。

        同哈希**幂等**：同一个内容跑一百轮，版本号都是那个 v1 —— 这正是"版本"
        该有的样子（跑的次数不是版本）。分配与查询在同一把锁 + 同一个事务里，
        并发两个 run 同时首见同一哈希也只会得到一个版本号。

        **号从 `rtl_module_seq` 单调发放，不从 `MAX(version_no)+1` 算** ——
        后者在 `prune` 删过行之后会复用已删的号（"v3"换个内容还是 v3），
        而版本号的全部价值就是"它指向唯一一个内容"。
        """
        module = (module or "").strip()
        content_hash = (content_hash or "").strip()
        if not module or not content_hash:
            return None
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT version_no FROM rtl_versions WHERE module=? AND content_hash=?",
                (module, content_hash)).fetchone()
            if row:
                return int(row[0])
            nxt = conn.execute(
                "SELECT next_no FROM rtl_module_seq WHERE module=?", (module,)).fetchone()
            if nxt is None:
                # 本模块第一次出现（新库，或老库里从没有过这个模块）
                nxt_no = 1
                conn.execute("INSERT INTO rtl_module_seq (module, next_no) VALUES (?, ?)",
                             (module, nxt_no + 1))
            else:
                nxt_no = int(nxt[0])
                conn.execute("UPDATE rtl_module_seq SET next_no=? WHERE module=?",
                             (nxt_no + 1, module))
            conn.execute(
                "INSERT INTO rtl_versions (module, content_hash, version_no, "
                "first_seen_run_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (module, content_hash, nxt_no, run_id or "", self._now()))
            conn.commit()
            return int(nxt_no)

    def version_name(self, module: str, version_no: Optional[int]) -> str:
        """`vN` + 12 位哈希前缀 —— 给人看的名字。取不到就 `""`（不编一个）。"""
        if version_no is None:
            return ""
        row = self._connect().execute(
            "SELECT content_hash FROM rtl_versions WHERE module=? AND version_no=?",
            (module, int(version_no))).fetchone()
        return f"v{int(version_no)}" + (f" ({row[0][:12]})" if row else "")

    def list_versions(self, module: str = "") -> List[Dict[str, Any]]:
        """版本表（`module` 空则全部），按模块 + 版本号排序。"""
        conn = self._connect()
        if module:
            rows = conn.execute(
                "SELECT module, content_hash, version_no, first_seen_run_id, created_at "
                "FROM rtl_versions WHERE module=? ORDER BY version_no", (module,)).fetchall()
        else:
            rows = conn.execute(
                "SELECT module, content_hash, version_no, first_seen_run_id, created_at "
                "FROM rtl_versions ORDER BY module, version_no").fetchall()
        return [{"module": r[0], "content_hash": r[1], "version_no": r[2],
                 "hash": r[1][:12], "name": f"v{r[2]}",
                 "first_seen_run_id": r[3], "created_at": r[4]} for r in rows]

    def prune(self, keep_last: int = 50, module: str = "",
              dry_run: bool = False) -> Dict[str, Any]:
        """删**孤儿**版本行：既没有任何 run 引用、又不是基准/缺陷锚点、且已超出保留窗口。

        ## 判据（**三条全中才删**，任一不中一律留）

          1. `run_rtl_bindings` 里没有它 —— 有 run 引用 = 它是某次运行的证据
          2. 不是 `run_baselines` 的锚（"相对最初那版偏了多少"要它才答得了）
          3. 不是任何 `bug_rtl_links` 的 `found/fixed_version`（修没修靠它）
          4. 且它是该模块**最老的**那批里、序号小于 `keep_last` 留剩的窗口

        保守到几乎删不掉东西是**故意的**：这张库是签核回溯的锚，删错一条
        （比如某个基准）会让"这版和最初那版差多少"永久答不出来。真正会涨的是
        `run_rtl_bindings`（一行一次 run），而那是**证据**，不在这里删。

        ## 为什么删除是安全的（版本号不会被复用）

        `ensure_rtl_version` 的号来自 `rtl_module_seq` 那张只增不减的计数器，
        不再从 `MAX(version_no)+1` 算 —— 所以删掉 v1/v2 之后，下一个新内容
        仍然拿 v5，不会有人把 v1 拿去指另一个内容。

        `dry_run=True` 只算不删（CLI 默认先给人看一眼再删）。
        """
        conn = self._connect()
        window = max(0, int(keep_last))
        with self._lock:
            rows = conn.execute(
                "SELECT module, content_hash, version_no FROM rtl_versions"
                + (" WHERE module=?" if module else "")
                + " ORDER BY module, version_no", ((module,) if module else ())).fetchall()
            protected_versions = {
                (r[0], r[1]) for r in conn.execute(
                    "SELECT module, version_no FROM run_rtl_bindings").fetchall()}
            protected_versions |= {
                (r[0], r[1]) for r in conn.execute(
                    "SELECT module, baseline_version_no FROM run_baselines").fetchall()}
            for r in conn.execute(
                    "SELECT module, found_version_no, fixed_version_no FROM bug_rtl_links"):
                if r[1] is not None:
                    protected_versions.add((r[0], int(r[1])))
                if r[2] is not None:
                    protected_versions.add((r[0], int(r[2])))

            keep: Dict[str, List[int]] = {}
            for mod, _h, vno in rows:
                keep.setdefault(mod, []).append(int(vno))

            victims: List[Dict[str, Any]] = []
            for mod, content_hash, vno in rows:
                vno = int(vno)
                window_start = keep[mod][-window:] if window else []
                if vno in window_start:
                    continue                                   # 保留窗口内
                if (mod, vno) in protected_versions:
                    continue                                   # 有引用
                victims.append({"module": mod, "version_no": vno,
                                "content_hash": content_hash})

            if victims and not dry_run:
                conn.executemany(
                    "DELETE FROM rtl_versions WHERE module=? AND content_hash=?",
                    [(v["module"], v["content_hash"]) for v in victims])
                conn.commit()
            return {"pruned": len(victims), "dry_run": bool(dry_run),
                    "keep_last": window,
                    "versions": [f"{v['module']} v{v['version_no']}" for v in victims]}

    # ═══════════════════════════════════════════════════════════
    # run ↔ 版本
    # ═══════════════════════════════════════════════════════════

    def bind_run(self, run_id: str, module: str, content_hash: str,
                 version_no: int) -> None:
        """记下"**这一轮跑的是哪一版**"。按 `run_id` upsert（`n_finalize` 可能重入）。"""
        if not (run_id and module) or version_no is None:
            return
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO run_rtl_bindings (run_id, module, content_hash, "
                "version_no, created_at) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET module=excluded.module, "
                "content_hash=excluded.content_hash, version_no=excluded.version_no",
                (run_id, module, content_hash or "", int(version_no), self._now()))
            conn.commit()

    def version_by_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        row = self._connect().execute(
            "SELECT module, content_hash, version_no FROM run_rtl_bindings WHERE run_id=?",
            (run_id,)).fetchone()
        return None if not row else {"module": row[0], "content_hash": row[1],
                                     "version_no": row[2], "name": f"v{row[2]}"}

    def runs_of_version(self, module: str, version_no: int) -> List[str]:
        """跑过这一版的所有 run（`run_id` 升序）—— "这版被谁验过"。"""
        rows = self._connect().execute(
            "SELECT run_id FROM run_rtl_bindings WHERE module=? AND version_no=? "
            "ORDER BY run_id", (module, int(version_no))).fetchall()
        return [r[0] for r in rows]

    # ═══════════════════════════════════════════════════════════
    # run 基准（**每个模块的首次 run**）
    # ═══════════════════════════════════════════════════════════

    def ensure_baseline(self, module: str, run_id: str,
                        version_no: int) -> bool:
        """首次见到这个模块就把它锚成基准；**已经有锚就不动**。

        返回"这次是不是新立的"。用户选定的口径是**首次 run 当锚点**（不是"上一轮"
        也不是"最近的 golden"）—— 因为 "相对最初那版偏了多少" 是复现和签核都要
        回答的问题，而它是单调的；"上一轮" 会随跑的次数漂。
        """
        if not (module and run_id) or version_no is None:
            return False
        conn = self._connect()
        with self._lock:
            cur = conn.execute(
                "INSERT OR IGNORE INTO run_baselines (module, baseline_run_id, "
                "baseline_version_no, created_at) VALUES (?, ?, ?, ?)",
                (module, run_id, int(version_no), self._now()))
            conn.commit()
            return bool(cur.rowcount)

    def get_baseline(self, module: str) -> Optional[Dict[str, Any]]:
        row = self._connect().execute(
            "SELECT baseline_run_id, baseline_version_no, created_at "
            "FROM run_baselines WHERE module=?", (module,)).fetchone()
        return None if not row else {"module": module, "run_id": row[0],
                                     "version_no": row[1], "name": f"v{row[1]}",
                                     "created_at": row[2]}

    # ═══════════════════════════════════════════════════════════
    # bug ↔ 版本
    # ═══════════════════════════════════════════════════════════

    def link_bug(self, bug_id: str, module: str,
                 found_version_no: Optional[int] = None,
                 fixed_version_no: Optional[int] = None,
                 found_run_id: str = "", fixed_run_id: str = "") -> None:
        """把一个 bug 挂到 RTL 版本上（**只记录，不触发流程**）。

        `found_*` = 在哪个版本发现的；`fixed_*` = 在哪个版本修好的。同一个 bug 在
        同一模块下**只有一行**，后面的调用补字段（先记 found、修完再补 fixed）——
        `COALESCE` 让"只传一个"的调用不会把另一个冲掉。
        """
        if not (bug_id and module):
            return
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO bug_rtl_links (bug_id, module, found_version_no, "
                "fixed_version_no, found_run_id, fixed_run_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(bug_id, module) DO UPDATE SET "
                "found_version_no=COALESCE(excluded.found_version_no, found_version_no), "
                "fixed_version_no=COALESCE(excluded.fixed_version_no, fixed_version_no), "
                "found_run_id=CASE WHEN excluded.found_run_id<>'' "
                "  THEN excluded.found_run_id ELSE found_run_id END, "
                "fixed_run_id=CASE WHEN excluded.fixed_run_id<>'' "
                "  THEN excluded.fixed_run_id ELSE fixed_run_id END",
                (bug_id, module,
                 None if found_version_no is None else int(found_version_no),
                 None if fixed_version_no is None else int(fixed_version_no),
                 found_run_id or "", fixed_run_id or "", self._now()))
            conn.commit()

    def bugs_of_version(self, module: str = "",
                        version_no: Optional[int] = None) -> List[Dict[str, Any]]:
        """按模块/版本查 bug（两个都给就取"在这一版发现**或**在这一版修好"的）。"""
        conn = self._connect()
        sql = ("SELECT bug_id, module, found_version_no, fixed_version_no, "
               "found_run_id, fixed_run_id, created_at FROM bug_rtl_links")
        args: List[Any] = []
        where = []
        if module:
            where.append("module=?")
            args.append(module)
        if version_no is not None:
            where.append("(found_version_no=? OR fixed_version_no=?)")
            args.extend([int(version_no), int(version_no)])
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at, bug_id"
        return [{"bug_id": r[0], "module": r[1], "found_version_no": r[2],
                 "fixed_version_no": r[3], "found_run_id": r[4],
                 "fixed_run_id": r[5], "created_at": r[6]}
                for r in conn.execute(sql, args).fetchall()]


def ensure_run_rtl_version(output_dir, module: str = "",
                           run_id: str = "") -> Dict[str, Any]:
    """**「这一轮跑的是 RTL 的哪一版」—— 一个入口，三个阶段共用。**

    front（注册用例时）、debug（记 bug 时）、finalize（收尾时）都要知道这个版本。
    各自算一遍就会漂（同一个 run 三个地方三个版本号，而且都不报错），所以做成
    一个函数：算内容哈希 → `ensure_rtl_version`（幂等）→ `bind_run` → 返回。

    返回 `{module, version_no, name, content_hash}`；**拿不到就返回 `{}`**
    （没有 RTL 目录 / 目录里没有源码）—— 不是"版本是空的"。

    `module` 缺省时读 `<run>/spec.json` 的 `design_name`：那是本 run 的规格身份，
    比让调用方各传一个字符串可靠。都没有就落 `"dut"` 并**说出来**（编一个模块名
    会把血缘挂到错的地方，而它和挂对了长得一模一样）。
    """
    import json as _json

    d = Path(output_dir)
    content_hash = compute_rtl_dir_hash(d / "rtl")
    if not content_hash:
        return {}
    mod = (module or "").strip()
    if not mod:
        try:
            spec = _json.loads((d / "spec.json").read_text(encoding="utf-8",
                                                           errors="replace"))
            mod = str((spec or {}).get("design_name") or "").strip()
        except Exception:                                  # noqa: BLE001
            mod = ""
    if not mod:
        mod = "dut"
    store = LineageStore()
    try:
        version_no = store.ensure_rtl_version(mod, content_hash, run_id)
        store.bind_run(run_id or d.name, mod, content_hash, version_no)
    finally:
        store.close()                                      # Windows 文件锁
    return {"module": mod, "version_no": version_no, "name": f"v{version_no}",
            "content_hash": content_hash}


def run_rtl_version_no(output_dir, module: str = "") -> Optional[int]:
    """这一轮 RTL 的版本号（没有 RTL 就 `None`）—— **调用点只管要这个数**。

    单列一个函数是为了让"注册用例时带上版本"这种调用点只写一行。**每一处都得
    走它**：这个仓库反复吃过"同一件事有多个落点，改了三个漏一个"的亏 ——
    本功能刚落地时就漏了图上的两个 `register_from_spec` 落点（front agent 与
    n_design 是两条路径），于是同一个模块的用例一半带版本、一半不带，
    而**两边都不报错**。有一条源级守卫测盯着这件事。
    """
    return (ensure_run_rtl_version(output_dir, module=module,
                                   run_id=Path(output_dir).name) or {}).get("version_no")


def get_lineage_store() -> LineageStore:
    """进程内默认血缘库（`.signoffai/lineage.db`）—— 与其它领域库同款单例。"""
    global _DEFAULT
    try:
        return _DEFAULT
    except NameError:
        pass
    _DEFAULT = LineageStore()
    return _DEFAULT
