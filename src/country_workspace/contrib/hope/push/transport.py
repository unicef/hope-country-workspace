from collections.abc import Callable, Mapping
from json import JSONDecodeError
from typing import Any

from requests.exceptions import RequestException

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.exceptions import RemoteError

from .config import ROUTES, Route


class HopeApi:
    """Thin client over HopeClient with typed routes and uniform error handling."""

    def __init__(self, *, co_slug: str, err: Callable[[str], None]) -> None:
        self.client = HopeClient()
        self.co_slug = co_slug
        self.err = err

    def create_rdi(self, payload: Mapping[str, Any]) -> dict[str, Any] | None:
        return self._post(Route.CREATE, payload)

    def post_individuals(self, rdi_id: str, payload: list[dict]) -> dict[str, Any] | None:
        return self._post(Route.INDIVIDUALS, payload, rdi_id=rdi_id)

    def post_households(self, rdi_id: str, payload: list[dict]) -> dict[str, Any] | None:
        return self._post(Route.HOUSEHOLDS, payload, rdi_id=rdi_id)

    def post_people(self, rdi_id: str, payload: list[dict]) -> dict[str, Any] | None:
        return self._post(Route.PEOPLE, payload, rdi_id=rdi_id)

    def complete_rdi(self, rdi_id: str) -> dict[str, Any] | None:
        return self._post(Route.COMPLETE, {}, rdi_id=rdi_id)

    def _post(self, route: Route, payload: Any, *, rdi_id: str | None = None) -> dict[str, Any] | None:
        """POST JSON for the given route; build URL here and log uniform errors."""
        url = ROUTES[route].format(co_slug=self.co_slug, **({"rdi_id": rdi_id} if rdi_id else {}))
        error_msg = f"Hope API: {route.value}"
        try:
            return self.client.post(url, payload)
        except (RequestException, JSONDecodeError, RemoteError) as e:
            self.err(f"{error_msg}: {e}")
            return None
