"""In-memory caching service for Earth Engine results."""

import hashlib
import json
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    """Simple in-memory cache with TTL."""
    
    def __init__(self, ttl: int = None):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._ttl = ttl or settings.CACHE_TTL
    
    def _make_key(self, **kwargs) -> str:
        """Create a cache key from parameters."""
        key_data = json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.sha256(key_data.encode()).hexdigest()
    
    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache."""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                logger.debug(f"Cache hit: {key[:16]}...")
                return value
            else:
                del self._cache[key]
                logger.debug(f"Cache expired: {key[:16]}...")
        return None
    
    def set(self, key: str, value: Any) -> None:
        """Set a value in cache."""
        self._cache[key] = (value, time.time())
        logger.debug(f"Cache set: {key[:16]}...")
    
    def invalidate(self, key: str) -> None:
        """Remove a value from cache."""
        self._cache.pop(key, None)
    
    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()
    
    @property
    def size(self) -> int:
        """Get number of cached items."""
        return len(self._cache)


# Global cache instance
cache_service = CacheService()
