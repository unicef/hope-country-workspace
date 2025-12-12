import logging
from typing import TYPE_CHECKING, Any

from constance import config
from django.core.cache import caches
from django.core.cache.backends.redis import RedisCacheClient
from django.http import HttpRequest
from django.utils import timezone
from django.utils.text import slugify
from redis_lock.django_cache import RedisCache
from sentry_sdk import capture_exception

from country_workspace import VERSION
from country_workspace.state import state
from .signals import cache_get, cache_invalidate, cache_set

if TYPE_CHECKING:
    from ..models import Office, Program
logger = logging.getLogger(__name__)


class CacheManager:
    def __init__(self, prefix: str = "cache") -> None:
        self.prefix = prefix
        self.cw_version = "-"
        self.cache_timeout = 86400
        self.cache_by_version = False

    def get_redis_client(self) -> RedisCacheClient:
        return self.cache.client.get_client()

    @property
    def cache(self) -> RedisCache:
        return caches["default"]

    def init(self) -> None:
        from . import handlers  # noqa: F401

        try:
            self.cache_timeout = config.CACHE_TIMEOUT
            self.cache_by_version = config.CACHE_BY_VERSION
            if self.cache_by_version:
                self.cw_version = VERSION
        except Exception as e:
            logger.exception(e)
            capture_exception(e)

    def invalidate(self, key: str) -> None:
        cache_invalidate.send(CacheManager, key=key)

    def retrieve(self, key: str) -> Any:
        if not self.active:
            return None
        data = self.cache.get(key)
        cache_get.send(CacheManager, key=key, hit=bool(data))
        return data

    def store(self, key: str, value: Any, timeout: int = 0, **kwargs: Any) -> None:
        cache_set.send(self.__class__, key=key)
        if not self.active:
            timeout = 1
        self.cache.set(key, value, timeout=timeout or self.cache_timeout, **kwargs)

    def _get_version_key(self, office: "Office | None" = None, program: "Program | None" = None) -> str:
        if program:
            office = program.country_office
        elif office:
            program = None

        parts = [self.prefix, "key", office.slug if office else "-", str(program.pk) if program else "-"]
        return ":".join(parts)

    def reset_cache_version(self, *, office: "Office | None" = None, program: "Program | None" = None) -> None:
        key = self._get_version_key(office, program)
        self.cache.delete(key)

    def get_cache_version(self, *, office: "Office | None" = None, program: "Program | None" = None) -> int:
        key = self._get_version_key(office, program)
        version = self.cache.get(key)
        if not version:
            version = 1
            self.cache.set(key, version, timeout=self.cache_timeout)
        return version

    def incr_cache_version(self, *, office: "Office | None" = None, program: "Program | None" = None) -> int:
        if office and program:
            raise ValueError("Cannot use both office and program")
        key = self._get_version_key(office, program)
        try:
            return self.cache.incr(key)
        except ValueError:
            return self.cache.set(key, 2)

    @property
    def active(self) -> bool:
        return not bool(self.cache.get(f"{self.prefix}:cache_disabled"))

    @active.setter
    def active(self, value: bool) -> None:
        if not value:
            self.cache.set(f"{self.prefix}:cache_disabled", True)
        else:
            self.cache.delete(f"{self.prefix}:cache_disabled")

    def build_key(self, prefix: str, *parts: list[str]) -> str:
        tenant = "t"
        version = "v"
        program = "p"
        ts = "ts"
        if not self.active:
            ts = str(timezone.now().toordinal())

        if state.tenant and state.program:
            tenant = state.tenant.slug
            program = str(state.program.pk)
            version = str(self.get_cache_version(program=state.program))
        elif state.tenant:
            tenant = state.tenant.slug
            version = str(self.get_cache_version(office=state.tenant))

        final_parts = [self.prefix, "entry", prefix, self.cw_version, ts, version, tenant, program, *parts]
        return ":".join(map(str, final_parts))

    def build_key_from_request(self, request: HttpRequest, prefix: str = "view", *args: list[str]) -> str:
        return self.build_key(
            prefix,
            *[slugify(request.path), slugify(str(sorted(request.GET.items()))), *[str(e) for e in args]],
        )

    def invalidate_pattern(self, pattern: str) -> int:
        client = self.get_redis_client()
        deleted_count = 0

        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                deleted_count += client.delete(*keys)
            if cursor == 0:
                break

        return deleted_count

    def invalidate_containing(self, substring: str) -> int:
        return self.invalidate_pattern(f"*{substring}*")


cache_manager = CacheManager()
