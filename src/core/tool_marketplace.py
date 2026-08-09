"""
Tool Marketplace — 工具市场 (Phase 3)

提供:
  1. 工具索引与搜索
  2. 一键安装（从 Git URL / wheel / pip）
  3. 依赖解析
  4. 兼容性检查
  5. 评分与使用统计

用法:
  from src.core.tool_marketplace import ToolMarketplace
  market = ToolMarketplace()
  results = market.search("vcs")
  market.install("vcs_compile")
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

from src.core.tool_protocol import ITool, ToolManifest, ToolRisk, ToolStatus
from src.core.tool_hub import ToolHub

logger = structlog.get_logger()


@dataclass
class MarketplaceEntry:
    """工具市场条目"""
    name: str
    version: str
    description: str
    author: str = ""
    license: str = ""
    homepage: str = ""

    # 安装
    install_type: str = "pip"         # pip | git | wheel | url | directory
    install_source: str = ""          # pip package name / git URL / wheel URL
    install_args: str = ""            # e.g. "--index-url https://..."

    # 元信息
    tags: List[str] = field(default_factory=list)
    category: str = ""
    risk_level: str = "safe"
    downloads: int = 0
    rating: float = 0.0              # 0-5
    ratings_count: int = 0
    last_updated: str = ""
    python_requires: str = ">=3.10"

    # 依赖
    dependencies: List[str] = field(default_factory=list)

    # 兼容性
    verified_platforms: List[str] = field(default_factory=lambda: ["linux", "windows"])


class ToolMarketplace:
    """工具市场 —— 发现、安装、管理第三方工具"""

    def __init__(self, index_url: str = None):
        self._index_url = index_url or os.environ.get(
            "SIGNOFFAI_MARKETPLACE_URL",
            "https://market.signoffai.dev/tools/index.json"
        )
        self._cache_dir = Path.home() / ".signoffai" / "marketplace"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._installed: Dict[str, MarketplaceEntry] = {}
        self._hub = ToolHub.get_instance()

    # ═══════════════════════════════════════════════════════════
    # 远程索引
    # ═══════════════════════════════════════════════════════════

    async def fetch_index(self) -> List[MarketplaceEntry]:
        """从远程获取工具索引"""
        entries = []
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(self._index_url, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        for item in data.get("tools", []):
                            entries.append(MarketplaceEntry(**item))
        except ImportError:
            # Fallback: use urllib
            import urllib.request
            try:
                with urllib.request.urlopen(self._index_url, timeout=10) as resp:
                    data = json.loads(resp.read())
                    for item in data.get("tools", []):
                        entries.append(MarketplaceEntry(**item))
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Failed to fetch marketplace index: {e}")

        # Cache locally
        if entries:
            cache_file = self._cache_dir / "index.json"
            cache_file.write_text(json.dumps(
                [self._entry_to_dict(e) for e in entries],
                indent=2, ensure_ascii=False,
            ), encoding="utf-8")

        return entries

    def load_local_index(self) -> List[MarketplaceEntry]:
        """加载本地缓存的市场索引"""
        cache_file = self._cache_dir / "index.json"
        if not cache_file.exists():
            return self._build_local_index()

        entries = []
        try:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            for item in data:
                entries.append(MarketplaceEntry(**item))
        except Exception:
            return self._build_local_index()
        return entries

    def _build_local_index(self) -> List[MarketplaceEntry]:
        """从已注册的工具构建本地索引"""
        entries = []
        for name, manifest in ToolHub.get_instance()._manifests.items():
            entries.append(MarketplaceEntry(
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                author=manifest.author,
                tags=manifest.tags,
                category=manifest.category,
                risk_level=manifest.risk_level.value,
                install_type="builtin",
                install_source="",
                python_requires=manifest.requires_python,
                dependencies=manifest.requires_packages,
            ))
        return entries

    # ═══════════════════════════════════════════════════════════
    # 搜索
    # ═══════════════════════════════════════════════════════════

    def search(self, query: str, category: str = None,
               risk_level: str = None, tags: List[str] = None) -> List[MarketplaceEntry]:
        """搜索工具"""
        entries = self.load_local_index()
        results = []
        q = query.lower()

        for e in entries:
            if q and q not in e.name.lower() and q not in e.description.lower():
                continue
            if category and e.category != category:
                continue
            if risk_level and e.risk_level != risk_level:
                continue
            if tags and not set(tags).intersection(e.tags):
                continue
            results.append(e)

        return results

    def get(self, name: str) -> Optional[MarketplaceEntry]:
        """获取工具详情"""
        for e in self.load_local_index():
            if e.name == name:
                return e
        return None

    def list_categories(self) -> List[str]:
        """列出所有分类"""
        cats = set()
        for e in self.load_local_index():
            if e.category:
                cats.add(e.category)
        return sorted(cats)

    def list_popular(self, limit: int = 20) -> List[MarketplaceEntry]:
        """热门工具排行"""
        entries = self.load_local_index()
        entries.sort(key=lambda e: (e.downloads, e.rating), reverse=True)
        return entries[:limit]

    # ═══════════════════════════════════════════════════════════
    # 安装
    # ═══════════════════════════════════════════════════════════

    async def install(self, name: str, version: str = None,
                      upgrade: bool = False, force: bool = False) -> Tuple[bool, str]:
        """安装工具

        Returns:
          (success, message)
        """
        # 检查是否已安装
        if name in self._installed and not upgrade and not force:
            installed = self._installed[name]
            return True, f"Already installed: {name} v{installed.version}"

        # 查找工具
        entry = self.get(name)
        if not entry:
            # 尝试从远程获取
            remote_entries = await self.fetch_index()
            for e in remote_entries:
                if e.name == name:
                    entry = e
                    break

        if not entry:
            return False, f"Tool '{name}' not found in marketplace"

        # 检查平台兼容性
        platform = sys.platform
        if platform.startswith("linux"):
            plat = "linux"
        elif platform.startswith("win"):
            plat = "windows"
        elif platform.startswith("darwin"):
            plat = "macos"
        else:
            plat = platform

        if plat not in entry.verified_platforms:
            return False, f"Tool '{name}' is not verified for platform '{plat}'. "
            f"Verified: {entry.verified_platforms}"

        # 安装
        try:
            if entry.install_type == "builtin":
                return True, f"Built-in tool '{name}' is already available"

            elif entry.install_type == "pip":
                pkg = entry.install_source or name
                cmd = [sys.executable, "-m", "pip", "install", pkg]
                if version:
                    cmd[-1] = f"{pkg}=={version}"
                if upgrade:
                    cmd.insert(4, "--upgrade")
                if entry.install_args:
                    cmd.extend(entry.install_args.split())
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                if result.returncode == 0:
                    self._installed[name] = entry
                    self._save_installed()
                    return True, f"Installed {name} v{entry.version}"
                return False, f"pip install failed: {result.stderr[:500]}"

            elif entry.install_type == "git":
                target_dir = self._cache_dir / "repos" / name
                target_dir.parent.mkdir(parents=True, exist_ok=True)
                if target_dir.exists() and upgrade:
                    subprocess.run(["git", "-C", str(target_dir), "pull"],
                                   capture_output=True, timeout=30)
                else:
                    subprocess.run(["git", "clone", entry.install_source, str(target_dir)],
                                   capture_output=True, timeout=120)
                # pip install from local
                subprocess.run([sys.executable, "-m", "pip", "install", str(target_dir)],
                               capture_output=True, timeout=60)
                self._installed[name] = entry
                self._save_installed()
                return True, f"Installed {name} from git"

            elif entry.install_type == "directory":
                cmd = [sys.executable, "-m", "pip", "install", entry.install_source]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    self._installed[name] = entry
                    self._save_installed()
                    return True, f"Installed {name} from {entry.install_source}"
                return False, f"Install failed: {result.stderr[:500]}"

            else:
                return False, f"Unknown install type: {entry.install_type}"

        except subprocess.TimeoutExpired:
            return False, "Installation timed out"
        except Exception as e:
            return False, str(e)[:500]

    def uninstall(self, name: str) -> Tuple[bool, str]:
        """卸载工具"""
        if name in self._installed:
            entry = self._installed[name]
            if entry.install_type == "builtin":
                return False, "Cannot uninstall built-in tools"
            # pip uninstall
            try:
                pkg = entry.install_source or name
                subprocess.run([sys.executable, "-m", "pip", "uninstall", "-y", pkg],
                               capture_output=True, timeout=30)
            except Exception:
                pass
            del self._installed[name]
            self._save_installed()
            # Also unregister from hub
            ToolHub.get_instance().unregister(name)
            return True, f"Uninstalled {name}"
        return False, f"Tool '{name}' is not installed"

    def check_updates(self) -> List[Tuple[str, str, str]]:
        """检查已安装工具的更新。返回 [(name, current_version, latest_version)]"""
        updates = []
        for name, entry in self._installed.items():
            latest = self.get(name)
            if latest and latest.version != entry.version:
                updates.append((name, entry.version, latest.version))
        return updates

    # ═══════════════════════════════════════════════════════════
    # 本地状态
    # ═══════════════════════════════════════════════════════════

    @property
    def installed_count(self) -> int:
        return len(self._installed)

    def list_installed(self) -> List[MarketplaceEntry]:
        return list(self._installed.values())

    def _save_installed(self):
        file = self._cache_dir / "installed.json"
        file.write_text(json.dumps(
            {name: self._entry_to_dict(e) for name, e in self._installed.items()},
            indent=2, ensure_ascii=False,
        ), encoding="utf-8")

    def _load_installed(self):
        file = self._cache_dir / "installed.json"
        if file.exists():
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                self._installed = {k: MarketplaceEntry(**v) for k, v in data.items()}
            except Exception:
                pass

    @staticmethod
    def _entry_to_dict(e: MarketplaceEntry) -> dict:
        return {
            "name": e.name, "version": e.version, "description": e.description,
            "author": e.author, "tags": e.tags, "category": e.category,
            "risk_level": e.risk_level, "install_type": e.install_type,
            "install_source": e.install_source, "downloads": e.downloads,
            "rating": e.rating, "python_requires": e.python_requires,
            "dependencies": e.dependencies,
        }
