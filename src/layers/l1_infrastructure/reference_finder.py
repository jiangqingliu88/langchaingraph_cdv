"""Reference Finder —— 逐版本回溯，定位「哪个提交引入了这个失败」。

它回答的问题

    某个用例在最新版本失败了。它是什么时候坏的？
    即：找出 `good..bad` 区间里**第一个失败**的提交。

为什么这属于 L1

    L1 已经拥有 `run_regression` 与 `output_root` 的生命周期，而本功能的原子动作
    就是「在某个版本上跑一次回归」。所以它在 L1，**不改回归框架**：
    回归框架本来就是 per-output_root 的，每个版本给一个 output_root 就天然隔离；
    单用例选择用现成的 `tests` 参数。

两条硬约束（都是被真实教训逼出来的）

    1. **绝不用 `git checkout` 切换版本。**
       那会把用户的工作区切走，回溯过程中任何中断都留下一棵半切状态的树。
       一律用 `git worktree add --detach`：独立目录、独立 HEAD、跑完即删。

    2. **`inconclusive` 不等于 pass 也不等于 fail。**
       编译不过、缺 license、超时 —— 这些既不能算「这个版本是好的」（会把 bug
       引入点推后），也不能算「这个版本已经坏了」（会推向更早）。静默归入任何
       一边都会给出**看起来确定、实际错误**的结论。所以单独一态，并在结论里
       降级可靠性、把可疑版本列出来让人复核。

与 ExecMan 的差异

    手册那张图描述的是**线性回溯**（N-1, N-2, ...），代价 O(n)。这里用二分，
    O(log n)。不是优化选项：每个版本都要完整编译+仿真，一次几十秒到几分钟，
    十来个版本线性跑就不可用了。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import env_snapshot

#: 单版本回归的三种结论。**三态，不是两态** —— 见模块 docstring 的约束 2。
PASS, FAIL, INCONCLUSIVE = "pass", "fail", "inconclusive"


@dataclass
class RevisionResult:
    """某个版本上跑一次的结果。"""
    rev: str
    short: str
    verdict: str
    detail: str = ""
    run_root: str = ""
    passed: int = 0
    failed: int = 0
    unknown: int = 0
    elapsed_s: float = 0.0
    from_cache: bool = False


def _posix(p: Any) -> str:
    """Windows 路径统一成正斜杠再注入配置。

    生成的脚本是 bash 跑的，`D:\\a\\b` 里的反斜杠会被当转义符吃掉，路径直接
    找不着 —— 这个坑在回归框架的 waves 目录上已经踩过一次（见 shell.py）。
    凡是往 run_cmd 里注入的路径都要过这一道。
    """
    return str(p).replace("\\", "/")


def _git(repo: str | Path, *args: str, check: bool = True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def list_revisions(repo: str | Path, good: str, bad: str,
                   paths: List[str] = None) -> List[str]:
    """列出 `good..bad` 之间的提交，**按时间正序**（最早的在最前）。

    正序很重要：二分的语义是「找第一个失败的」，比较的是时间先后。
    `paths` 可限定只看某些目录/文件的变更（比如只关心 `rtl/`）。
    """
    args = ["log", "--format=%H", "--reverse", f"{good}..{bad}"]
    if paths:
        args += ["--", *paths]
    out = _git(repo, *args, check=False)
    return [line.strip() for line in out.splitlines() if line.strip()]


class ReferenceFinder:
    """在 `good..bad` 区间内二分定位首个失败的提交。"""

    def __init__(self, repo_path: str | Path, work_root: str | Path,
                 reg_yaml: str | Path, test_pattern: str,
                 mode: str = "mock", overrides: List[str] = None,
                 keep_worktrees: bool = False, verbose: bool = True,
                 use_cache: bool = True, debug_at_boundary: bool = False):
        self.repo = Path(repo_path).resolve()
        self.work_root = Path(work_root).resolve()
        self.reg_yaml = str(Path(reg_yaml).resolve())
        self.test_pattern = test_pattern
        self.mode = mode
        self.overrides = overrides or []
        self.keep_worktrees = keep_worktrees
        self.verbose = verbose
        self.use_cache = use_cache
        #: 定位到之后，是否在边界两个版本上补跑 Debug Run（产出对比素材）
        self.debug_at_boundary = debug_at_boundary
        # 缓存键要带环境摘要 —— 结论不只取决于代码，还取决于跑它的环境
        self._env_digest = ""
        #: 整块区间的环境快照（用配置本身算，与版本无关的部分）
        self._base_snapshot = env_snapshot.capture_optional(
            repo_root=self.repo, config_path=self.reg_yaml) or {}
        self._env_digest = self._base_snapshot.get("digest", "")

        self.work_root.mkdir(parents=True, exist_ok=True)
        self.wt_root = self.work_root / "worktrees"
        self.wt_root.mkdir(parents=True, exist_ok=True)
        self.results: List[RevisionResult] = []
        # 每跑一个版本拍一张快照，用于事后回答「这些版本是在同一环境里跑的吗」
        self.snapshots: Dict[str, Dict[str, Any]] = {}

    # ═══════════════════════════════════════════════════════════
    # 日志
    # ═══════════════════════════════════════════════════════════

    def _log(self, msg: str) -> None:
        if self.verbose:
            print(f"[reference-finder] {msg}", flush=True)

    # ═══════════════════════════════════════════════════════════
    # 单版本原语
    # ═══════════════════════════════════════════════════════════

    def _worktree_for(self, rev: str) -> Path:
        """给某个版本开一个独立工作区。**不动用户工作区**。"""
        short = rev[:12]
        wt = self.wt_root / short
        if wt.exists():
            # 上一轮残留（被中断过）：先摘掉再重建，保证这棵树一定是干净的
            subprocess.run(["git", "-C", str(self.repo), "worktree", "remove",
                            "--force", str(wt)],
                           capture_output=True, text=True)
            shutil.rmtree(wt, ignore_errors=True)
        _git(self.repo, "worktree", "add", "--detach", str(wt), rev)
        return wt

    def _drop_worktree(self, wt: Path) -> None:
        if self.keep_worktrees:
            self._log(f"保留工作区（--keep-worktrees）: {wt}")
            return
        subprocess.run(["git", "-C", str(self.repo), "worktree", "remove",
                        "--force", str(wt)],
                       capture_output=True, text=True)
        shutil.rmtree(wt, ignore_errors=True)

    def run_at_revision(self, rev: str, debug_mode: bool = False) -> RevisionResult:
        """跑一次「这个版本」。这是整个功能的原子动作。

        步骤：worktree 隔离 → 该版本自己的 output_root → 复用现成的
        `InfrastructureManager.run_regression` 跑指定用例 → 归一成三态。
        """
        # **先把 ref 解成完整 SHA**。用户传进来的可能是 `HEAD` / tag / 分支名，
        # 而区间里的提交是 SHA。不解开的话：同一个提交换个名字就有两份产物，
        # 工作目录名也变成 `runs/HEAD` 这种；更要命的是**缓存键不一致** ——
        # 端点按 `HEAD` 缓存、二分中途按 SHA 缓存，同一个提交会白跑两次。
        full = _git(self.repo, "rev-parse", rev, check=False) or rev
        rev = full
        short = _git(self.repo, "rev-parse", "--short", rev, check=False) or rev[:12]
        t0 = time.time()
        run_root = self.work_root / "runs" / rev[:12]

        # ── 缓存命中就直接返回：省掉的是一次完整编译 + 仿真（分钟级）──
        if self.use_cache:
            try:
                from ..l4_memory.reference_finder_cache import get_reference_finder_cache
                hit = get_reference_finder_cache().get(
                    str(self.repo), rev, self.test_pattern, self._env_digest)
            except Exception as e:                            # 缓存故障不该挡住回溯
                self._log(f"缓存读取失败（忽略）: {e}")
                hit = None
            if hit:
                res = RevisionResult(
                    rev=rev, short=short, verdict=hit["verdict"],
                    detail=hit["detail"], run_root=hit["run_root"],
                    passed=hit["passed"], failed=hit["failed"],
                    unknown=hit["unknown"], elapsed_s=round(time.time() - t0, 2),
                    from_cache=True)
                self._log(f"{short} → {res.verdict}（缓存命中）")
                self.results.append(res)
                return res

        run_root.mkdir(parents=True, exist_ok=True)

        wt = None
        try:
            wt = self._worktree_for(rev)
            self._log(f"{short} 工作区就绪 → {wt}")

            # 环境快照：跑之前拍，记录这个版本是在什么环境下跑的
            self.snapshots[rev] = env_snapshot.capture_optional(
                repo_root=wt, config_path=self.reg_yaml,
                extra={"revision": rev}) or {}

            # 版本内的配置：worktree 里的那份（如果版本里有），否则用给定的
            cfg = self.reg_yaml
            wt_cfg = wt / Path(self.reg_yaml).name
            if wt_cfg.exists():
                cfg = str(wt_cfg)

            # 按版本改写路径：把配置里的绝对路径指到本版本自己的目录，
            # 否则所有版本共用同一份产物，「换版本」就名存实亡。
            #
            # 配置在版本之间是**同一份**（这正是"同一份配置、不同代码"的语义），
            # 所以它不能把路径写死 —— 通过下面这几个变量引用，每个版本拿到自己的：
            #   RF_WORKTREE  该版本代码的检出目录（worktree）
            #   RF_RUN_DIR   该版本的回归输出目录
            overrides = list(self.overrides) + [
                f"variables.WORK={_posix(run_root / 'build' / 'work')}",
                f"variables.RF_WORKTREE={_posix(wt)}",
                f"variables.RF_RUN_DIR={_posix(run_root)}",
            ]

            from .infrastructure import InfrastructureManager
            infra = InfrastructureManager(run_root, repo_root=wt)
            # reference_mode=True：让框架在跑这个历史版本时优先用 `ref_run_cmd`
            # （配置里写了的话）。这是「框架能力」的落点——框架自己知道
            # 「我现在跑的是一个参考版本」，而不是靠外面猜。
            r = infra.run_regression(cfg, mode=self.mode,
                                     tests=self.test_pattern,
                                     overrides=overrides,
                                     reference_mode=True,
                                     debug_mode=debug_mode)
            passed = int(r.get("passed") or 0)
            failed = int(r.get("failed") or 0)
            unknown = int(r.get("unknown") or 0)
            total = int(r.get("total") or 0)

            if r.get("status") == "FAIL" and r.get("error"):
                # 根本没跑起来（配置缺失 / EDA 缺失）—— 这是 inconclusive，不是 fail
                verdict, detail = INCONCLUSIVE, str(r["error"])[:200]
            elif total == 0:
                # 用例没被选中（改名了/过滤没命中）—— 同样不能当成 pass
                verdict, detail = INCONCLUSIVE, f"没有选中任何用例（pattern={self.test_pattern}）"
            elif failed > 0:
                verdict, detail = FAIL, f"{failed}/{total} 失败"
            elif unknown > 0 and passed == 0:
                verdict, detail = INCONCLUSIVE, f"{unknown}/{total} unknown（既非通过也非失败）"
            else:
                verdict, detail = PASS, f"{passed}/{total} 通过"

            res = RevisionResult(rev=rev, short=short, verdict=verdict, detail=detail,
                                 run_root=str(run_root), passed=passed, failed=failed,
                                 unknown=unknown, elapsed_s=round(time.time() - t0, 2))
        except Exception as e:
            res = RevisionResult(rev=rev, short=short, verdict=INCONCLUSIVE,
                                 detail=f"{type(e).__name__}: {str(e)[:200]}",
                                 run_root=str(run_root),
                                 elapsed_s=round(time.time() - t0, 2))
        finally:
            if wt is not None:
                self._drop_worktree(wt)

        self._log(f"{short} → {res.verdict}（{res.detail}，{res.elapsed_s}s）")
        self.results.append(res)
        if self.use_cache:
            try:
                from ..l4_memory.reference_finder_cache import get_reference_finder_cache
                get_reference_finder_cache().put(
                    str(self.repo), rev, self.test_pattern, self._env_digest,
                    res.verdict, res.detail, res.passed, res.failed, res.unknown,
                    res.run_root)
            except Exception as e:
                self._log(f"缓存写入失败（忽略）: {e}")
        return res

    # ═══════════════════════════════════════════════════════════
    # 二分搜索
    # ═══════════════════════════════════════════════════════════

    def find_first_bad(self, good: str, bad: str,
                       paths: List[str] = None) -> Dict[str, Any]:
        """在 `good..bad` 里找第一个失败的提交。

        前置条件：`good` 通过、`bad` 失败。不成立就直接报出来 —— 拿一个错误前提
        去二分，只会得到一条精确但无意义的结论。
        """
        t0 = time.time()
        revs = list_revisions(self.repo, good, bad, paths)
        self._log(f"{good[:12]}..{bad[:12]} 区间共 {len(revs)} 个提交"
                  + (f"（限定 paths={paths}）" if paths else ""))

        report: Dict[str, Any] = {
            "good": good, "bad": bad, "paths": paths or [],
            "candidate_count": len(revs),
            "reliable": True,
            "caveats": [],
        }

        if not revs:
            report.update({"culprit": None, "confidence": "none",
                           "reason": "区间内没有提交（good 可能不是 bad 的祖先）"})
            self._write_report(report, t0)
            return report

        # ── 校验前置条件：端点必须分别是 pass / fail ──
        g = self.run_at_revision(good)
        if g.verdict != PASS:
            report["reliable"] = False
            report["caveats"].append(
                f"good({good[:12]}) 的结论是 {g.verdict}（期望 pass）：{g.detail}")
        b = self.run_at_revision(bad)
        if b.verdict != FAIL:
            report["reliable"] = False
            report["caveats"].append(
                f"bad({bad[:12]}) 的结论是 {b.verdict}（期望 fail）：{b.detail}")
        if g.verdict != PASS or b.verdict != FAIL:
            report.update({
                "culprit": None, "confidence": "invalid",
                "reason": "端点不满足「good 通过 / bad 失败」，二分无意义。"
                          "常见原因：环境不一致、用例选择没命中、或区间选错了。",
            })
            self._write_report(report, t0)
            return report

        # ── 二分：不变量 pass(lo-1) / fail(hi)，收敛到第一个 fail ──
        lo, hi = 0, len(revs) - 1
        while lo < hi:
            mid = (lo + hi) // 2
            r = self.run_at_revision(revs[mid])
            if r.verdict == FAIL:
                hi = mid
            elif r.verdict == PASS:
                lo = mid + 1
            else:
                # inconclusive：既不能判它通过、也不能判它失败。
                # 为了能继续收敛，往「失败侧」缩，但**记下这个缺口并降级可靠性** ——
                # 静默当成 pass 或 fail 都会给出看似确定、实则可能错的结论。
                report.setdefault("inconclusive_revisions", []).append(
                    {"rev": revs[mid], "short": r.short, "detail": r.detail})
                report["reliable"] = False
                hi = mid

        # 引入点 = 第一个失败的提交；它前面那个（或 good）是最后一个好版本
        culprit = revs[lo]
        prev = revs[lo - 1] if lo > 0 else good
        report.update({
            "culprit": culprit,
            "culprit_short": _git(self.repo, "rev-parse", "--short", culprit, check=False),
            "last_good": prev,
            "last_good_short": _git(self.repo, "rev-parse", "--short", prev, check=False),
            "confidence": "high" if report["reliable"] else "degraded",
            "subject": _git(self.repo, "log", "-1", "--format=%s", culprit, check=False),
            "author": _git(self.repo, "log", "-1", "--format=%an <%ae>", culprit, check=False),
            "date": _git(self.repo, "log", "-1", "--format=%cI", culprit, check=False),
            "changed_files": _git(self.repo, "show", "--name-only", "--format=",
                                  culprit, check=False).split(),
        })
        if not report["reliable"]:
            report.setdefault("caveats", []).append(
                "区间内存在 inconclusive 版本，定位结果可能偏早，请复核下列版本")

        # ── 边界 Debug Run（ExecMan 流程的最后一步）──
        # 定位到引入点之后，在**两个边界版本**上用调试跑法各跑一次，产出可供
        # 对比的素材（波形、详细日志）。这一步只**产出素材**，不做差异分析 ——
        # ExecMan 的 Debug Engine 那层（自动对比给根因）没有实现，见
        # docs/design/reference_finder.md 的「已知限制」。
        if self.debug_at_boundary:
            report["boundary_debug"] = self._debug_boundaries(prev, culprit)

        self._write_report(report, t0)
        return report

    def _debug_boundaries(self, last_good: str, culprit: str) -> Dict[str, Any]:
        """在 last_good 与 culprit 上各跑一次 Debug Run，返回产物位置。

        两个版本用的是 `ref_debug_run_cmd`（配置里没写就退到 `debug_run_cmd`，
        再退到 `ref_run_cmd`/`run_cmd` —— 见 shell.py 的命令选择矩阵）。跑出来的
        波形/日志分别在各自的 run 目录下，人工或后续工具可据此对比。

        失败不抛：边界调试素材是**附加价值**，拿不到不该让已经得到的定位结论作废。
        """
        out: Dict[str, Any] = {}
        for label, rev in (("last_good", last_good), ("culprit", culprit)):
            try:
                self._log(f"边界 Debug Run: {label} {rev[:12]}")
                res = self.run_at_revision(rev, debug_mode=True)
                out[label] = {"rev": rev, "run_root": res.run_root,
                              "verdict": res.verdict, "detail": res.detail}
            except Exception as e:
                out[label] = {"rev": rev, "error": f"{type(e).__name__}: {str(e)[:200]}"}
        out["note"] = ("只产出调试素材（波形/详细日志），未做版本间差异分析 —— "
                       "ExecMan 的 Debug Engine 那层未实现")
        return out

    # ═══════════════════════════════════════════════════════════
    # 证据落盘
    # ═══════════════════════════════════════════════════════════

    def _write_report(self, report: Dict[str, Any], t0: float) -> None:
        """把结论 + 全部版本结果 + 环境快照写成可审计的落盘证据。

        结论本身是一条证据：「bug 在 k 与 k+1 之间引入」，依据是两个版本的回归
        结果**加上它们是在什么环境下跑的**。少了后半句，这条结论在换台机器上
        就不可复核了 —— 而这正是它区别于 `git bisect` 的地方。
        """
        report["elapsed_s"] = round(time.time() - t0, 1)
        report["results"] = [asdict(r) for r in self.results]
        report["env_snapshots"] = self.snapshots

        # 各版本环境是否一致 —— 不一致就不能把结果差异归因于代码
        snaps = [s for s in self.snapshots.values() if s]
        if len(snaps) > 1:
            base = snaps[0]
            mism = []
            for s in snaps[1:]:
                d = env_snapshot.diff(base, s)
                if d:
                    mism.append({"revision": s.get("extra", {}).get("revision", "?"),
                                 "differences": d})
            if mism:
                report["reliable"] = False
                report.setdefault("caveats", []).append(
                    "各版本的环境快照不一致 —— 结果差异不能只归因于代码")
                report["env_mismatches"] = mism

        out = self.work_root / "reference_finder_result.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                       encoding="utf-8")
        (self.work_root / "reference_finder_summary.md").write_text(
            _to_markdown(report), encoding="utf-8")
        self._log(f"结论已落盘: {out}")


def _to_markdown(r: Dict[str, Any]) -> str:
    """人读版结论。落一份 md 是因为签核场景里要能直接贴给人看。"""
    lines = ["# Reference Finder 结论", ""]
    if r.get("culprit"):
        lines += [
            f"- **引入提交**: `{r.get('culprit_short')}` {r.get('subject', '')}",
            f"- 作者: {r.get('author', '')}  ·  时间: {r.get('date', '')}",
            f"- **最后一个好版本**: `{r.get('last_good_short')}`",
            f"- 置信度: **{r.get('confidence')}**",
        ]
        if r.get("changed_files"):
            lines += ["", "## 该提交改动的文件", ""]
            lines += [f"- `{f}`" for f in r["changed_files"]]
    else:
        lines.append(f"- **未能定位**: {r.get('reason', '')}")

    lines += ["", f"- 区间: `{r.get('good','')[:12]}..{r.get('bad','')[:12]}`"
                  f"（{r.get('candidate_count')} 个候选）",
              f"- 总耗时: {r.get('elapsed_s')}s", ""]

    if r.get("caveats"):
        lines += ["## ⚠ 需要注意", ""] + [f"- {c}" for c in r["caveats"]] + [""]
    if r.get("inconclusive_revisions"):
        lines += ["## inconclusive 版本（需人工复核）", ""]
        lines += [f"- `{x['short']}` — {x['detail']}" for x in r["inconclusive_revisions"]]
        lines.append("")

    lines += ["## 各版本实测结果", "", "| 提交 | 结论 | 说明 | 耗时 |", "|---|---|---|---|"]
    for res in r.get("results", []):
        lines.append(f"| `{res['short']}` | {res['verdict']} | {res['detail']} | {res['elapsed_s']}s |")
    return "\n".join(lines) + "\n"
