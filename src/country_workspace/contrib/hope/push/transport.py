from collections.abc import Mapping, Iterator
from typing import Any
from contextlib import contextmanager

from requests.exceptions import HTTPError, RequestException
from rest_framework.status import HTTP_404_NOT_FOUND
from country_workspace.contrib.hope.client import HopeClient
from country_workspace.exceptions import RemoteError
from country_workspace.contrib.dedup_engine.client import make_client


from .config import ROUTES, Route


class HopeApi:
    """Thin transport adapter over HopeClient."""

    def __init__(self, *, co_slug: str) -> None:
        self.client = HopeClient()
        self.co_slug = co_slug

    def create_rdi(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post(Route.CREATE, payload)

    def post_individuals(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.INDIVIDUALS, payload, rdi_id=rdi_id)

    def post_households(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.HOUSEHOLDS, payload, rdi_id=rdi_id)

    def post_people(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.PEOPLE, payload, rdi_id=rdi_id)

    def complete_rdi(self, rdi_id: str) -> dict[str, Any]:
        return self._post(Route.COMPLETE, {}, rdi_id=rdi_id)

    def _post(self, route: Route, payload: Any, *, rdi_id: str | None = None) -> dict[str, Any]:
        url = ROUTES[route].format(co_slug=self.co_slug, **({"rdi_id": rdi_id} if rdi_id else {}))
        return self.client.post(url, payload)


DEDUPLICATION_SET_NOT_EXPOSED = object()


@contextmanager
def dedup_api(program_id: str) -> Iterator[Any]:
    with make_client(program_id) as client:

        def _raise(name: str, e: Exception, resp: object | None) -> None:
            req = getattr(resp, "request", None) if resp else None
            head = f"{getattr(req, 'method', '')} {getattr(req, 'url', '')}".strip() or f"client.{name}"
            tail = (
                f". Status: {getattr(resp, 'status_code', None)}. Response: {getattr(resp, 'text', None)}"
                if resp
                else ""
            )
            raise RemoteError(f"DedupEngine: {head} failed: {e}{tail}") from e

        class Proxy:
            def __getattr__(self, name: str) -> Any:
                attr = getattr(client, name)
                if not callable(attr):
                    return attr

                def wrapped(*args: Any, **kwargs: Any) -> Any:
                    try:
                        result = attr(*args, **kwargs)
                    except (RequestException, ValueError, KeyError, TypeError) as e:
                        resp = getattr(e, "response", None)
                        if (
                            name == "status"
                            and isinstance(e, HTTPError)
                            and getattr(resp, "status_code", None) == HTTP_404_NOT_FOUND
                        ):
                            return DEDUPLICATION_SET_NOT_EXPOSED
                        _raise(name, e, resp)
                    return True if result is None else result

                return wrapped

        proxy = Proxy()
        proxy.DEDUPLICATION_SET_NOT_EXPOSED = DEDUPLICATION_SET_NOT_EXPOSED
        yield proxy
