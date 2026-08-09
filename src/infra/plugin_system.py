"""
可扩展插件系统 — 工具链适配器 + 验证框架适配器 + 扩展点注册

设计原则:
  - 核心代码不硬编码工具链逻辑
  - 通过适配器接口接入不同 EDA 工具、验证框架、客户环境
  - 插件通过注册表发现和加载
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


# ═══════════════════════════════════════════════════════════
# 扩展点枚举 — 系统中可被插件化的能力点
# ═══════════════════════════════════════════════════════════

class ExtensionPoint(str, Enum):
    """平台可扩展的能力点"""
    # 工具链
    EDA_SIMULATOR = "eda_simulator"             # QuestaSim / VCS / Xcelium / Riviera
    EDA_SYNTHESIS = "eda_synthesis"             # Design Compiler / Genus
    EDA_PLACE_ROUTE = "eda_place_route"         # Innovus / ICC2
    EDA_TIMING = "eda_timing"                   # PrimeTime / Tempus
    EDA_POWER = "eda_power"                     # Voltus / PrimePower
    EDA_FORMAL = "eda_formal"                   # JasperGold / VC Formal

    # 验证框架
    VERIF_METHODOLOGY = "verif_methodology"     # UVM / OVM / VMM / cocotb
    VERIF_LANGUAGE = "verif_language"           # SystemVerilog / Python / C++ / Specman

    # 外部集成
    CI_CD = "ci_cd"                             # Jenkins / GitLab CI / GitHub Actions
    VCS_HOST = "vcs_host"                       # Git / SVN / Perforce
    ISSUE_TRACKER = "issue_tracker"             # Jira / Redmine / 飞书
    NOTIFICATION = "notification"               # 企业微信 / 钉钉 / Slack / Email

    # 报告
    REPORT_FORMAT = "report_format"             # HTML / PDF / JSON / Markdown
    DOC_GENERATOR = "doc_generator"             # Sphinx / Doxygen / 自定义


# ═══════════════════════════════════════════════════════════
# 适配器接口
# ═══════════════════════════════════════════════════════════

class PluginAdapter(ABC):
    """所有插件的基类"""

    @property
    @abstractmethod
    def plugin_id(self) -> str:
        """唯一插件标识"""
        ...

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """可读名称"""
        ...

    @property
    @abstractmethod
    def extension_point(self) -> ExtensionPoint:
        """所属扩展点"""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> bool:
        """初始化插件"""
        ...

    @abstractmethod
    async def execute(self, action: str, context: dict) -> dict:
        """执行插件动作"""
        ...

    @abstractmethod
    async def shutdown(self):
        """清理资源"""
        ...


class EdaSimulatorAdapter(PluginAdapter):
    """EDA 仿真器适配器接口"""
    extension_point = ExtensionPoint.EDA_SIMULATOR

    @abstractmethod
    async def compile(self, filelist: list[str], top_module: str, options: dict) -> dict:
        """编译 RTL + UVM"""
        ...

    @abstractmethod
    async def simulate(self, test_name: str, options: dict) -> dict:
        """运行仿真"""
        ...

    @abstractmethod
    async def get_coverage(self, coverage_type: str) -> dict:
        """获取覆盖率数据"""
        ...

    @abstractmethod
    async def get_waveform(self, test_name: str, signal: str) -> bytes:
        """获取波形数据"""
        ...


class EdaSynthesisAdapter(PluginAdapter):
    """综合工具适配器"""
    extension_point = ExtensionPoint.EDA_SYNTHESIS

    @abstractmethod
    async def synthesize(self, rtl_files: list[str], constraints: str, options: dict) -> dict:
        """运行综合"""
        ...

    @abstractmethod
    async def get_area_report(self) -> dict:
        """获取面积报告"""
        ...

    @abstractmethod
    async def get_timing_report(self) -> dict:
        """获取时序报告"""
        ...


class NotificationAdapter(PluginAdapter):
    """通知适配器接口"""
    extension_point = ExtensionPoint.NOTIFICATION

    @abstractmethod
    async def send(self, recipients: list[str], title: str, content: str, level: str = "info") -> bool:
        """发送通知"""
        ...


# ═══════════════════════════════════════════════════════════
# 插件注册表
# ═══════════════════════════════════════════════════════════

class PluginRegistry:
    """插件注册表 — 管理所有已加载的插件"""

    def __init__(self):
        self._plugins: Dict[str, PluginAdapter] = {}
        self._by_extension: Dict[ExtensionPoint, List[str]] = {}

    def register(self, plugin: PluginAdapter):
        """注册插件"""
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"Plugin already registered: {plugin.plugin_id}")
        self._plugins[plugin.plugin_id] = plugin
        ext = plugin.extension_point
        self._by_extension.setdefault(ext, []).append(plugin.plugin_id)

    def get(self, plugin_id: str) -> Optional[PluginAdapter]:
        return self._plugins.get(plugin_id)

    def get_by_extension(self, point: ExtensionPoint) -> List[PluginAdapter]:
        """获取某个扩展点的所有插件"""
        return [self._plugins[pid] for pid in self._by_extension.get(point, [])]

    def get_default(self, point: ExtensionPoint) -> Optional[PluginAdapter]:
        """获取扩展点的默认插件（第一个注册的）"""
        plugins = self.get_by_extension(point)
        return plugins[0] if plugins else None

    def list_extensions(self) -> dict:
        """列出所有扩展点及其已注册插件"""
        return {
            ext.value: [self._plugins[pid].plugin_name for pid in pids]
            for ext, pids in self._by_extension.items()
        }

    def has_extension(self, point: ExtensionPoint) -> bool:
        return point in self._by_extension and len(self._by_extension[point]) > 0


# ── 全局实例 ──
_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


# ═══════════════════════════════════════════════════════════
# 内置适配器实现
# ═══════════════════════════════════════════════════════════

class QuestaSimAdapter(EdaSimulatorAdapter):
    """QuestaSim 仿真器适配器"""
    plugin_id = "mentor_questasim"
    plugin_name = "Mentor Graphics QuestaSim"
    extension_point = ExtensionPoint.EDA_SIMULATOR

    async def initialize(self, config: dict) -> bool:
        self.questa_root = config.get("questa_root", "")
        self.license_file = config.get("license_file", "")
        return True

    async def execute(self, action: str, context: dict) -> dict:
        actions = {
            "compile": self.compile,
            "simulate": self.simulate,
            "get_coverage": self.get_coverage,
        }
        handler = actions.get(action)
        if not handler:
            return {"success": False, "error": f"Unknown action: {action}"}
        return await handler(**context)

    async def compile(self, filelist: list[str], top_module: str, options: dict = None) -> dict:
        return {"success": True, "tool": "questa", "action": "compile",
                "top_module": top_module, "file_count": len(filelist)}

    async def simulate(self, test_name: str, options: dict = None) -> dict:
        return {"success": True, "tool": "questa", "action": "simulate", "test": test_name}

    async def get_coverage(self, coverage_type: str = "code") -> dict:
        return {"tool": "questa", "coverage_type": coverage_type}

    async def get_waveform(self, test_name: str, signal: str = "") -> bytes:
        return b""

    async def shutdown(self):
        pass


class BuiltinNotifier(NotificationAdapter):
    """内置通知适配器 — 记录到审计日志"""
    plugin_id = "builtin_log"
    plugin_name = "内置日志通知"
    extension_point = ExtensionPoint.NOTIFICATION

    async def initialize(self, config: dict) -> bool:
        return True

    async def execute(self, action: str, context: dict) -> dict:
        return await self.send(**context)

    async def send(self, recipients: list[str], title: str, content: str, level: str = "info") -> bool:
        try:
            from src.database.repository import add_audit_log
            await add_audit_log(0, "system", "notification", ",".join(recipients),
                                f"[{level}] {title}: {content[:100]}",
                                resource_type="notification")
            return True
        except Exception:
            return False

    async def shutdown(self):
        pass


# ═══════════════════════════════════════════════════════════
# 自动发现和加载
# ═══════════════════════════════════════════════════════════

async def bootstrap_plugins():
    """启动时加载内置插件"""
    registry = get_plugin_registry()

    # 仿真器
    questa = QuestaSimAdapter()
    await questa.initialize({})
    registry.register(questa)

    # 通知
    notifier = BuiltinNotifier()
    await notifier.initialize({})
    registry.register(notifier)

    return registry
