from collections.abc import Mapping
from typing import Any

from country_workspace.contrib.hope.client import HopeClient


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
