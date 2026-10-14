"""
TestCaseRegistry —— 用例状态库（sqlite）：生命周期管理 + 优先级规划 + 有效性评分。

验证规划分层模型（L0 目标 → L1 Feature → L2 场景 → L3 用例）的"用例层"落地：
  用例有状态（planned → generated → running → passed/failed → deprecated），
  按规划目标（功能/协议/性能/鲁棒性）动态决定优先做哪个用例，
  每轮评分、淘汰低效用例。

用法:
    from src.layers.l4_memory.testcase_registry import TestcaseRegistry
    reg = TestcaseRegistry(".signoffai/testcase_registry.db")
    reg.register("test_axi_rd_burst_len_16", purpose="functional", scenario="burst_read",
                 priority="P0", coverage_bin="rd_burst_len[16]")
    reg.update_status("test_axi_rd_burst_len_16", "passed", result={"sim_time": 80, "new_coverage": 3})
    order = reg.get_priority_order(stage=2, limit=10)   # 按规划目标排序
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 用例状态机
STATUS_PLANNED = "planned"
STATUS_GENERATED = "generated"
STATUS_RUNNING = "running"
STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_DEPRECATED = "deprecated"

# 规划目的（对应 L0 验证目标）
PURPOSES = ("functional", "protocol", "performance", "corner")

# 各阶段（迭代轮次）的 purpose 权重：前期多功能，后期多边界
STAGE_PURPOSE_WEIGHTS = [
    # stage 0（早期）：功能正确性优先
    {"functional": 0.55, "protocol": 0.20, "performance": 0.15, "corner": 0.10},
    # stage 1（中期）：协议兼容性上升
    {"functional": 0.40, "protocol": 0.30, "performance": 0.20, "corner": 0.10},
    # stage 2（后期）：边界/鲁棒性 + 性能
    {"functional": 0.25, "protocol": 0.25, "performance": 0.25, "corner": 0.25},
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS testcase_registry (
    name             TEXT PRIMARY KEY,
    purpose          TEXT NOT NULL DEFAULT 'functional',
    scenario         TEXT NOT NULL DEFAULT '',
    priority         TEXT NOT NULL DEFAULT 'P1',
    status           TEXT NOT NULL DEFAULT 'planned',
    constraints      TEXT NOT NULL DEFAULT '[]',
    coverage_bin     TEXT NOT NULL DEFAULT '',
    sim_time         REAL NOT NULL DEFAULT 0,
    fail_rate        REAL NOT NULL DEFAULT 0,
    new_coverage     REAL NOT NULL DEFAULT 0,
    unique_coverage  INTEGER NOT NULL DEFAULT 0,
    effectiveness    REAL NOT NULL DEFAULT 0,
    run_count        INTEGER NOT NULL DEFAULT 0,
    last_run         TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT '',
    updated_at       TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS portfolio (
    purpose TEXT PRIMARY KEY,
    weight  REAL NOT NULL DEFAULT 0.25,
    min_w   REAL NOT NULL DEFAULT 0.05,
    max_w   REAL NOT NULL DEFAULT 0.70
);
"""

# 默认 portfolio 权重（覆盖范围：min/max）
DEFAULT_PORTFOLIO = {
    "functional":  {"weight": 0.55, "min_w": 0.30, "max_w": 0.70},
    "protocol":    {"weight": 0.20, "min_w": 0.10, "max_w": 0.30},
    "performance": {"weight": 0.15, "min_w": 0.05, "max_w": 0.25},
    "corner":      {"weight": 0.10, "min_w": 0.05, "max_w": 0.20},
}


class TestcaseRegistry:
    """用例状态库（同步 sqlite，跨 run 持久）。"""

    def __init__(self, db_path: Optional[str | Path] = None):
        self.db_path = Path(db_path) if db_path else Path(".signoffai") / "testcase_registry.db"
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.executescript(_SCHEMA)
            self._migrate_columns(self._conn)
            # 初始化 portfolio 默认权重（幂等）
            for purpose, cfg in DEFAULT_PORTFOLIO.items():
                self._conn.execute(
                    "INSERT OR IGNORE INTO portfolio (purpose, weight, min_w, max_w) "
                    "VALUES (?, ?, ?, ?)",
                    (purpose, cfg["weight"], cfg["min_w"], cfg["max_w"]))
            self._conn.commit()
        return self._conn

    #: 后加的列：`(列名, 列定义)`。**只能加，不能改语义** —— 老库是直接把
    #: `CREATE TABLE IF NOT EXISTS` 跳过去的，不 ALTER 的话这两列永远不存在，
    #: 而写入端会报 "no such column"（或者更糟：静默丢字段）。
    _ADDED_COLUMNS = (
        #: 用例属于哪个模块 —— 原来只把模块名**文本**拼进 `name`，
        #: 于是"这个用例是哪个设计的"只能靠解析字符串，没法按模块查/删/对账。
        ("module", "TEXT NOT NULL DEFAULT ''"),
        #: 注册时对应的 **RTL 版本号**（`.signoffai/lineage.db` 的 `version_no`）。
        #: 用例是有版本的：RTL 换了版，之前那批用例是在哪版上定的就没法回答了。
        #: NULL = 不知道（老记录、或这一轮没有 RTL）—— 不编一个 0 出来。
        ("rtl_version_no", "INTEGER"),
    )

    @classmethod
    def _migrate_columns(cls, conn: sqlite3.Connection) -> None:
        """给**既有的**库补新列（幂等，`PRAGMA table_info` 守卫）。

        为什么不能只改 `_SCHEMA` 里的 `CREATE TABLE`：那份 DDL 是
        `CREATE TABLE IF NOT EXISTS` —— 老库已经存在，整条语句被跳过，
        新列**永远长不出来**。而 `.signoffai/testcase_registry.db` 是跨 run 累积的，
        现场一定有老库。
        """
        have = {r[1] for r in conn.execute("PRAGMA table_info(testcase_registry)")}
        for col, decl in cls._ADDED_COLUMNS:
            if col not in have:
                conn.execute(f"ALTER TABLE testcase_registry ADD COLUMN {col} {decl}")

    def close(self):
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ═══════════════════════════════════════════════════════════
    # 注册 / 更新
    # ═══════════════════════════════════════════════════════════

    def register(self, name: str, purpose: str = "functional",
                 scenario: str = "", priority: str = "P1",
                 constraints: list = None, coverage_bin: str = "",
                 module: str = "", rtl_version_no: Optional[int] = None) -> None:
        """注册/更新一个用例（不覆盖已有状态和验证历史）。

        `module` / `rtl_version_no` 是**绑定**：这个用例属于哪个设计、注册时对应的
        RTL 是哪一版。两者都可缺省（老调用方照旧）—— 缺省就是"不知道"，
        不编一个默认值出来。
        """
        if not name:
            return
        now = self._now()
        with self._lock:
            conn = self._connect()
            existing = conn.execute(
                "SELECT 1 FROM testcase_registry WHERE name = ?", (name,)).fetchone()
            if existing:
                # `module` / `rtl_version_no` **只在传了的时候**才覆盖：同一批用例
                # 可能被不同来源重复注册（spec 分解 / case 模型桥），后来那次不一定
                # 带着版本信息 —— 拿 `''` 把已知的模块名冲掉就是丢证据。
                conn.execute(
                    "UPDATE testcase_registry SET purpose=?, scenario=?, priority=?, "
                    "constraints=?, coverage_bin=?, "
                    "module=CASE WHEN ?<>'' THEN ? ELSE module END, "
                    "rtl_version_no=COALESCE(?, rtl_version_no), updated_at=? "
                    "WHERE name=?",
                    (purpose, scenario, priority,
                     json.dumps(constraints or [], ensure_ascii=False),
                     coverage_bin, module or "", module or "",
                     rtl_version_no, now, name))
            else:
                conn.execute(
                    "INSERT INTO testcase_registry "
                    "(name, purpose, scenario, priority, status, constraints, coverage_bin, "
                    "module, rtl_version_no, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (name, purpose, scenario, priority, STATUS_PLANNED,
                     json.dumps(constraints or [], ensure_ascii=False),
                     coverage_bin, module or "", rtl_version_no, now, now))
            conn.commit()

    @staticmethod
    def _safe_name(name: str) -> str:
        """规范化用例名：去空格/中文/位宽后缀 → 字母数字下划线（回归目录/脚本不能含这些）。"""
        import re
        s = str(name or "")
        s = s.split("[")[0]  # 去掉 [7:0] 位宽后缀
        s = re.sub(r'[^0-9A-Za-z_]+', '_', s).strip('_')
        return s or "case"

    def register_from_spec(self, spec: Dict[str, Any], module_name: str = "dut",
                           rtl_version_no: Optional[int] = None) -> int:
        """场景分解：从 spec 提取场景 → 注册用例（L2 场景 → L3 用例）。

        分层：features → functional 用例，registers → functional 用例，
        interfaces → protocol 用例，默认补 protocol/performance/corner 通用用例。
        返回注册的用例数。

        全部用例都带上 **module**（结构化列，不再只靠 `name` 里的文本）与
        `rtl_version_no`（注册时对应的 RTL 版本；缺省 = 不知道）。
        """
        count = 0
        module_name = self._safe_name(module_name)

        def _reg(name: str, **kw) -> None:
            self.register(name, module=module_name,
                          rtl_version_no=rtl_version_no, **kw)

        # 1. features → functional 用例（每个功能一个基本用例）
        for op in spec.get("features", []) or []:
            name = op if isinstance(op, str) else (op.get("name") or "")
            name = self._safe_name(name)
            if name:
                _reg(f"test_{module_name}_{name}_basic", purpose="functional",
                     scenario=name, priority="P0", coverage_bin=name)
                count += 1
        # 2. registers → functional 用例（寄存器读写）
        for r in spec.get("registers", []) or []:
            if isinstance(r, dict) and r.get("name"):
                rname = self._safe_name(r["name"])
                _reg(f"test_{module_name}_{rname}_rw", purpose="functional",
                     scenario="register_rw", priority="P0",
                     coverage_bin=rname)
                count += 1
        # 3. interfaces → protocol 用例（握手/协议）
        for iface in spec.get("interfaces", []) or []:
            if isinstance(iface, dict) and iface.get("name"):
                iname = self._safe_name(iface["name"])
                _reg(f"test_{module_name}_{iname}_handshake",
                     purpose="protocol", scenario="handshake", priority="P1")
                count += 1
        # 4. 默认补 performance / corner 通用用例（若还没有）
        #
        # 优先级 = 分级回归的 tier（`regression.yaml` 的 tag 直接取 priority.lower()，
        # 见 tool_find_spec_yaml::_generate_regression_yaml）。口径：
        #   P0 功能 / P1 次功能（边界 + corner）/ P2 压力 / P3 错误 + 随机
        # **throughput 与 error_injection 原先都是 P1** —— 于是 p2/p3 两级一条用例都
        # 匹配不到，分级回归跑到 p1 就被 p2 EMPTY 拦下（实测）。压力/错误不是"次功能"，
        # 它们是更晚才该烧机时的两级。
        defaults = [
            ("performance", "throughput", "P2", f"test_{module_name}_throughput"),
            ("corner", "error_injection", "P3", f"test_{module_name}_error_injection"),
            ("corner", "reset", "P0", f"test_{module_name}_reset"),
        ]
        for purpose, scenario, priority, name in defaults:
            with self._lock:
                exists = self._connect().execute(
                    "SELECT 1 FROM testcase_registry WHERE name=?", (name,)).fetchone()
            if not exists:
                _reg(name, purpose=purpose, scenario=scenario, priority=priority)
                count += 1
        return count

    def bind_modules(self, candidates, apply: bool = False) -> Dict[str, Any]:
        """把 `module=''` 的**老行**按命名约定归到真模块（一次性回填）。

        ## 为什么需要它

        `module` 这一列是后加的，之前的行没有归属。而 `get_priority_order(module=)`
        是**严格按列**筛的（读侧不猜 —— 猜错就是把别的项目的用例放进本项目，
        正是要修的病）。所以老行必须先**显式**归位，之后读侧就只剩一条规则。

        ## 归属怎么定

        名字是写侧拼的，约定就两条：`test_<模块>_…`（`register_from_spec` /
        `registry_bridge`）与 `<模块>_…`（spec 派生的 `<模块>_D_ADDR_0` 那类）。
        所以把候选模块名逐个去比，**取最长匹配**：
        `test_apb_uart_case_basic` 同时命中 `apb` 与 `apb_uart` —— 取长的那个，
        否则会把 `apb_uart` 的用例算到 `apb` 头上。

        **`*_loopback` 一律不归属**：那些是 **agent 自检**（`test_<agent>_loopback`），
        不是模块用例。而且它们在回归里有**两条来源** —— 库里这条绑在 DUT build 上
        （错的），生成器自己产的那条绑 `<agent>_loopback_tb`（对的），
        `_dedupe_loopback_tests` 专门在收拾这个重复。不让库里的进来的话，
        这个重复**从源头就没了**。

        **归不上的保持空**（loopback、以及模块名就是兜底 `"dut"` 的 `test_dut_*`）
        —— 它们本来就不属于任何模块，编一个归属出来只是把噪音换个地方藏。
        按模块筛时它们自然落选。

        `apply=False`（缺省）**只算不写**；`apply=True` 先备份库再写。
        """
        cands = sorted({str(c).strip() for c in (candidates or []) if str(c).strip()},
                       key=len, reverse=True)
        conn = self._connect()
        with self._lock:
            rows = conn.execute(
                "SELECT name FROM testcase_registry WHERE module IS NULL OR module=''"
            ).fetchall()

        plan: Dict[str, List[str]] = {}
        unmatched: List[str] = []
        for (name,) in rows:
            stem = name[5:] if name.startswith("test_") else name
            if stem.endswith("_loopback"):
                unmatched.append(name)          # agent 自检，不属于任何模块
                continue
            hit = ""
            for m in cands:
                if stem == m or stem.startswith(m + "_"):
                    hit = m
                    break                       # cands 已按长度降序 → 第一个就是最长
            if hit:
                plan.setdefault(hit, []).append(name)
            else:
                unmatched.append(name)

        out: Dict[str, Any] = {
            "total_legacy": len(rows),
            "attributed": {m: len(v) for m, v in sorted(plan.items())},
            "unmatched": sorted(unmatched),
            "applied": False,
            "backup": "",
        }
        if not apply or not plan:
            return out

        import shutil
        backup = str(self.db_path) + ".bak"
        try:
            self.close()                        # Windows 文件锁：先放连接再拷
            shutil.copy2(self.db_path, backup)
        finally:
            conn = self._connect()
        with self._lock:
            for module, names in plan.items():
                conn.executemany(
                    "UPDATE testcase_registry SET module=?, updated_at=? "
                    "WHERE name=? AND (module IS NULL OR module='')",
                    [(module, self._now(), n) for n in names])
            conn.commit()
        out["applied"] = True
        out["backup"] = backup
        return out

    def update_status(self, name: str, status: str, result: Dict = None) -> None:
        """更新用例状态 + 结果（sim_time/fail_rate/new_coverage），并重算有效性。"""
        if not name:
            return
        result = result or {}
        now = self._now()
        with self._lock:
            conn = self._connect()
            existing = conn.execute(
                "SELECT sim_time, fail_rate, run_count FROM testcase_registry WHERE name = ?",
                (name,)).fetchone()
            if not existing:
                return
            # 累加统计（sim_time 取最新，fail_rate 累计，run_count +1）
            run_count = existing[2] + 1
            sim_time = result.get("sim_time", existing[0])
            failed = 1 if status in (STATUS_FAILED, STATUS_DEPRECATED) else 0
            # 累计失败率 = (历史失败 + 本次失败) / 总次数
            fail_rate = round((existing[1] * (run_count - 1) + failed) / run_count, 3)
            new_coverage = result.get("new_coverage", 0)
            unique_coverage = result.get("unique_coverage", 0)
            effectiveness = self._score_effectiveness(sim_time, fail_rate,
                                                      new_coverage, unique_coverage)
            conn.execute(
                "UPDATE testcase_registry SET status=?, sim_time=?, fail_rate=?, "
                "new_coverage=?, unique_coverage=?, effectiveness=?, run_count=?, "
                "last_run=?, updated_at=? WHERE name=?",
                (status, sim_time, fail_rate, new_coverage, unique_coverage,
                 effectiveness, run_count, now, now, name))
            conn.commit()

    # ═══════════════════════════════════════════════════════════
    # 优先级规划（不同规划目标，优先做什么用例）
    # ═══════════════════════════════════════════════════════════

    def get_priority_order(self, stage: int = 0, limit: int = None,
                           module: str = "") -> List[Dict[str, Any]]:
        """按规划目标（stage）排序，返回优先执行的用例列表。

        排序规则：
          1. purpose 权重（stage 决定：前期功能优先，后期边界优先）
          2. 优先级（P0 > P1 > P2）
          3. 状态（planned 优先，passed 次之，failed/deprecated 最后）
          4. 有效性（高分的优先）

        ## `module`：**这是哪个设计的用例**

        这个库是**项目级**的（项目根 `.signoffai/`，跨 run 累积），里面躺着所有跑过的
        模块。不按模块筛的后果实测过：一次 NPU 的 p0 里跑了 20 条，**14 条是
        `apb_uart` / `apb_slave` 的名字**，而且它们全都用本地的
        `npu_sched_env_directed_test` 兜底执行 —— 于是同一个仿真被数了十几遍，
        "全过"看着很漂亮，其实只有 6 条是这个设计的。

        `module=""`（缺省）＝ **不过滤**（老调用方与"看全库"的场合照旧）。
        """
        stage_idx = min(max(stage, 0), len(STAGE_PURPOSE_WEIGHTS) - 1)
        # 优先用动态 portfolio 权重（optimize_portfolio 更新），未优化则用 stage 静态权重
        weights = self._get_portfolio_weights()
        if not weights:
            weights = STAGE_PURPOSE_WEIGHTS[stage_idx]
        sql = ("SELECT name, purpose, scenario, priority, status, constraints, "
               "coverage_bin, sim_time, fail_rate, effectiveness, run_count "
               "FROM testcase_registry")
        args: tuple = ()
        if module:
            # 老行（`module=''`）**不在这里兜底**：按名字猜模块是读侧的启发式，
            # 猜错会把别的项目的用例放进来（正是要修的病）。归属由
            # `vagent lineage bind-modules` 一次性回填，之后这里就只剩一条规则。
            sql += " WHERE module=?"
            args = (str(module).strip(),)
        with self._lock:
            rows = self._connect().execute(sql, args).fetchall()

        # 状态排序权重：planned 最优先，deprecated 最后
        status_rank = {STATUS_PLANNED: 0, STATUS_GENERATED: 1, STATUS_RUNNING: 2,
                       STATUS_PASSED: 3, STATUS_FAILED: 4, STATUS_DEPRECATED: 5}
        priority_rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

        items = []
        for r in rows:
            (name, purpose, scenario, priority, status, raw_constraints, bin_name,
             sim_time, fail_rate, eff, run_count) = r
            # `constraints` 是**属性组合**（维度/字段/取值）—— 以前这一列没人写、
            # 这里也没人读，于是"建模声明的覆盖点"和"回归跑的用例"之间少一条线。
            # 与 `_row_to_dict` 同一口径解码（坏值当空表，不抛）。
            try:
                constraints = json.loads(raw_constraints or "[]")
            except (ValueError, TypeError):
                constraints = []
            items.append({
                "name": name, "purpose": purpose, "scenario": scenario,
                "priority": priority, "status": status, "constraints": constraints,
                "coverage_bin": bin_name,
                "sim_time": sim_time, "fail_rate": fail_rate,
                "effectiveness": eff, "run_count": run_count,
                # 排序键：purpose 权重（高优先）+ priority（P0 优先）+ 状态（planned 优先）
                "_sort": (
                    -weights.get(purpose, 0.1),       # purpose 权重高 → 排前面
                    priority_rank.get(priority, 9),   # P0 → 排前面
                    status_rank.get(status, 9),       # planned → 排前面
                    -(eff or 0),                       # 有效性高 → 排前面
                ),
            })
        items.sort(key=lambda x: x["_sort"])
        for it in items:
            it.pop("_sort", None)
        return items[:limit] if limit else items

    # ═══════════════════════════════════════════════════════════
    # 比例动态优化（portfolio optimizer）
    # ═══════════════════════════════════════════════════════════

    def _get_portfolio_weights(self) -> Dict[str, float]:
        """从 portfolio 表读取当前 purpose 权重。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT purpose, weight FROM portfolio").fetchall()
        return {p: w for p, w in rows}

    def get_portfolio(self) -> Dict[str, Dict[str, float]]:
        """返回当前 portfolio（purpose → {weight, min_w, max_w}）。"""
        with self._lock:
            rows = self._connect().execute(
                "SELECT purpose, weight, min_w, max_w FROM portfolio").fetchall()
        return {p: {"weight": w, "min_w": min_w, "max_w": max_w}
                for p, w, min_w, max_w in rows}

    def optimize_portfolio(self, coverage_report: Dict[str, Any],
                           iteration: int = 0) -> Dict[str, float]:
        """按覆盖率边际收益动态调整 purpose 权重（DynamicTestPortfolioOptimizer）。

        coverage_report: {"by_purpose": {purpose: {"coverage", "sim_time"}}}
        iteration: 迭代轮次（早期多 functional，后期多 corner 的启发式叠加）
        """
        # 1. 计算各 purpose 的边际收益（覆盖率 / 仿真时间）
        marginal_gains: Dict[str, float] = {}
        by_purpose = coverage_report.get("by_purpose", {}) if coverage_report else {}
        for purpose, data in by_purpose.items():
            cov = float(data.get("coverage", 0) or 0)
            spent = float(data.get("sim_time", 0) or 0)
            marginal_gains[purpose] = cov / (spent + 1)

        # 2. 按边际收益更新权重（限制在 min/max 范围内）
        total_gain = sum(marginal_gains.values()) or 1.0
        portfolio = self.get_portfolio()
        for purpose, gain in marginal_gains.items():
            if purpose not in portfolio:
                continue
            new_weight = gain / total_gain
            min_w = portfolio[purpose]["min_w"]
            max_w = portfolio[purpose]["max_w"]
            portfolio[purpose]["weight"] = max(min_w, min(max_w, new_weight))

        # 3. 早期/后期启发式：前期多 functional，后期多 corner
        if iteration < 5 and "functional" in portfolio:
            portfolio["functional"]["weight"] = min(0.70,
                portfolio["functional"]["weight"] * 1.1)
        elif iteration > 15 and "corner" in portfolio:
            portfolio["corner"]["weight"] = max(0.20,
                portfolio["corner"]["weight"] * 1.1)

        # 4. 归一化
        total = sum(p["weight"] for p in portfolio.values()) or 1.0
        for p in portfolio.values():
            p["weight"] = round(p["weight"] / total, 3)

        # 5. 写回 portfolio 表
        now = self._now()
        with self._lock:
            conn = self._connect()
            for purpose, cfg in portfolio.items():
                conn.execute(
                    "UPDATE portfolio SET weight=? WHERE purpose=?",
                    (cfg["weight"], purpose))
            conn.commit()

        return {p: cfg["weight"] for p, cfg in portfolio.items()}

    # ═══════════════════════════════════════════════════════════
    # 有效性评分
    # ═══════════════════════════════════════════════════════════

    @staticmethod
    def _score_effectiveness(sim_time: float, fail_rate: float,
                             new_coverage: float, unique_coverage: int) -> float:
        """有效性评分（0-100）：
        覆盖率贡献（0-50）+ 运行成本（0-20）+ 稳定性（0-20）+ 独特性（0-10）
        """
        score = 0.0
        # 1. 覆盖率贡献
        if new_coverage > 5:
            score += 40
        elif new_coverage > 0:
            score += 20
        # 2. 运行成本（时间越短越高）
        if sim_time <= 0:
            score += 20
        elif sim_time < 100:
            score += 20
        elif sim_time < 500:
            score += 15
        elif sim_time < 1000:
            score += 10
        else:
            score += 5
        # 3. 稳定性（失败率越低越高）
        score += max(0, 20 - (fail_rate or 0) * 20)
        # 4. 独特性
        if unique_coverage > 0:
            score += 10
        return round(min(score, 100.0), 1)

    def score_effectiveness(self, name: str, result: Dict) -> float:
        """对外评分入口：评分并写回 effectiveness 字段。"""
        self.update_status(name, STATUS_PASSED, result)
        with self._lock:
            row = self._connect().execute(
                "SELECT effectiveness FROM testcase_registry WHERE name = ?",
                (name,)).fetchone()
        return row[0] if row else 0.0

    # ═══════════════════════════════════════════════════════════
    # 查询 / 统计
    # ═══════════════════════════════════════════════════════════

    def get_all(self) -> List[Dict[str, Any]]:
        """**全库原样列出**（含 `constraints`，`_row_to_dict` 解码）。

        与 `get_priority_order` 的区别：那个是**排序后的待跑清单**、还带截断；
        这个是"库里到底有什么"。`constraints` 只有这条路径完整给出 —— 审计
        "建模声明的覆盖点有没有真的进库"要的就是它。
        """
        with self._lock:
            rows = self._connect().execute("SELECT * FROM testcase_registry").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_by_purpose(self, purpose: str, status: str = None) -> List[Dict[str, Any]]:
        with self._lock:
            if status:
                rows = self._connect().execute(
                    "SELECT * FROM testcase_registry WHERE purpose=? AND status=?",
                    (purpose, status)).fetchall()
            else:
                rows = self._connect().execute(
                    "SELECT * FROM testcase_registry WHERE purpose=?",
                    (purpose,)).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM testcase_registry").fetchone()[0]
            by_status = {}
            for r in conn.execute("SELECT status, COUNT(*) FROM testcase_registry GROUP BY status").fetchall():
                by_status[r[0]] = r[1]
            by_purpose = {}
            for r in conn.execute("SELECT purpose, COUNT(*) FROM testcase_registry GROUP BY purpose").fetchall():
                by_purpose[r[0]] = r[1]
        return {"total": total, "by_status": by_status, "by_purpose": by_purpose}

    def deprecate_low_value(self, threshold: float = 10.0) -> List[str]:
        """淘汰低效用例（有效性低于阈值且已运行过）。"""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT name FROM testcase_registry "
                "WHERE run_count > 0 AND effectiveness < ? AND status != 'deprecated'",
                (threshold,)).fetchall()
            deprecated = [r[0] for r in rows]
            for name in deprecated:
                conn.execute(
                    "UPDATE testcase_registry SET status='deprecated', updated_at=? WHERE name=?",
                    (self._now(), name))
            conn.commit()
        return deprecated

    @staticmethod
    def _row_to_dict(row) -> Dict[str, Any]:
        cols = ["name", "purpose", "scenario", "priority", "status", "constraints",
                "coverage_bin", "sim_time", "fail_rate", "new_coverage",
                "unique_coverage", "effectiveness", "run_count", "last_run",
                "created_at", "updated_at",
                # 后加的列排在**最后** —— `SELECT *` 的列序是物理列序，而 ALTER
                # 加的列一律追加在尾部。插在中间就会整体错位一格（每个字段读到
                # 邻居的值），而且不报错。
                "module", "rtl_version_no"]
        d = dict(zip(cols, row))
        try:
            d["constraints"] = json.loads(d.get("constraints") or "[]")
        except Exception:
            d["constraints"] = []
        return d
