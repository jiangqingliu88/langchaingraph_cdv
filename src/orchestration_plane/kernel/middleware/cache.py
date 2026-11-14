"""
缓存中间件 - 使用装饰器模式
"""
import asyncio
import time
from functools import wraps
from typing import Dict, Any, Optional, Callable
import hashlib
import json
import structlog

logger = structlog.get_logger()

class CacheMiddleware:
    """缓存中间件"""
    
    def __init__(self, ttl: int = 300, max_size: int = 100):
        """
        初始化缓存
        ttl: 缓存生存时间(秒)
        max_size: 最大缓存条目数
        """
        self.ttl = ttl
        self.max_size = max_size
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._access_times: Dict[str, float] = {}
    
    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> str:
        """生成缓存键"""
        key_data = {
            "func": func_name,
            "args": str(args),
            "kwargs": str(sorted(kwargs.items()))
        }
        key_str = json.dumps(key_data, sort_keys=True)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def _is_expired(self, key: str) -> bool:
        """检查缓存是否过期"""
        if key not in self._access_times:
            return True
        return (time.time() - self._access_times[key]) > self.ttl
    
    def _evict_oldest(self):
        """淘汰最旧的缓存"""
        if len(self._cache) >= self.max_size:
            oldest_key = min(self._access_times, key=self._access_times.get)
            del self._cache[oldest_key]
            del self._access_times[oldest_key]
            logger.debug("缓存淘汰", key=oldest_key)
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self._cache and not self._is_expired(key):
            self._access_times[key] = time.time()
            return self._cache[key]["value"]
        return None
    
    def set(self, key: str, value: Any):
        """设置缓存"""
        self._evict_oldest()
        self._cache[key] = {
            "value": value,
            "created_at": time.time()
        }
        self._access_times[key] = time.time()
    
    def clear(self):
        """清除所有缓存"""
        self._cache.clear()
        self._access_times.clear()
        logger.info("缓存已清除")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计"""
        return {
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
            "hit_rate": self._calculate_hit_rate()
        }
    
    def _calculate_hit_rate(self) -> float:
        """计算命中率"""
        # 简化实现
        return len(self._cache) / max(self.max_size, 1) * 100

# 全局缓存实例
global_cache = CacheMiddleware()

def cached(ttl: int = 300):
    """缓存装饰器"""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            # 生成缓存键
            key = global_cache._make_key(func.__name__, args, kwargs)
            
            # 检查缓存
            cached_result = global_cache.get(key)
            if cached_result is not None:
                logger.debug("缓存命中", function=func.__name__)
                return cached_result
            
            # 执行函数
            result = await func(*args, **kwargs)
            
            # 缓存结果
            global_cache.set(key, result)
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            key = global_cache._make_key(func.__name__, args, kwargs)
            
            cached_result = global_cache.get(key)
            if cached_result is not None:
                logger.debug("缓存命中", function=func.__name__)
                return cached_result
            
            result = func(*args, **kwargs)
            global_cache.set(key, result)
            
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    
    return decorator