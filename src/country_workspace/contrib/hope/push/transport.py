from collections.abc import Mapping
from http import HTTPStatus
from typing import Any, Final

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.exceptions import HopeResponseError

from .config import ROUTES, RdiDeleteResult, Route


RDI_ALREADY_MERGED_ERROR_CODE: Final[str] = "rdi_already_merged"


class HopeApi:
    """Thin transport adapter over HopeClient."""

    def __init__(self, *, co_slug: str) -> None:
        self.client = HopeClient()
        self.co_slug = co_slug

    def create_rdi(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return self._post(Route.CREATE_RDI, payload)

    def post_individuals(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.INDIVIDUALS, payload, rdi_id=rdi_id)

    def post_households(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.HOUSEHOLDS, payload, rdi_id=rdi_id)

    def post_people(self, rdi_id: str, payload: list[dict]) -> dict[str, Any]:
        return self._post(Route.PEOPLE, payload, rdi_id=rdi_id)

    def complete_rdi(self, rdi_id: str) -> dict[str, Any]:
        return self._post(Route.COMPLETE_RDI, {}, rdi_id=rdi_id)

    def _post(self, route: Route, payload: Any, *, rdi_id: str | None = None) -> dict[str, Any]:
        url = ROUTES[route].format(co_slug=self.co_slug, **({"rdi_id": rdi_id} if rdi_id else {}))
        return self.client.post(url, payload)

    def delete_rdi(self, rdi_id: str) -> RdiDeleteResult:
        url = ROUTES[Route.DELETE_RDI].format(co_slug=self.co_slug, rdi_id=rdi_id)
        try:
            self.client.delete(url)
        except HopeResponseError as exc:
            match exc.response.status_code:
                case HTTPStatus.NOT_FOUND:
                    return RdiDeleteResult.DELETED
                case HTTPStatus.CONFLICT if exc.error_code == RDI_ALREADY_MERGED_ERROR_CODE:
                    return RdiDeleteResult.ALREADY_MERGED
            raise
        return RdiDeleteResult.DELETED
