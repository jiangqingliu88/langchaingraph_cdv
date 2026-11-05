"""
重试中间件 - 使用装饰器模式 + 策略模式
"""
import asyncio
import time
from functools import wraps
from typing import Type, Tuple, Callable, Any
import structlog

logger = structlog.get_logger()

class RetryStrategy:
    """重试策略"""
    
    def __init__(
        self,
        max_retries: int = 3,
        delay: float = 1.0,
        backoff_factor: float = 2.0,
        exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff_factor = backoff_factor
        self.exceptions = exceptions
    
    def get_delay(self, attempt: int) -> float:
        """计算延迟时间"""
        return self.delay * (self.backoff_factor ** (attempt - 1))

def retry(strategy: RetryStrategy = None):
    """重试装饰器"""
    if strategy is None:
        strategy = RetryStrategy()
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, strategy.max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except strategy.exceptions as e:
                    last_exception = e
                    
                    if attempt < strategy.max_retries:
                        delay = strategy.get_delay(attempt)
                        logger.warning(
                            f"重试",
                            function=func.__name__,
                            attempt=attempt,
                            max_retries=strategy.max_retries,
                            delay=f"{delay:.2f}s",
                            error=str(e)
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            f"重试耗尽",
                            function=func.__name__,
                            attempts=attempt,
                            error=str(e)
                        )
            
            raise last_exception
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(1, strategy.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except strategy.exceptions as e:
                    last_exception = e
                    
                    if attempt < strategy.max_retries:
                        delay = strategy.get_delay(attempt)
                        logger.warning(
                            f"重试",
                            function=func.__name__,
                            attempt=attempt,
                            delay=f"{delay:.2f}s",
                            error=str(e)
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"重试耗尽",
                            function=func.__name__,
                            attempts=attempt,
                            error=str(e)
                        )
            
            raise last_exception
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator