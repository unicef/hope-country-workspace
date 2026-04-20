from typing import Callable

from django.conf import settings
from django.contrib.messages import get_messages
from django.http import HttpRequest, HttpResponse
from django.utils.cache import patch_response_headers
from django.utils.deprecation import MiddlewareMixin

from country_workspace.cache.manager import cache_manager

NOT_CACHABLE_METHODS = {"POST"}


class UpdateCacheMiddleware(MiddlewareMixin):
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        super().__init__(get_response)
        self.cache_timeout = settings.CACHE_MIDDLEWARE_SECONDS
        self.page_timeout = 10
        self.manager = cache_manager

    def _should_invalidate_cache(self, request: HttpRequest, response: HttpResponse) -> bool:
        return any(
            (
                get_messages(request),
                request.method == "POST" and response.status_code == 302,
            )
        )

    def _should_update_cache(self, request: HttpRequest, response: HttpResponse) -> bool:
        return all(
            (
                hasattr(request, "_cache_update_cache") and request._cache_update_cache,
                not response.streaming,
                response.status_code in (200, 304),
                "private" not in response.get("Cache-Control", ""),
                request.method not in NOT_CACHABLE_METHODS,
                not get_messages(request),
            )
        )

    def _invalidate_cache(self, request: HttpRequest) -> None:
        cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
        if request.method == "POST":
            for verb in ("add", "change", "delete"):
                if request.path.endswith(f"/{verb}/"):
                    if verb == "add":
                        sep = verb
                    else:
                        pk = request.resolver_match.kwargs.get("object_id", "")
                        sep = f"{pk}{verb}"
                    # last occurrence
                    cache_key = "".join(cache_key.rsplit(sep, 1))
                    break
        self.manager.cache.delete(cache_key)

    def _update_cache(self, request: HttpRequest, response: HttpResponse) -> None:
        timeout = self.page_timeout
        patch_response_headers(response, timeout)

        if response.status_code == 200:
            if "Etag" in response.headers:
                cache_key = response.headers["Etag"]
            else:
                cache_key = self.manager.build_key_from_request(request, "view", getattr(request.user, "pk", ""))
                response.headers["Etag"] = cache_key
            if hasattr(response, "render") and callable(response.render):
                response.add_post_render_callback(lambda r: self.manager.store(cache_key, r, timeout=timeout))
            else:
                self.manager.store(cache_key, response, timeout=timeout)

    def process_response(self, request: HttpRequest, response: HttpResponse) -> HttpResponse:
        if self._should_invalidate_cache(request, response):
            self._invalidate_cache(request)

        if self._should_update_cache(request, response):
            self._update_cache(request, response)

        return response


class FetchFromCacheMiddleware(MiddlewareMixin):
    def __init__(self, get_response: Callable) -> None:
        super().__init__(get_response)
        self.manager = cache_manager

    def process_request(self, request: HttpRequest) -> HttpResponse | None:
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
