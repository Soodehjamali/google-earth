"""In-memory caching service for Earth Engine results."""

import hashlib
import json
import time
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class CacheService:
    """Bounded in-memory cache with TTL and cross-worker file fallback for tile templates."""

    def __init__(self, ttl: Optional[int] = None, max_entries: int = 5000):
        self._cache: dict[str, tuple[Any, float, int]] = {}
        self._ttl = ttl or getattr(settings, "CACHE_TTL", 3600)
        self._max_entries = max_entries
        import tempfile
        from pathlib import Path

        self._shared_dir = Path(tempfile.gettempdir()) / "antigravity_tile_cache"
        try:
            self._shared_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    def _make_key(self, **kwargs) -> str:
        """Create a cache key from parameters."""
        key_data = json.dumps(kwargs, sort_keys=True, default=str)
        return hashlib.sha256(key_data.encode()).hexdigest()

    def get(self, key: str) -> Optional[Any]:
        """Get a value from cache, resolving tile_template across workers if needed."""
        now = time.time()
        if key in self._cache:
            entry = self._cache[key]
            value, timestamp, item_ttl = (
                entry if len(entry) == 3 else (entry[0], entry[1], self._ttl)
            )
            if now - timestamp < item_ttl:
                logger.debug(f"Cache hit: {key[:16]}...")
                return value
            else:
                del self._cache[key]
                logger.debug(f"Cache expired: {key[:16]}...")

        # Cross-worker disk-backed fallback for tile_template:* keys
        if key.startswith("tile_template:"):
            try:
                safe_name = key.replace(":", "_") + ".json"
                fpath = self._shared_dir / safe_name
                if fpath.exists():
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    ts = float(data.get("ts", 0))
                    ttl = int(data.get("ttl", self._ttl))
                    if now - ts < ttl:
                        val = data.get("val")
                        self.set(key, val, ttl=int(ttl - (now - ts)))
                        return val
                    else:
                        fpath.unlink(missing_ok=True)
            except Exception as exc:
                logger.debug("Failed reading shared tile cache file: %s", exc)

        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in cache, evicting if over max_entries and persisting tile_template:*."""
        now = time.time()
        item_ttl = ttl or self._ttl

        # Evict if over capacity
        if len(self._cache) >= self._max_entries:
            # 1. Evict expired
            expired = [
                k
                for k, v in self._cache.items()
                if now - v[1] >= (v[2] if len(v) == 3 else self._ttl)
            ]
            for k in expired:
                del self._cache[k]
            # 2. If still full, evict oldest 20%
            if len(self._cache) >= self._max_entries:
                sorted_keys = sorted(self._cache.keys(), key=lambda k: self._cache[k][1])
                for k in sorted_keys[: len(self._cache) // 5 + 1]:
                    del self._cache[k]

        self._cache[key] = (value, now, item_ttl)
        logger.debug(f"Cache set: {key[:16]}...")

        # Persist tile_template:* for cross-worker sharing
        if key.startswith("tile_template:") and isinstance(value, str):
            try:
                safe_name = key.replace(":", "_") + ".json"
                fpath = self._shared_dir / safe_name
                with open(fpath, "w", encoding="utf-8") as f:
                    json.dump({"val": value, "ts": now, "ttl": item_ttl}, f)
            except Exception as exc:
                logger.debug("Failed writing shared tile cache file: %s", exc)

    def invalidate(self, key: str) -> None:
        """Remove a value from cache and shared disk store."""
        self._cache.pop(key, None)
        if key.startswith("tile_template:"):
            try:
                safe_name = key.replace(":", "_") + ".json"
                (self._shared_dir / safe_name).unlink(missing_ok=True)
            except Exception:
                pass

    def clear(self) -> None:
        """Clear all cached values."""
        self._cache.clear()

    @property
    def size(self) -> int:
        """Get number of cached items."""
        return len(self._cache)


# Global cache instance
cache_service = CacheService()
