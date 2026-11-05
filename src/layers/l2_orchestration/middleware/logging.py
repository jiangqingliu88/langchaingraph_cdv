"""
日志中间件 - 使用装饰器模式
"""
import structlog
import sys
from functools import wraps
from typing import Callable, Any
import time
import asyncio

# 配置structlog
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    # 显式写 stderr（structlog 25.x 的 WriteLoggerFactory() 默认 sys.stdout，会污染 --json 输出）
    logger_factory=structlog.WriteLoggerFactory(sys.stderr),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

def log_execution(func: Callable) -> Callable:
    """记录函数执行的装饰器"""
    
    @wraps(func)
    async def async_wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.info(f"开始执行", function=func_name)
        start_time = time.time()
        
        try:
            result = await func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"执行完成", function=func_name, elapsed=f"{elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"执行失败", function=func_name, error=str(e), elapsed=f"{elapsed:.2f}s")
            raise
    
    @wraps(func)
    def sync_wrapper(*args, **kwargs):
        func_name = func.__name__
        logger.info(f"开始执行", function=func_name)
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            elapsed = time.time() - start_time
            logger.info(f"执行完成", function=func_name, elapsed=f"{elapsed:.2f}s")
            return result
        except Exception as e:
            elapsed = time.time() - start_time
            logger.error(f"执行失败", function=func_name, error=str(e), elapsed=f"{elapsed:.2f}s")
            raise
    
    if asyncio.iscoroutinefunction(func):
        return async_wrapper
    return sync_wrapper

class LoggingMiddleware:
    """日志中间件"""
    
    @staticmethod
    async def log_agent_interaction(agent_id: str, message: str, level: str = "info"):
        """记录Agent交互"""
        log_func = getattr(logger, level, logger.info)
        log_func(f"Agent交互", agent_id=agent_id, message=message)