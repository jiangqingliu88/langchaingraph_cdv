"""
ModelRegistry —— **参考模型库**（sqlite）：TLM 1.0 事务级组件的注册 / 版本 / 复用。

## 为什么是 SQL，不是 `model_library/<name>/v1/` 那种文件目录

老形状是把参考模型当**文件**存：`model_library/apb_slave/v1/{manifest.json, model.sv}`
+ 一份 `INDEX.yaml`。库一大就三件事全都靠不住：

  · **查不动** —— "哪个模型能接 `apb_master_seq_item`" 得把目录全打开才知道；
  · **版本靠文件夹名** —— `v1` / `v2` 是字符串，没有"当前该用哪个"的单一答案；
  · **验证状态写在 manifest 里** —— 那是第二个真相源，和文件本身各说各话。

用例库（`testcase_registry.py`）早就走对了：库是 SQL，声明（`regression.yaml`）
由 `_generate_regression_yaml` **从库里读出来再写**。模型这边照同一条走 ——
**SQL 是库（有哪些、验证过没有、哪一版），yaml 是这一轮的装配单**。

## 为什么必须是 TLM 1.0 事务级

老库里的 `*_golden.sv` 长这样：

    module apb_slave_golden #(NREGS, ADDR_W, DATA_W) (
        input logic clk, rst_n, paddr, pwdata, pwrite, psel, penable,
        output logic prdata                       // 引脚级
    );
        always_ff @(posedge clk or negedge rst_n) ...   // 带时钟的时序逻辑

那是**信号级 RTL**，不是参考模型。参考模型要的是"给一条事务，算出它应该得到什么"：

    uvm_component + uvm_analysis_imp (#(...)) + uvm_analysis_port (#(...))
    跑 *_seq_item，没有 clk

这正是 `tool_uvm/examples/apb/apb_util_comp.yaml` 里 `util_components` 已经声明的形状
（`analysis_exports` / `analysis_ports` → `util_comp.sv.j2` 渲染出
`uvm_analysis_imp_<name>` + `write_<name>` + `process_<name>`）。**形状不用造**，
缺的只是 `process_<port>` 里那份事务级语义 —— 本库存的就是它。

用法:
    from src.knowledge_plane.model_registry import ModelRegistry
    reg = ModelRegistry("database/model_registry.db")
    reg.register("apb_slave", trans_in="apb_master_seq_item",
                 trans_out="apb_master_seq_item", protocol="apb",
                 semantics="写 regs[paddr]=pwdata；读 prdata=regs[paddr]（越界回 0）",
                 body="...process_ 的实现...")
    reg.set_status("apb_slave", "verified", evidence={"case": "test_apb_uart_case_basic"})
    reg.to_util_component("apb_slave")      # → 直接可写进 env.yaml 的那一节
"""
from __future__ import annotations

from .sqlite_utils import connect

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── 模型状态机 ──
# 与用例库同口径：草稿 → 生成 → 已验证。**`verified` 是唯一能被生成器选中的状态**
#（没验证过的模型接进 env，就是拿没根据的东西当 expected）。
STATUS_DRAFT = "draft"
STATUS_GENERATED = "generated"
STATUS_VERIFIED = "verified"
STATUS_DEPRECATED = "deprecated"

#: 只有这些状态才会被 `select()` 选中。
SELECTABLE = (STATUS_VERIFIED,)

#: 组件种类。目前只有 TLM 1.0 事务级这一种 —— 留成字段是为了**看见**这件事，
#: 而不是靠约定；哪天要加 TLM 2.0 / C-model，这里是一条显式记录。
KIND_TLM10 = "tlm10_component"
KINDS = (KIND_TLM10,)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_registry (
    name         TEXT NOT NULL,
    version      INTEGER NOT NULL DEFAULT 1,
    kind         TEXT NOT NULL DEFAULT 'tlm10_component',
    protocol     TEXT NOT NULL DEFAULT '',
    -- TLM 1.0 的两个口：进什么事务、出什么事务。生成器就靠这两列选模型。
    trans_in     TEXT NOT NULL DEFAULT '',
    trans_out    TEXT NOT NULL DEFAULT '',
    -- `util_components` 那两节，JSON 存：[{name,type}, ...]
    exports      TEXT NOT NULL DEFAULT '[]',
    ports        TEXT NOT NULL DEFAULT '[]',
    semantics    TEXT NOT NULL DEFAULT '',
    -- process_<port> 的实现（事务级，无 clk）
    body         TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL DEFAULT 'draft',
    evidence     TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL DEFAULT '',
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (name, version)
);
CREATE INDEX IF NOT EXISTS idx_model_trans
    ON model_registry (trans_in, trans_out, status);
"""


class ModelRegistry:
    """参考模型库（同步 sqlite，跨 run 持久）。

    **版本是行不是文件夹**：`(name, version)` 主键，`latest(name)` 取最大版本。
    老形状的 `v1/` 目录名换成了整数列 —— 排序、比较、回滚都能用 SQL 做。
    """

    def __init__(self, db_path: Optional[str | Path] = None):
        from config.paths import MODEL_DB

        self.db_path = Path(db_path) if db_path else MODEL_DB
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = connect(self.db_path)
            self._conn.executescript(_SCHEMA)
        return self._conn

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # ── 写 ──────────────────────────────────────────────────────

    def register(self, name: str, *, kind: str = KIND_TLM10,
                 protocol: str = "", trans_in: str = "", trans_out: str = "",
                 exports: Optional[List[Dict]] = None,
                 ports: Optional[List[Dict]] = None,
                 semantics: str = "", body: str = "",
                 version: Optional[int] = None,
                 status: str = STATUS_DRAFT) -> Dict[str, Any]:
        """登记一个模型版本。不给 `version` 就自动接在最新版后面。

        **不覆盖同名旧版本** —— 老形状的约束"黄金模型不可变，新增行为只能升版本"
        在这里靠 `(name, version)` 主键落实：同一个 `name` 想改语义，就是新版本。
        """
        if kind not in KINDS:
            raise ValueError(f"kind 必须是 {KINDS} 之一，收到 {kind!r}")
        if not trans_in or not trans_out:
            raise ValueError("TLM 1.0 组件必须写清 trans_in / trans_out"
                             "（生成器靠这两列选模型）")
        with self._lock:
            conn = self._connect()
            if version is None:
                row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM model_registry WHERE name=?",
                    (name,)).fetchone()
                version = int(row[0]) + 1
            now = datetime.now().isoformat(timespec="seconds")
            conn.execute(
                "INSERT INTO model_registry (name, version, kind, protocol, trans_in,"
                " trans_out, exports, ports, semantics, body, status, evidence,"
                " created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,'{}',?,?)",
                (name, version, kind, protocol, trans_in, trans_out,
                 json.dumps(exports or [], ensure_ascii=False),
                 json.dumps(ports or [], ensure_ascii=False),
                 semantics, body, status, now, now))
            conn.commit()
        return self.get(name, version) or {}

    def set_status(self, name: str, status: str, *,
                   evidence: Optional[Dict] = None, version: Optional[int] = None) -> int:
        """改状态（`verified` 要靠 `evidence` 说清"凭什么"）。返回影响行数。"""
        if status not in (STATUS_DRAFT, STATUS_GENERATED, STATUS_VERIFIED,
                          STATUS_DEPRECATED):
            raise ValueError(f"未知状态 {status!r}")
        ver = version if version is not None else self.latest_version(name)
        if ver is None:
            return 0
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "UPDATE model_registry SET status=?, evidence=?, updated_at=?"
                " WHERE name=? AND version=?",
                (status, json.dumps(evidence or {}, ensure_ascii=False),
                 datetime.now().isoformat(timespec="seconds"), name, ver))
            conn.commit()
            return cur.rowcount

    # ── 读 ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        for k in ("exports", "ports", "evidence"):
            try:
                d[k] = json.loads(d.get(k) or ("[]" if k != "evidence" else "{}"))
            except Exception:                          # noqa: BLE001 坏 JSON 不当场炸
                d[k] = [] if k != "evidence" else {}
        return d

    def get(self, name: str, version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        ver = version if version is not None else self.latest_version(name)
        if ver is None:
            return None
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM model_registry WHERE name=? AND version=?",
                           (name, ver)).fetchone()
        return self._row_to_dict(row) if row else None

    def latest_version(self, name: str) -> Optional[int]:
        conn = self._connect()
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM model_registry WHERE name=?",
            (name,)).fetchone()
        return int(row[0]) or None

    def all(self, include_deprecated: bool = False) -> List[Dict[str, Any]]:
        """每个 `name` 的**最新版**清单 —— 替代老的 `INDEX.yaml`。"""
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.* FROM model_registry r"
            " JOIN (SELECT name, MAX(version) v FROM model_registry GROUP BY name) m"
            "   ON r.name = m.name AND r.version = m.v"
            " ORDER BY r.name").fetchall()
        out = [self._row_to_dict(r) for r in rows]
        if not include_deprecated:
            out = [m for m in out if m["status"] != STATUS_DEPRECATED]
        return out

    def select(self, trans_in: str = "", trans_out: str = "",
               protocol: str = "") -> Optional[Dict[str, Any]]:
        """给生成器选模型：**只挑 `verified`**，条件按"越具体越优先"排序。

        为什么只挑 `verified`：`_ref_mirror_gate` 当初挡假失败的那条教训 ——
        拿没根据的东西当 expected，等于自己造一批假失败。`draft`/`generated`
        不是不能用，是**不该被自动选中**。
        """
        where, args = ["status IN (%s)" % ",".join("?" * len(SELECTABLE))], list(SELECTABLE)
        if trans_in:
            where.append("trans_in = ?")
            args.append(trans_in)
        if trans_out:
            where.append("trans_out = ?")
            args.append(trans_out)
        if protocol:
            where.append("(protocol = ? OR protocol = '')")
            args.append(protocol)
        conn = self._connect()
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT r.* FROM model_registry r"
            " JOIN (SELECT name, MAX(version) v FROM model_registry GROUP BY name) m"
            "   ON r.name = m.name AND r.version = m.v"
            f" WHERE {' AND '.join(where)}"
            " ORDER BY (protocol <> '') DESC, r.name",
            args).fetchall()
        return self._row_to_dict(rows[0]) if rows else None

    # ── 桥：库 → 这一轮的装配单 ────────────────────────────────

    def to_util_component(self, name: str,
                          version: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """一条记录 → `env.yaml` 里 `util_components:` 的一节。

        这就是"**SQL 是库，yaml 是装配单**"的接缝：生成器从库里读出选中那版，
        写成 yaml，再由 `util_comp.sv.j2` 渲染成 TLM 1.0 组件。缺了这层，
        库里存的东西就永远只是个文档。
        """
        m = self.get(name, version)
        if not m:
            return None
        return {
            "name": m["name"],
            "type": m["kind"],                    # tlm10_component
            "description": m["semantics"],
            "analysis_exports": m["exports"] or [
                {"name": "in_export", "type": m["trans_in"]}],
            "analysis_ports": m["ports"] or [
                {"name": "out_port", "type": m["trans_out"]}],
            # 事务级实现，渲染进 `process_<port>`；空则模板落到 TODO（如实暴露）
            "body": m["body"],
            "source_version": f"{m['name']}/v{m['version']}",
        }
