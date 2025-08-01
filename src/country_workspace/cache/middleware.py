from typing import Callable

from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_response_headers
from django.utils.deprecation import MiddlewareMixin

from country_workspace.cache.manager import cache_manager

NOT_CACHABLE_METHODS = ("POST",)


class UpdateCacheMiddleware(MiddlewareMixin):
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        super().__init__(get_response)
        self.cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
        self.page_timeout = 10
        self.manager = cache_manager

    def _should_update_cache(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        return hasattr(request, "_cache_update_cache") and request._cache_update_cache

    def _invalidate_cache_for_request(self, request: HttpRequest) -> None:
        cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
        if cache_key:
            self.manager.cache.delete(cache_key)

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        if not self._should_update_cache(request, response):
            return response
        if response.streaming or response.status_code not in (200, 304):
            return response
        if "private" in response.get("Cache-Control", ()):
            return response
        if request.method in NOT_CACHABLE_METHODS:
            return response
        if get_messages(request):
            self._invalidate_cache_for_request(request)
            return response
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
        if request.method in NOT_CACHABLE_METHODS or get_messages(request):
            request._cache_update_cache = True
            return None

        if request.method not in ("GET", "HEAD"):
            request._cache_update_cache = False
            return None

        cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
        if cache_key is None:
            request._cache_update_cache = True
            return None

        if request.headers.get("etag") == cache_key:
            return HttpResponse(status=304, headers={"Etag": cache_key})

        response = self.manager.retrieve(cache_key)
        if response is None:
            request._cache_update_cache = True
            return None

        request._cache_update_cache = False
        return response
