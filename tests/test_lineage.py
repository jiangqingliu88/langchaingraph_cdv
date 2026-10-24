"""血缘 —— RTL 版本 / run 基准 / bug↔版本 / 用例↔模块。

四件事缺的是同一个东西：**跨 run 的一级实体**。之前：

    run     跟谁比？          → 「首次 run 是基准」这件事只活在人的记忆里
    RTL     这轮跑的是哪版？   → 只有 `manifest.rtl_hashes`（16 位截断、只 `*.sv`）
    bug     在哪个版本发现？   → bug 记录里连 RTL 都没有
    用例    属于哪个模块？     → 只在 `name` 字符串里文本嵌着

所以这里钉几条**身份**性质的不变量 —— 它们错了不会报错，只会让血缘挂到别处：
版本必须由**内容**决定（跑的次数不是版本）、基准必须**幂等**（首次即锚，不被后来的覆盖）、
老库必须能**原地长出新列**（否则写入端报 no such column，或更糟：静默丢字段）。
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.layers.l4_memory.lineage import (LineageStore, compute_rtl_dir_hash,
                                          ensure_run_rtl_version)


def _rtl(root: Path, name: str = "dut", body: str = "module dut; endmodule\n") -> Path:
    d = root / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.sv").write_text(body, encoding="utf-8")
    return d


class TestTheRtlContentHash:
    """版本身份由**内容**决定 —— 哈希口径错一次，老记录全对不上。"""

    def test_it_is_deterministic_and_full_length(self, tmp_path):
        h1 = compute_rtl_dir_hash(_rtl(tmp_path))
        assert h1 == compute_rtl_dir_hash(_rtl(tmp_path))
        assert len(h1) == 64, "必须是**全** 64 位 —— `[:16]` 那是给人看的短标识，做身份会撞"

    def test_an_empty_dir_is_empty_not_a_hash(self, tmp_path):
        """没有 RTL ≠ RTL 是空的：空串让调用方**整条跳过**血缘，而不是写出一个假 v1。"""
        (tmp_path / "rtl").mkdir()
        assert compute_rtl_dir_hash(tmp_path / "rtl") == ""
        assert compute_rtl_dir_hash(tmp_path / "nope") == ""

    def test_a_one_byte_change_is_a_new_version(self, tmp_path):
        h1 = compute_rtl_dir_hash(_rtl(tmp_path, body="module dut; endmodule\n"))
        h2 = compute_rtl_dir_hash(_rtl(tmp_path, body="module dut; // x\nendmodule\n"))
        assert h1 != h2

    def test_all_source_suffixes_count_not_just_sv(self, tmp_path):
        """只收 `*.sv` 就等于"改了 `.v/.svh/.vh` 版本号不动" —— 而那正是要防的事。"""
        d = _rtl(tmp_path)
        h1 = compute_rtl_dir_hash(d)
        (d / "defs.svh").write_text("`define W 8\n", encoding="utf-8")
        assert compute_rtl_dir_hash(d) != h1

    def test_name_content_concatenation_cannot_collide(self, tmp_path):
        """`a.sv`(b) + `b.sv` 与 `a.svb.sv` 不能撞成同一个聚合 —— 用 `\\0` 分隔。

        这不是学究：RTL 目录里文件名是设计的一部分，换个切分方式就会有两份
        不同的 RTL 算出同一个版本号，而**没有任何东西会报**。
        """
        d1 = tmp_path / "d1" / "rtl"
        d1.mkdir(parents=True)
        (d1 / "a.sv").write_text("b", encoding="utf-8")
        (d1 / "b.sv").write_text("", encoding="utf-8")
        d2 = tmp_path / "d2" / "rtl"
        d2.mkdir(parents=True)
        (d2 / "a.svb.sv").write_text("", encoding="utf-8")
        assert compute_rtl_dir_hash(d1) != compute_rtl_dir_hash(d2)


class TestVersionNumbers:
    """版本号：同内容**幂等**，不同内容**递增**。"""

    def _store(self, tmp_path) -> LineageStore:
        return LineageStore(tmp_path / "lineage.db")

    def test_same_hash_is_the_same_version_forever(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_rtl_version("m", "h1", "run1") == 1
            assert s.ensure_rtl_version("m", "h1", "run2") == 1, \
                "跑的次数不是版本 —— 同一个内容跑一百轮都该是 v1"
        finally:
            s.close()

    def test_a_new_hash_is_the_next_version(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_rtl_version("m", "h1") == 1
            assert s.ensure_rtl_version("m", "h2") == 2
        finally:
            s.close()

    def test_modules_are_numbered_independently(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_rtl_version("a", "h1") == 1
            assert s.ensure_rtl_version("b", "h1") == 1
        finally:
            s.close()

    def test_no_module_or_no_hash_is_not_a_version(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_rtl_version("", "h1") is None
            assert s.ensure_rtl_version("m", "") is None
        finally:
            s.close()

    def test_run_binding_is_upsert_by_run_id(self, tmp_path):
        s = self._store(tmp_path)
        try:
            s.bind_run("run1", "m", "h1", 1)
            s.bind_run("run1", "m", "h2", 2)          # 重入应覆盖，不报主键冲突
            assert s.version_by_run("run1")["version_no"] == 2
        finally:
            s.close()


class TestTheBaselineIsTheFirstRun:
    """基准 = **每个模块的第一次 run**，写下就不再改。"""

    def _store(self, tmp_path) -> LineageStore:
        return LineageStore(tmp_path / "lineage.db")

    def test_first_run_wins_and_later_runs_do_not_move_it(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_baseline("m", "run1", 1) is True
            assert s.ensure_baseline("m", "run2", 2) is False
            base = s.get_baseline("m")
            assert (base["run_id"], base["version_no"]) == ("run1", 1)
        finally:
            s.close()

    def test_it_is_idempotent_even_for_the_same_run(self, tmp_path):
        s = self._store(tmp_path)
        try:
            assert s.ensure_baseline("m", "run1", 1) is True
            assert s.ensure_baseline("m", "run1", 1) is False
        finally:
            s.close()


class TestBugsAreLinkedToVersions:
    def test_found_and_fixed_merge_into_one_row(self, tmp_path):
        """先记 found、修完再补 fixed —— 补的那次不能把 found 冲掉。"""
        s = LineageStore(tmp_path / "lineage.db")
        try:
            s.link_bug("BUG-1", "m", found_version_no=1, found_run_id="run1")
            s.link_bug("BUG-1", "m", fixed_version_no=2, fixed_run_id="run2")
            (row,) = s.bugs_of_version("m")
            assert (row["found_version_no"], row["fixed_version_no"]) == (1, 2)
            assert (row["found_run_id"], row["fixed_run_id"]) == ("run1", "run2")
        finally:
            s.close()

    def test_query_by_version_finds_either_side(self, tmp_path):
        s = LineageStore(tmp_path / "lineage.db")
        try:
            s.link_bug("BUG-1", "m", found_version_no=1, fixed_version_no=2)
            assert [b["bug_id"] for b in s.bugs_of_version("m", 1)] == ["BUG-1"]
            assert [b["bug_id"] for b in s.bugs_of_version("m", 2)] == ["BUG-1"]
            assert s.bugs_of_version("m", 3) == []
        finally:
            s.close()


class TestTheRunVersionEntry:
    """`ensure_run_rtl_version` —— front / debug / finalize **共用的那一个入口**。

    三个阶段各算一遍就会同一个 run 三个版本号，而它们都不报错。
    """

    def test_it_binds_the_run_and_returns_the_manifest_slice(self, tmp_path,
                                                             monkeypatch):
        monkeypatch.chdir(tmp_path)
        _rtl(tmp_path)
        got = ensure_run_rtl_version(tmp_path, module="m", run_id="run1")
        assert got["module"] == "m" and got["version_no"] == 1
        assert got["name"] == "v1" and len(got["content_hash"]) == 64
        s = LineageStore()
        try:
            assert s.version_by_run("run1")["version_no"] == 1
        finally:
            s.close()

    def test_no_rtl_means_no_lineage_at_all(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert ensure_run_rtl_version(tmp_path, module="m", run_id="run1") == {}
        assert not (tmp_path / ".signoffai" / "lineage.db").exists(), \
            "没有 RTL 就不该建库 —— 否则会出现一个「有库没料」的假象"

    def test_module_falls_back_to_spec_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _rtl(tmp_path)
        (tmp_path / "spec.json").write_text('{"design_name": "npu_sched"}',
                                            encoding="utf-8")
        assert ensure_run_rtl_version(tmp_path, run_id="r")["module"] == "npu_sched"


class TestTheTestcaseRegistryCarriesModuleAndVersion:
    """用例要有**模块绑定**与**版本绑定** —— 两者原先都只在 `name` 字符串里。"""

    def _old_db(self, path: Path) -> None:
        """建一个**没有新列的**老库 + 一行数据（模拟现场累积下来的库）。"""
        c = sqlite3.connect(str(path))
        c.executescript("""
CREATE TABLE testcase_registry (
    name TEXT PRIMARY KEY, purpose TEXT NOT NULL DEFAULT 'functional',
    scenario TEXT NOT NULL DEFAULT '', priority TEXT NOT NULL DEFAULT 'P1',
    status TEXT NOT NULL DEFAULT 'planned', constraints TEXT NOT NULL DEFAULT '[]',
    coverage_bin TEXT NOT NULL DEFAULT '', sim_time REAL NOT NULL DEFAULT 0,
    fail_rate REAL NOT NULL DEFAULT 0, new_coverage REAL NOT NULL DEFAULT 0,
    unique_coverage INTEGER NOT NULL DEFAULT 0, effectiveness REAL NOT NULL DEFAULT 0,
    run_count INTEGER NOT NULL DEFAULT 0, last_run TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL DEFAULT '');
INSERT INTO testcase_registry (name, purpose, coverage_bin)
VALUES ('legacy_case', 'protocol', 'opcode[7:0]');
""")
        c.commit()
        c.close()

    def test_an_old_db_grows_the_columns_without_losing_rows(self, tmp_path):
        """`CREATE TABLE IF NOT EXISTS` 对**已存在**的老库整条跳过 ——
        不 ALTER 的话新列永远长不出来，而写入端会报 no such column。"""
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        db = tmp_path / "tc.db"
        self._old_db(db)
        reg = TestcaseRegistry(db)
        try:
            cols = [r[1] for r in reg._connect().execute(
                "PRAGMA table_info(testcase_registry)")]
            assert {"module", "rtl_version_no"} <= set(cols)
            (row,) = reg.get_all()
            assert row["name"] == "legacy_case" and row["coverage_bin"] == "opcode[7:0]"
            assert row["module"] == "" and row["rtl_version_no"] is None
        finally:
            reg.close()

    def test_the_new_columns_are_read_at_the_right_offset(self, tmp_path):
        """`SELECT *` 的列序是**物理列序**，ALTER 加的列在尾部 —— 插在中间会整体错位。

        错位的表现是每个字段读到邻居的值，**而且不报错**（最难查的那一类）。
        """
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        reg = TestcaseRegistry(tmp_path / "tc.db")
        try:
            reg.register("t1", purpose="performance", scenario="throughput",
                         priority="P2", module="m", rtl_version_no=7)
            (row,) = reg.get_all()
            assert (row["purpose"], row["scenario"], row["priority"]) == \
                ("performance", "throughput", "P2")
            assert (row["module"], row["rtl_version_no"]) == ("m", 7)
            assert row["created_at"] and row["updated_at"]
        finally:
            reg.close()

    def test_a_later_register_without_module_does_not_wipe_it(self, tmp_path):
        """同一批用例会被多个来源重复注册，后来那次不一定带模块 —— 拿空串冲掉
        已知的模块名就是丢证据。"""
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        reg = TestcaseRegistry(tmp_path / "tc.db")
        try:
            reg.register("t1", module="m", rtl_version_no=3)
            reg.register("t1", scenario="again")           # 不带模块/版本
            (row,) = reg.get_all()
            assert row["module"] == "m" and row["rtl_version_no"] == 3
            assert row["scenario"] == "again"              # 其他字段照常更新
        finally:
            reg.close()

    def test_register_from_spec_binds_every_case(self, tmp_path):
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        reg = TestcaseRegistry(tmp_path / "tc.db")
        try:
            reg.register_from_spec(
                {"interfaces": [{"name": "clk"}, {"name": "op_priority"}]},
                "npu_sched", rtl_version_no=4)
            rows = reg.get_all()
            assert rows, "应该注册出若干用例"
            assert {r["module"] for r in rows} == {"npu_sched"}
            assert {r["rtl_version_no"] for r in rows} == {4}
        finally:
            reg.close()

    def test_register_cases_binds_module_and_version(self, tmp_path):
        from src.tools.generation.casemodel_tools.registry_bridge import register_cases

        yaml_text = Path("specs/npu_sched/casemodel.yaml").read_text(encoding="utf-8")
        out = register_cases(yaml_text, "npu_sched",
                             db_path=str(tmp_path / "tc.db"), rtl_version_no=5)
        assert out["registered"] > 0, out
        c = sqlite3.connect(str(tmp_path / "tc.db"))
        rows = c.execute("SELECT module, rtl_version_no FROM testcase_registry "
                         "WHERE module<>''").fetchall()
        c.close()
        assert rows and all(r == ("npu_sched", 5) for r in rows)


class TestEveryRegistrationSiteCarriesTheVersion:
    """**每一处注册用例的落点**都要带版本 —— 源级守卫。

    落地时就是这么漏的：`register_from_spec` 有三处调用（front agent 的
    `execute_task`、`n_design` 的 bypass 分支与常规分支），只改了 front 那处 ——
    于是同一个模块的用例**一半带版本、一半不带**，而两边都不报错。
    这正是这个仓库反复吃的那一类（"同一件事有多个落点，改了三个漏一个"）。
    """

    def test_all_register_call_sites_pass_a_version(self):
        import re

        repo = Path(__file__).resolve().parents[1]
        offenders = []
        for py in list((repo / "src").rglob("*.py")):
            # 测例自己调 register_* 是为了验别的行为，参数本就是可选的 —— 只管生产落点
            if "tests" in py.parts or py.name.startswith("test_"):
                continue
            text = py.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"\b(register_from_spec|register_cases)\s*\(", text):
                # 取这次调用的完整实参串（按括号配平到收尾）
                depth, i = 0, m.end() - 1
                while i < len(text):
                    if text[i] == "(":
                        depth += 1
                    elif text[i] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    i += 1
                call = text[m.end():i]
                if "rtl_version_no" not in call:
                    offenders.append(f"{py.relative_to(repo).as_posix()}"
                                     f"::{m.group(1)}")
        assert not offenders, (
            "这些注册落点没带 rtl_version_no —— 用例会一半带版本一半不带，"
            f"而两边都不报错：{offenders}")


class TestTheCaseLibraryIsScopedToTheModule:
    """用例库是**项目级**的（躺着所有跑过的模块）—— 取用例时必须按模块划边界。

    实测：一次 NPU 的 p0 跑了 20 条，**14 条是 `apb_uart` / `apb_slave` 的名字**，
    而且全部用本地的 `npu_sched_env_directed_test` 兜底执行 —— 同一个仿真被数了
    十几遍。"全过"看着漂亮，真属于这个设计的只有 6 条。这类假绿正是本仓库
    最贵的一类 bug（数字全对、结论是错的）。
    """

    def _reg(self, tmp_path):
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        reg = TestcaseRegistry(tmp_path / "tc.db")
        reg.register("test_apb_uart_D_ADDR_0", priority="P0", module="apb_uart")
        reg.register("test_npu_sched_D_ADDR_0", priority="P0", module="npu_sched")
        reg.register("test_dut_throughput", priority="P2")          # 归属未知
        return reg

    def test_only_this_module_is_returned(self, tmp_path):
        reg = self._reg(tmp_path)
        try:
            names = [c["name"] for c in reg.get_priority_order(module="npu_sched")]
            assert names == ["test_npu_sched_D_ADDR_0"], names
            assert "test_apb_uart_D_ADDR_0" not in names
        finally:
            reg.close()

    def test_without_module_it_still_sees_everything(self, tmp_path):
        """缺省**不过滤** —— "看全库"（审计、`get_stats`）那些调用方靠它。"""
        reg = self._reg(tmp_path)
        try:
            assert len(reg.get_priority_order()) == 3
        finally:
            reg.close()

    def test_unattributed_rows_are_not_smuggled_in(self, tmp_path):
        """`module=''` 的老行**不兜底放行** —— 读侧按名字猜就是把别的项目的用例
        放进来（正是要修的病）。归属只由一次性回填写，之后读侧只有一条规则。"""
        reg = self._reg(tmp_path)
        try:
            names = [c["name"] for c in reg.get_priority_order(module="npu_sched")]
            assert "test_dut_throughput" not in names
        finally:
            reg.close()

    def test_the_regression_generator_passes_the_module(self):
        src = Path("src/tools/generation/uvm_tools/tool_find_spec_yaml/generators/regression_gen.py").read_text(
            encoding="utf-8")
        assert "get_priority_order(stage=0, limit=50, module=module_name)" in src, \
            "生成 regression.yaml 时没按模块筛 —— 跨项目用例会混进来"


class TestTheLegacyModuleBackfill:
    """老行归位：按命名约定取**最长匹配**，agent 自检与兜底名不归属。"""

    def _reg(self, tmp_path):
        from src.layers.l4_memory.testcase_registry import TestcaseRegistry

        return TestcaseRegistry(tmp_path / "tc.db")

    def _seed(self, reg):
        for n in ("test_apb_uart_case_basic", "apb_uart_D_ADDR_0",
                  "test_apb_master_paddr_handshake", "test_apb_loopback",
                  "test_npu_sched_in_loopback", "test_dut_reset"):
            reg.register(n, priority="P0")

    def test_the_longest_match_wins(self, tmp_path):
        """`test_apb_uart_case_basic` 同时命中 `apb` 与 `apb_uart` —— 取长的那个，
        否则 A 的用例会被算到 B 头上（而两边都不报错）。"""
        reg = self._reg(tmp_path)
        try:
            self._seed(reg)
            plan = reg.bind_modules(["apb", "apb_uart", "apb_master"])
            assert plan["attributed"] == {"apb_master": 1, "apb_uart": 2}
        finally:
            reg.close()

    def test_loopback_and_the_fallback_name_are_never_attributed(self, tmp_path):
        """`*_loopback` 是 **agent 自检**；`test_dut_*` 的模块名是兜底值。
        两者都不属于任何模块 —— 不让它们进来，回归里那份重复**从源头就没了**。"""
        reg = self._reg(tmp_path)
        try:
            self._seed(reg)
            plan = reg.bind_modules(["apb", "apb_uart", "apb_master", "npu_sched"])
            assert "test_apb_loopback" in plan["unmatched"]
            assert "test_npu_sched_in_loopback" in plan["unmatched"]
            assert "test_dut_reset" in plan["unmatched"]
        finally:
            reg.close()

    def test_dry_run_writes_nothing(self, tmp_path):
        reg = self._reg(tmp_path)
        try:
            self._seed(reg)
            plan = reg.bind_modules(["apb_uart"])
            assert plan["applied"] is False and plan["backup"] == ""
            assert all(r["module"] == "" for r in reg.get_all()
                       if r["name"].startswith("test_apb_uart"))
        finally:
            reg.close()

    def test_apply_writes_and_backs_up_first(self, tmp_path):
        reg = self._reg(tmp_path)
        try:
            self._seed(reg)
            out = reg.bind_modules(["apb_uart", "apb_master"], apply=True)
            assert out["applied"] is True and out["backup"].endswith(".bak")
            assert Path(out["backup"]).is_file(), "写库前必须先备份"
            got = {r["name"]: r["module"] for r in reg.get_all()}
            assert got["test_apb_uart_case_basic"] == "apb_uart"
            assert got["test_dut_reset"] == ""          # 归不上就保持空
        finally:
            reg.close()

    def test_it_only_touches_rows_without_a_module(self, tmp_path):
        """已经有归属的行**不许被改** —— 回填只补空，不覆盖已知。"""
        reg = self._reg(tmp_path)
        try:
            reg.register("test_apb_uart_case_basic", module="already_known")
            reg.bind_modules(["apb_uart"], apply=True)
            got = {r["name"]: r["module"] for r in reg.get_all()}
            assert got["test_apb_uart_case_basic"] == "already_known"
        finally:
            reg.close()


class TestBaselineAwareCompare:
    """「跟谁比」不再靠人肉记目录名 —— 从血缘里反查。"""

    def _run(self, root: Path, run_id: str, body: str) -> Path:
        d = root / run_id
        (d / "rtl").mkdir(parents=True)
        (d / "rtl" / "dut.sv").write_text(body, encoding="utf-8")
        (d / "docs").mkdir()
        (d / "docs" / "report.json").write_text(
            '{"verdict": "PASS", "signoff_status": "approved"}', encoding="utf-8")
        return d

    def test_it_finds_the_first_run_of_the_same_module(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # 血缘库已统一到 database/（绝对路径）；本测试要隔离，显式指到 tmp。
        import config.paths as _paths

        monkeypatch.setattr(_paths, "LINEAGE_DB", tmp_path / "lineage.db", raising=False)
        a = self._run(tmp_path, "output_a_20260101_000000", "module dut; endmodule\n")
        b = self._run(tmp_path, "output_b_20260102_000000", "module dut; endmodule\n")
        for d in (a, b):
            ensure_run_rtl_version(d, module="dut", run_id=d.name)
        s = LineageStore()
        try:
            s.ensure_baseline("dut", a.name, 1)
        finally:
            s.close()

        from src.tools.flow.flow_tools.lineage_api import (baseline_of_run,
                                                      compare_against_baseline)

        anchor = baseline_of_run(b)
        assert anchor["run_id"] == a.name
        assert anchor["current_version"] == "v1"
        result = compare_against_baseline(str(b))
        assert Path(result["baseline_dir"]).name == a.name

    def test_no_anchor_is_an_error_not_an_empty_diff(self, tmp_path, monkeypatch):
        """查不到锚点要**明说** —— 返回一个空 diff 会被读成"没有差异"。"""
        monkeypatch.chdir(tmp_path)
        lonely = self._run(tmp_path, "output_c_20260103_000000",
                           "module dut; endmodule\n")
        from src.tools.flow.flow_tools.lineage_api import compare_against_baseline

        result = compare_against_baseline(str(lonely))
        assert "error" in result and "血缘" in result["error"]

    def test_an_explicit_baseline_wins(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        a = self._run(tmp_path, "output_a_20260101_000000", "module dut; endmodule\n")
        b = self._run(tmp_path, "output_b_20260102_000000", "module dut; endmodule\n")
        from src.tools.flow.flow_tools.lineage_api import compare_against_baseline

        result = compare_against_baseline(str(b), baseline=str(a))
        assert Path(result["baseline_dir"]).name == a.name
