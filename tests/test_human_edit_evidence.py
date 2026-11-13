"""人工编辑 → 证据链。

这是一次真实缺口的回归测试：在此之前，**人在界面上改了什么一条痕迹都不留**
—— GUI 的保存就是一句 `Path.write_text`，哈希链 / 运行日志 / 五层证据里都没有。
对一个把"可审计、可追溯"当第一承诺的产品，那是正中间那个洞。

两条设计决定在这里被钉住（它们不是实现细节，是语义）：

  1. 人工变更走**自己的项目级链** `.signoffai/human_edits.json`，不塞进某次运行的
     `file_change_chain.json` —— 后者是 `n_finalize` 从内存整份覆盖落盘的
     （`graph.py:942`），运行暂停期间和运行结束之后的编辑都会被它冲掉。
  2. "谁"复用既有的 `agent` 字段（写成 `human:<名>`），**不新开字段**：
     `agent` 已经在 `_digest` 里，所以人工编辑同样受哈希链保护；新开一个不在
     digest 里的字段，人工编辑就成了链上唯一可以随便改而不会被发现的部分。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.orchestration_plane.l2.evidence.file_audit import FileAuditTrail
from src.orchestration_plane.l2.evidence.human_edit import (
    NO_REASON, project_chain_path, read_human_edits, record_human_edit,
    resolve_author,
)


@pytest.fixture
def repo(tmp_path):
    """一个有 config/ 的假仓库根。"""
    (tmp_path / "config").mkdir()
    return tmp_path


def _edit(repo, name="a.yaml", text="version: 1\n", reason="改了", author="jiang"):
    target = repo / "config" / name
    target.write_text(text, encoding="utf-8")
    return target, record_human_edit(str(target), reason, author=author,
                                     repo_root=str(repo))


class TestRecording:
    def test_a_human_edit_lands_in_the_project_chain(self, repo):
        target, info = _edit(repo)
        assert info["recorded"] is True
        assert info["appended"] == 1

        chain = read_human_edits(repo)
        assert chain["exists"] and chain["total_changes"] == 1
        record = chain["records"][0]
        assert record["file_path"] == "config/a.yaml"
        assert record["agent"] == "human:jiang"
        assert record["reason"] == "改了"
        assert record["content_hash"]          # 内容哈希在，防篡改才有意义

    def test_the_chain_path_is_the_project_growth_dir(self, repo):
        _edit(repo)
        assert project_chain_path(repo) == repo / ".signoffai" / "human_edits.json"
        assert project_chain_path(repo).is_file()

    def test_paths_are_stored_relative_to_the_repo(self, repo):
        """存绝对路径的话，换台机器同一次编辑就成了另一条记录。"""
        _edit(repo)
        assert read_human_edits(repo)["records"][0]["file_path"] == "config/a.yaml"

    def test_an_empty_reason_is_recorded_as_empty_not_invented(self, repo):
        """**不编一个像样的理由顶上去** —— 那会让读链的人分不清哪句是人写的。"""
        _, info = _edit(repo, reason="   ")
        assert info["reason"] == NO_REASON
        assert read_human_edits(repo)["records"][0]["reason"] == NO_REASON

    def test_a_missing_file_is_refused(self, repo):
        info = record_human_edit(str(repo / "config" / "nope.yaml"), "x",
                                 repo_root=str(repo))
        assert info["recorded"] is False
        assert "不存在" in info["error"]

    def test_the_author_comes_from_the_argument_first(self, repo):
        _, info = _edit(repo, author="alice")
        assert info["author"] == "alice"
        assert read_human_edits(repo)["records"][0]["agent"] == "human:alice"

    def test_resolve_author_never_returns_empty(self):
        assert resolve_author("bob") == "bob"
        assert resolve_author()                      # 配置或登录名，反正有个值


class TestChainIntegrity:
    def test_successive_edits_append_and_stay_valid(self, repo):
        """**链要能接着写。** 每次保存都从头开始的话，链还在、历史没了。"""
        for i in range(3):
            _edit(repo, name=f"f{i}.yaml", reason=f"第 {i} 次")
        chain = read_human_edits(repo)
        assert [r["seq"] for r in chain["records"]] == [0, 1, 2]
        assert [r["file_path"] for r in chain["records"]] == [
            "config/f0.yaml", "config/f1.yaml", "config/f2.yaml"]
        assert chain["chain_valid"] is True

    def test_the_first_record_keeps_seq_zero(self, repo):
        """`seq=0` 是第一条记录的**合法值** —— 载入时别把 0 当假值吃掉。"""
        _edit(repo)
        assert read_human_edits(repo)["records"][0]["seq"] == 0

    def test_tampering_with_a_past_record_is_detected(self, repo):
        _edit(repo, name="a.yaml")
        _edit(repo, name="b.yaml")
        path = project_chain_path(repo)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["records"][0]["reason"] = "偷偷改掉的理由"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        issues = FileAuditTrail.verify_persisted(path)["issues"]
        assert any(i["type"] == "hash_broken" for i in issues), issues

    def test_truncating_the_tail_is_detected(self, repo):
        """内存 verify() 等于「自己验自己」—— 尾部被裁要回读磁盘才发现。"""
        _edit(repo, name="a.yaml")
        _edit(repo, name="b.yaml")
        path = project_chain_path(repo)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["records"].pop()
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

        issues = FileAuditTrail.verify_persisted(path)["issues"]
        assert any(i["type"] == "tail_truncated" for i in issues), issues

    def test_reading_a_missing_chain_is_not_an_error(self, repo):
        chain = read_human_edits(repo)
        assert chain["exists"] is False and chain["total_changes"] == 0
        assert chain["chain_valid"] is True          # 空的链是完整的链


class TestJumpingToEmpty:
    """链不存在时 `open()` 不该炸，也不该凭空造一条。"""

    def test_open_on_a_missing_file_starts_empty(self, tmp_path):
        trail = FileAuditTrail.open(tmp_path / "nope.json")
        assert trail.records == [] and trail.prev_hash == ""

    def test_open_on_garbage_does_not_raise(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{这不是 json", encoding="utf-8")
        assert FileAuditTrail.open(bad).records == []


class TestJournalAnchor:
    """给了 run_id 就往那次运行写一条 `human.edit` —— 用锚点，不复制。"""

    def test_a_missing_run_is_not_a_failure(self, repo):
        """运行目录找不到就不写日志（链已经记上了），但**不能因此失败**。"""
        _, info = _edit(repo)
        assert info["journal"] is None
        assert read_human_edits(repo)["total_changes"] == 1

    def test_the_event_lands_in_the_run_journal(self, repo, tmp_path):
        from src.orchestration_plane.l2.run_journal import RunJournal

        run_dir = repo / "output_demo_20260101_000000"
        (run_dir / "docs").mkdir(parents=True)
        journal = RunJournal(run_dir, run_id="output_demo_20260101_000000")
        journal.record("run.started")
        journal.record("stage.finished", stage="verify", status="ok")

        target = repo / "config" / "a.yaml"
        target.write_text("version: 1\n", encoding="utf-8")
        info = record_human_edit(str(target), "人工修正 harness", author="jiang",
                                 run_id="output_demo_20260101_000000",
                                 repo_root=str(repo))
        assert info["journal"] is not None, "锚点没写进运行日志"

        events = journal.read() if hasattr(journal, "read") else None
        if events is None:                       # 用模块级读法，别依赖实例状态
            from src.orchestration_plane.l2.run_journal import read_journal
            events = read_journal(run_dir)
        edited = [e for e in events if e.kind == "human.edit"]
        assert edited, [e.kind for e in events]
        assert edited[0].payload["file"] == "config/a.yaml"
        assert "人工修正 harness" in edited[0].payload["reason"]
