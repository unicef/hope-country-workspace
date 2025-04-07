from typing import Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_response_headers
from django.utils.deprecation import MiddlewareMixin

from country_workspace.cache.manager import cache_manager


class UpdateCacheMiddleware(MiddlewareMixin):
    def __init__(self, get_response: Callable) -> None:
        super().__init__(get_response)
        self.cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
        self.page_timeout = 10
        self.manager = cache_manager

    def _should_update_cache(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        return hasattr(request, "_cache_update_cache") and request._cache_update_cache

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        """Set the cache, if needed."""
        if not self._should_update_cache(request, response):
            # We don't need to update the cache, just return.
            return response

        if response.streaming or response.status_code not in (200, 304):
            return response

        # Don't cache a response with 'Cache-Control: private'
        if "private" in response.get("Cache-Control", ()):
            return response

        # Page timeout takes precedence over the "max-age" and the default
        # cache timeout.
        timeout = self.page_timeout
        patch_response_headers(response, timeout)
        if response.status_code == 200:
            if "Etag" in response.headers:
                cache_key = response.headers["Etag"]
            else:
                cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
                response.headers["Etag"] = cache_key
            if hasattr(response, "render") and callable(response.render):
                response.add_post_render_callback(lambda r: self.manager.store(cache_key, r))
            else:
                self.manager.store(cache_key, response)
        return response


class FetchFromCacheMiddleware(MiddlewareMixin):
    def __init__(self, get_response: Callable) -> None:
        super().__init__(get_response)
        self.manager = cache_manager

    def process_request(self, request: HttpRequest) -> HttpResponse:
        if request.method not in ("GET", "HEAD"):
            request._cache_update_cache = False
            return None  # Don't bother checking the cache.

        # try and get the cached GET response
        cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
        if cache_key is None:
            request._cache_update_cache = True
            return None  # No cache information available, need to rebuild.
        if request.headers.get("etag") == cache_key:
            return HttpResponse(status=304, headers={"Etag": cache_key})
        response = self.manager.retrieve(cache_key)

        if response is None:
            request._cache_update_cache = True
            return None  # No cache information available, need to rebuild.

        # hit, return cached response
        request._cache_update_cache = False

        return response
