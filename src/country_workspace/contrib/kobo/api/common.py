from collections.abc import Callable
from typing import Any, TypedDict

from django.core.cache import cache
from requests import HTTPError, Response, Session

UrlPredicate = Callable[[str], bool]


class ResponseDict(TypedDict):
    """Dictionary for response data."""

    json: dict[str, Any]
    status_code: int


class CachedResponse:
    """Wrapper resembling requests.Response."""

    def __init__(self, response_dict: ResponseDict) -> None:
        self._response_dict = response_dict

    def json(self) -> dict[str, Any]:
        return self._response_dict["json"]

    @property
    def status_code(self) -> int:
        return self._response_dict["status_code"]

    def raise_for_status(self) -> None:
        pass


def data_getter_cache_key(url: str) -> str:
    return f"dg:{url}"


class DataGetter:
    """
    An abstraction over HTTP GET request.

    A class used to abstract HTTP GET request, so authentication, caching,
    etc. can be configured without touching the rest of the code.
    """

    def __init__(
        self,
        session: Session,
        cache_ttl: int,
        headers: dict[str, str] | None = None,
        do_not_use_cache_if: UrlPredicate | None = None,
    ) -> None:
        self._session = session
        self._headers = headers
        self._cache_ttl = cache_ttl
        self._do_not_use_cache_if = do_not_use_cache_if

    def __call__(self, url: str) -> Response | CachedResponse:
        if self._do_not_use_cache_if and self._do_not_use_cache_if(url):
            return self._session.get(url, headers=self._headers)

        cache_key = data_getter_cache_key(url)

        if cached_value := cache.get(cache_key):
            return CachedResponse(cached_value)

        response = self._session.get(url, headers=self._headers)
        try:
            response.raise_for_status()
        except HTTPError:
            # don't cache failed response
            return response

        value: ResponseDict = {"json": response.json(), "status_code": response.status_code}
        cache.set(cache_key, value, self._cache_ttl)

        return response
