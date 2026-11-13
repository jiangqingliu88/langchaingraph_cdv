"""环境快照 —— 「可复现」的地基。

为什么需要它

    「同一份配置跑出同一个结果」这句话要成立，前提是**除了被测代码，别的都没变**。
    但本仓的 EDA 路径 / UVM 版本 / 工具链位置散落在十几处，且写死过
    `f:/questasim64_2024.1`、`win64`、`uvm-1.2`、`gcc-8.1.0`。没有环境快照时：

      · 两次 run 结果不同，无法判断是**代码变了**还是**环境变了**；
      · Reference Finder 会把环境差异**误判成 bug 引入点**——看起来在工作，
        结论却是错的。

    所以快照不只是「记一笔」，它是判定「这次复现是否可信」的依据：
    两次 run 的 `digest` 一致，结果差异才归因于代码。

记什么

    · EDA：后端名 + 安装根 + 版本（能拿到就拿）
    · UVM：版本与源码/DPI 路径
    · 关键环境变量（**白名单**，不把整个 os.environ 写进证据）
    · 运行时：Python 版本、平台
    · 代码：git HEAD + 是否有未提交改动
    · 配置：yaml 文件的 SHA256

    不记：密钥、token、整个 PATH（只记 PATH 的哈希，够比对、不泄路径细节）。
"""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

#: 进快照的环境变量白名单。**只收工具链相关**——把整个 os.environ 写进证据
#: 会把 API key / token 一起落到磁盘上，那是泄密，不是审计。
_ENV_WHITELIST = (
    "QUESTA_HOME", "VCS_HOME", "UVM_HOME", "UVM_VERSION",
    "MTI_HOME", "MODEL_TECH", "LM_LICENSE_FILE", "SNPSLMD_LICENSE_FILE",
    "CDC_FSDB_HOME", "VERDI_HOME", "VERILATOR_ROOT",
)


def _sha256_file(path: Path) -> str:
    try:
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    return ""


def _git(repo: str | Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(repo), *args],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def _eda_home(kind: str) -> str:
    """EDA 安装根。优先走 config.settings 的**唯一来源**，避免再造一份硬编码。"""
    try:
        from config.settings import questa_home
        if kind == "questa":
            return questa_home() or ""
    except Exception:
        pass
    return os.environ.get(f"{kind.upper()}_HOME", "") or ""


def _uvm_src(questa: str) -> Dict[str, str]:
    """UVM 源码 / DPI 路径。

    版本从环境变量读，默认 uvm-1.2（本仓多处写死过这个默认值，在这里集中
    暴露出来，至少让快照能记录「这次用的是哪个版本」）。
    """
    ver = os.environ.get("UVM_VERSION", "uvm-1.2")
    out = {"uvm_version": ver, "uvm_src": "", "uvm_dpi": ""}
    if questa:
        root = Path(questa)
        # questa 根可能带 win64 后缀，去掉再拼
        if root.name in ("win64", "linux64", "bin"):
            root = root.parent
        src = root / "verilog_src" / ver / "src"
        dpi = root / ver / ("win64" if os.name == "nt" else "linux64") / "uvm_dpi"
        out["uvm_src"] = str(src) if src.exists() else ""
        out["uvm_dpi"] = str(dpi) if dpi.exists() else ""
    return out


def capture(repo_root: str | Path = ".", config_path: str | Path = None,
            backend: str = "questa", extra: Dict[str, Any] = None) -> Dict[str, Any]:
    """拍一张环境快照。返回的 dict 可直接 JSON 落盘。"""
    repo = Path(repo_root)

    eda_home = _eda_home(backend)
    snap: Dict[str, Any] = {
        # ── EDA ──
        "eda_backend": backend,
        "eda_home": eda_home,
        "eda_home_exists": bool(eda_home) and Path(eda_home).exists(),
        # 版本号：QuestaSim 的根目录名里就带版本（如 questasim64_2024.1），
        # 直接取目录名，不额外跑子进程（启动 EDA 只为问版本太贵，且可能要 license）。
        "eda_version_guess": Path(eda_home).name if eda_home else "",

        # ── UVM ──
        **_uvm_src(eda_home),

        # ── 关键环境变量（白名单）──
        "env": {k: os.environ[k] for k in _ENV_WHITELIST if k in os.environ},
        "path_sha256": hashlib.sha256(
            os.environ.get("PATH", "").encode()).hexdigest()[:16],

        # ── 运行时 ──
        "python": sys.version.split()[0],
        "python_exe": sys.executable,
        "platform": platform.platform(),

        # ── 代码 ──
        "git_head": _git(repo, "rev-parse", "HEAD"),
        "git_dirty": bool(_git(repo, "status", "--porcelain")),
        "git_describe": _git(repo, "describe", "--tags", "--always"),

        # ── 配置 ──
        "config_path": str(config_path) if config_path else "",
        "config_sha256": _sha256_file(Path(config_path)) if config_path else "",
    }
    if extra:
        snap["extra"] = extra

    # 摘要：只把**影响复现性**的字段纳入，这样「两次 run 的 digest 是否相同」
    # 才等价于「环境是否一致」。python_exe 路径、config_path 这类不进摘要
    # （换台机器路径必然不同，但那不代表环境变了）。
    digest_src = {
        "eda_backend": snap["eda_backend"],
        "eda_version_guess": snap["eda_version_guess"],
        "uvm_version": snap["uvm_version"],
        "env": snap["env"],
        "python": snap["python"].rsplit(".", 1)[0],   # 只比 major.minor
        "platform": snap["platform"],
        "config_sha256": snap["config_sha256"],
    }
    import json as _json
    snap["digest"] = hashlib.sha256(
        _json.dumps(digest_src, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()[:32]
    return snap


def diff(a: Dict[str, Any], b: Dict[str, Any]) -> List[str]:
    """比对两张快照，返回**人可读的差异列表**。空列表 = 环境一致。

    这是判定「两次结果不同能不能归因于代码」的依据：diff 非空时，
    结果差异就不能只归因于代码变更。
    """
    issues: List[str] = []
    if a.get("digest") == b.get("digest"):
        return issues
    for key in ("eda_backend", "eda_version_guess", "uvm_version", "python", "platform"):
        if a.get(key) != b.get(key):
            issues.append(f"{key}: {a.get(key)!r} → {b.get(key)!r}")
    ea, eb = a.get("env") or {}, b.get("env") or {}
    for k in sorted(set(ea) | set(eb)):
        if ea.get(k) != eb.get(k):
            issues.append(f"env.{k}: {ea.get(k)!r} → {eb.get(k)!r}")
    if a.get("config_sha256") != b.get("config_sha256"):
        issues.append("config_sha256 变了（配置本身不一致，结果不可比）")
    if a.get("path_sha256") != b.get("path_sha256"):
        issues.append("PATH 变了（工具链可能被换过）")
    return issues or ["digest 不一致但未定位到具体字段（见快照原文）"]


def capture_optional(*args, **kwargs) -> Optional[Dict[str, Any]]:
    """拍快照，失败也不抛 —— 快照缺失是问题，但不该打断回归本身。"""
    try:
        return capture(*args, **kwargs)
    except Exception as e:                                    # pragma: no cover
        print(f"[warn] 环境快照捕获失败: {e}")
        return None
