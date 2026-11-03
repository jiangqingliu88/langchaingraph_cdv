"""种子多样性 —— 同一批用例在不同 seed 下覆盖分布是否真的变化。

从采集文件拆出：它只读回归库、调 vcover merge/report，与主采集链路解耦。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from config.settings import questa_exe

from .cvg_parse import _parse_cvg_bin_hits

def analyze_seed_diversity(od: Path, max_seeds: int = 5,
                           max_stores_per_seed: int = 400) -> dict:
    """**种子多样性实测** —— 不同 seed 的命中 bin 集合到底一不一样。

    ## 为什么要做

    "换种子 → 换激励 → 换覆盖率"是随机验证的基本假设，但此前没有任何
    证据：`seed_diversity` 一直是 `None`。`None` 不是"中性"，它让
    "可复现"退化成"同一颗种子可复现"，而不是"分布可复现"。

    ## 怎么算（不重跑仿真）

    回归的每个用例目录名里带 seed（`*_seed_<n>`），每个用例都有
    `cov/*/questa.db`。按 seed 分组合并成一份 ucdb，再 `vcover report -cvg
    -details` 取逐 bin 命中数。比较各 seed 的命中集合：

      · `stable_bins`   所有 seed 都命中的 bin（种子无关）
      · `variable_bins` 至少一个 seed 新打中的 bin（种子敏感）
      · `new_bins_per_seed` 每个 seed 相对前序 seed 的新增

    这是**实测**，不是"跑了几颗种子"的计数。代价是每颗种子一次 merge；
    默认最多 5 颗（超过的**记账不静默丢**）。

    ## 失败时

    仍然写一份 JSON（`verdict: UNAVAILABLE/INSUFFICIENT` + 原因），
    绝不返回 `None` —— 签核要能区分"没验证"与"验证过且结果如何"。
    """
    od = Path(od).resolve()
    reg_root = od / "regression_run"
    stores = sorted(reg_root.rglob("cov/*/questa.db")) if reg_root.is_dir() else []
    out_path = od / "coverage" / "seed_diversity.json"

    def _finish(payload: dict) -> dict:
        payload.setdefault("schema", "seed_diversity_v1")
        payload.setdefault("analyzed", False)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        except OSError as e:
            payload.setdefault("notes", []).append(f"落盘失败: {e}")
        return payload

    if not stores:
        return _finish({"verdict": "UNAVAILABLE", "reason": "没有回归覆盖率库",
                        "seeds": []})

    # 缓存：结果比所有 store 都新就直接用
    try:
        newest = max(p.stat().st_mtime for p in stores)
        if out_path.is_file() and out_path.stat().st_mtime >= newest:
            cached = json.loads(out_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(cached, dict):
                cached["cached"] = True
                return cached
    except (OSError, ValueError):
        pass

    # 按 seed 分组（目录名里找 `_seed_<n>` / `seed<n>`）
    groups: dict = {}
    for db in stores:
        rel = db.relative_to(od).as_posix()
        m = re.search(r"(?:^|[_-])seed[_-]?(\d+)", rel, re.IGNORECASE)
        seed = int(m.group(1)) if m else None
        groups.setdefault(seed, []).append(db)

    seeds = sorted(s for s in groups if s is not None)
    notes = []
    if len(seeds) < 2:
        return _finish({
            "verdict": "INSUFFICIENT",
            "reason": f"只找到 {len(seeds)} 个可区分 seed 的用例库"
                      f"（共 {len(stores)} 个 store）—— 需要 ≥2 颗种子才能比对",
            "seeds": seeds,
            "stores": len(stores),
            "notes": notes,
        })
    if len(seeds) > max_seeds:
        notes.append(f"只分析前 {max_seeds} 颗种子（共 {len(seeds)} 颗）："
                     f"{seeds[:max_seeds]}，其余 {len(seeds) - max_seeds} 颗未分析")
        seeds = seeds[:max_seeds]

    vcover = questa_exe("vcover.exe")
    if not os.path.exists(vcover):
        return _finish({"verdict": "UNAVAILABLE",
                        "reason": f"vcover not found: {vcover}",
                        "seeds": seeds, "stores": len(stores)})

    per_seed: dict = {}
    errors: list = []
    all_hit_sets: dict = {}
    for seed in seeds:
        subset = groups[seed][:max_stores_per_seed]
        if len(groups[seed]) > max_stores_per_seed:
            notes.append(f"seed {seed}: 只合并前 {max_stores_per_seed} 个 store"
                         f"（共 {len(groups[seed])} 个）")
        out = od / "sim" / "coverage" / f"seed_{seed}_merged.ucdb"
        out.parent.mkdir(parents=True, exist_ok=True)
        for junk in (out, Path(str(out) + "._lock"), Path(str(out) + ".questatmp")):
            try:
                junk.unlink()
            except OSError:
                pass
        specs = []
        for db in subset:
            store = db.parent
            data = sorted(store.glob("*.data"))
            stem = (data[0].stem if len(data) == 1
                    else (store.name if not data else
                          max(data, key=lambda x: x.stat().st_mtime).stem))
            null_test = (not stem) or stem in ("(null)", "null")
            try:
                rel = store.relative_to(od).as_posix()
            except ValueError:
                continue
            specs.append(rel if null_test else f"{rel}:{stem}")
        if not specs:
            continue
        cmdfile = od / "sim" / "coverage" / f"seed_{seed}_inputs.txt"
        cmdfile.write_text("\n".join(specs) + "\n", encoding="utf-8")
        proc = subprocess.run([vcover, "merge", "-inputs", str(cmdfile), str(out)],
                              cwd=str(od), capture_output=True, text=True,
                              errors="replace", timeout=900)
        if proc.returncode != 0 or not out.is_file():
            errors.append(f"seed {seed}: "
                          f"{((proc.stdout or '') + (proc.stderr or '')).strip()[-200:]}")
            continue
        rep = subprocess.run([vcover, "report", "-cvg", "-details", str(out)],
                             capture_output=True, text=True, errors="replace",
                             timeout=300)
        hits = _parse_cvg_bin_hits(rep.stdout or "")
        hit_set = {f"{cg}.{cp}.{b}"
                   for cg, cps in hits.items()
                   for cp, bins in cps.items()
                   for b, n in bins.items() if n > 0}
        all_hit_sets[seed] = hit_set
        per_seed[str(seed)] = {
            "stores": len(specs),
            "hit_bins": len(hit_set),
            "ucdb": str(out),
        }

    if len(all_hit_sets) < 2:
        return _finish({"verdict": "UNAVAILABLE",
                        "reason": "可用的 seed 合并结果不足 2 份",
                        "seeds": seeds, "per_seed": per_seed,
                        "errors": errors, "notes": notes})

    sets = list(all_hit_sets.values())
    stable = set.intersection(*sets)
    union = set.union(*sets)
    variable = union - stable
    # 每个 seed 相对"前序并集"的新增
    running: set = set()
    new_per_seed: dict = {}
    for seed in sorted(all_hit_sets):
        new_per_seed[str(seed)] = len(all_hit_sets[seed] - running)
        running |= all_hit_sets[seed]
    for seed, info in per_seed.items():
        info["new_bins"] = new_per_seed.get(seed, 0)

    verdict = "DIVERSE" if variable else "IDENTICAL"
    if verdict == "IDENTICAL":
        notes.append("所有种子的命中 bin 集合完全一致 —— 种子没有改变覆盖分布，"
                     "需要检查随机化是否真的生效（约束是否把所有取值钉死了）")
    return _finish({
        "verdict": verdict,
        "seeds": sorted(all_hit_sets),
        "stores": len(stores),
        "per_seed": per_seed,
        "stable_bins": len(stable),
        "variable_bins": len(variable),
        "union_bins": len(union),
        "new_bins_per_seed": new_per_seed,
        "notes": notes,
        "errors": errors,
        "analyzed": True,
    })
