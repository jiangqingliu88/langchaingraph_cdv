"""
依赖注入容器 — 统一管理各层依赖

替代全局 get_*() 单例，让依赖关系可测试、可替换。
用法:
    from src.core.container import container
    container.signoff_service().approve(...)
    container.doc_service().update(...)
"""
from __future__ import annotations
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


class AppContainer:
    """应用级 IoC 容器"""

    def __init__(self):
        self._factories: dict[str, Callable[[], Any]] = {}
        self._singletons: dict[str, Any] = {}
        self._instances: dict[str, Any] = {}

    def register(self, name: str, factory: Callable[[], Any], singleton: bool = True):
        self._factories[name] = factory
        if singleton:
            self._singletons[name] = None

    def resolve(self, name: str) -> Any:
        if name not in self._factories:
            raise KeyError(f"未注册的依赖: {name}。可用: {list(self._factories.keys())}")
        # 检查是否有 override 的实例
        if name in self._instances:
            return self._instances[name]
        if name in self._singletons:
            if self._singletons[name] is None:
                self._singletons[name] = self._factories[name]()
            return self._singletons[name]
        return self._factories[name]()

    def override(self, name: str, instance: Any):
        """注入依赖替换（用于测试或运行时覆盖）"""
        self._instances[name] = instance
        if name in self._singletons:
            self._singletons[name] = None

    def reset(self):
        """重置所有单例（测试后清理）"""
        for key in self._singletons:
            self._singletons[key] = None
        self._instances.clear()

    # ── 便捷访问方法 ──

    def signoff_service(self):
        return self.resolve("signoff_service")

    def doc_service(self):
        return self.resolve("doc_service")

    def pipeline_service(self):
        return self.resolve("pipeline_service")

    def repository(self):
        return self.resolve("repository")

    def auth(self):
        return self.resolve("auth")

    def event_bus(self):
        return self.resolve("event_bus")

    def rules_engine(self):
        return self.resolve("rules_engine")

    def trigger_service(self):
        return self.resolve("trigger_service")


# ── 全局容器初始化 ──

def bootstrap_container() -> AppContainer:
    """启动时初始化容器 — 注册所有组件"""
    c = AppContainer()

    # Infrastructure
    c.register("event_bus", _lazy(lambda: _get_event_bus()))
    c.register("auth", _lazy(lambda: _get_auth()))

    # Repository (data access only, no business logic)
    c.register("repository", _lazy(lambda: _get_repository()))

    # Rules engine
    c.register("rules_engine", _lazy(lambda: _get_rules_engine()))

    # Trigger service
    c.register("trigger_service", _lazy(lambda: _get_trigger_service()))

    # Services (business logic)
    from src.core.services import SignoffService, DocService, PipelineService
    c.register("signoff_service", lambda: SignoffService())
    c.register("doc_service", lambda: DocService())
    c.register("pipeline_service", lambda: PipelineService())

    return c


def _lazy(factory: Callable) -> Callable:
    """延迟导入包装器，避免循环依赖"""
    def wrapper():
        return factory()
    return wrapper


def _get_event_bus():
    from src.infra.event_bus import get_event_bus
    return get_event_bus()


def _get_auth():
    from src.core.auth import AuthManager
    return AuthManager()


def _get_repository():
    """返回 repository 模块的代理（保持向后兼容）"""
    import src.database.repository as repo
    return repo


def _get_rules_engine():
    from src.core.rules_engine import RulesEngine
    return RulesEngine()


def _get_trigger_service():
    from src.infra.workflow_triggers import get_trigger_service
    return get_trigger_service()


# ── 全局容器实例 ──
container: AppContainer = bootstrap_container()
