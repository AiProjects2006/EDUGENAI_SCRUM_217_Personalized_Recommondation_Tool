"""Redis cache client with TTL, key invalidation, and in-process memory fallback."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Iterable, Optional

from config import settings
from models import RecommendationBundleResponse, RecommendationToolOutput

log = logging.getLogger(__name__)


class RecommendationRedisCache:
    """Caches per-student recommendation bundles in Redis with TTL and invalidation."""

    def __init__(
        self,
        host: str = settings.redis_host,
        port: int = settings.redis_port,
        db: int = settings.redis_db,
        ttl_seconds: int = settings.cache_ttl_seconds,
        client: Optional[Any] = None,
    ) -> None:
        self.ttl_seconds = max(1, int(ttl_seconds))
        self._client: Optional[Any] = None
        self._memory_fallback: dict[str, tuple[float, str]] = {}
        self.backend = "memory"

        if client is not None:
            try:
                if callable(getattr(client, "ping", None)):
                    client.ping()
                self._client = client
                self.backend = "redis"
                return
            except Exception as exc:
                log.info("Injected Redis client unavailable (%s); using in-process cache.", exc)
                self._client = None
                return

        try:
            import redis

            redis_client = redis.Redis(
                host=host,
                port=port,
                db=db,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=1.0,
            )
            redis_client.ping()
            self._client = redis_client
            self.backend = "redis"
            log.info("Connected to Redis Cache at %s:%s", host, port)
        except Exception as exc:
            log.info("Redis unavailable (%s); using in-process cache fallback.", exc)
            self._client = None

    @staticmethod
    def _key(user_id: int) -> str:
        return f"rec:user:{user_id}:v1"

    def get(self, user_id: int) -> Optional[str]:
        """Return raw cached JSON for a student, or None on miss/expiry."""
        key = self._key(user_id)
        if self._client is not None:
            try:
                return self._client.get(key)
            except Exception as exc:
                log.debug("Redis get error for %s: %s", key, exc)

        entry = self._memory_fallback.get(key)
        if not entry:
            return None
        expires_at, payload_json = entry
        if time.monotonic() >= expires_at:
            self._memory_fallback.pop(key, None)
            return None
        return payload_json

    def set(
        self,
        user_id: int,
        payload_json: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store raw JSON in Redis (with TTL) and mirror to the local fallback."""
        key = self._key(user_id)
        ttl = max(1, int(self.ttl_seconds if ttl_seconds is None else ttl_seconds))
        if self._client is not None:
            try:
                self._client.setex(key, ttl, payload_json)
            except Exception as exc:
                log.debug("Redis set error for %s: %s", key, exc)

        self._memory_fallback[key] = (time.monotonic() + ttl, payload_json)

    def get_bundle(self, user_id: int) -> Optional[RecommendationBundleResponse]:
        """Deserialize a cached recommendation bundle, flagging cacheHit=True."""
        raw = self.get(user_id)
        if not raw:
            return None
        try:
            data = json.loads(raw)
            data["cacheHit"] = True
            return RecommendationBundleResponse(**data)
        except Exception as exc:
            log.debug("Cache deserialize error for user %s: %s", user_id, exc)
            self.invalidate(user_id)
            return None

    def set_bundle(
        self,
        bundle: RecommendationToolOutput,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Serialize and cache a RecommendationToolOutput or RecommendationBundleResponse."""
        self.set(bundle.userId, bundle.model_dump_json(), ttl_seconds=ttl_seconds)

    def invalidate(self, user_id: int) -> None:
        """Delete a student's cached recommendation bundle from Redis and memory."""
        key = self._key(user_id)
        if self._client is not None:
            try:
                self._client.delete(key)
            except Exception as exc:
                log.debug("Redis delete error for %s: %s", key, exc)
        self._memory_fallback.pop(key, None)

    def invalidate_users(self, user_ids: Iterable[int]) -> None:
        """Invalidate cached recommendation bundles for multiple students."""
        for uid in user_ids:
            self.invalidate(int(uid))
