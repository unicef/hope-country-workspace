from collections.abc import Mapping
from enum import StrEnum, auto
from http import HTTPStatus
from typing import Any, Final

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.exceptions import HopeResponseError
from country_workspace.exceptions import RemoteError

from .exceptions import HopeRdiResetUnconfirmedError


class RdiResetResult(StrEnum):
    ACCEPTED = auto()
    NOT_FOUND = auto()
    MERGE_IN_PROGRESS = auto()
    ALREADY_MERGED = auto()


class Route(StrEnum):
    CREATE_RDI = auto()
    COMPLETE_RDI = auto()
    INDIVIDUALS = auto()
    HOUSEHOLDS = auto()
    PEOPLE = auto()
    RESET_RDI = auto()


ROUTES: Final[dict[Route, str]] = {
    Route.CREATE_RDI: "{co_slug}/rdi/create/",
    Route.COMPLETE_RDI: "{co_slug}/rdi/{rdi_id}/completed/",
    Route.INDIVIDUALS: "{co_slug}/rdi/{rdi_id}/push/lax/individuals/",
    Route.HOUSEHOLDS: "{co_slug}/rdi/{rdi_id}/push/lax/households/",
    Route.PEOPLE: "{co_slug}/rdi/{rdi_id}/push/people/",
    Route.RESET_RDI: "{co_slug}/rdi/{rdi_id}/reset/",
}


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

    def reset_rdi(self, rdi_id: str, callback_url: str, signed_token: str) -> RdiResetResult:
        url = ROUTES[Route.RESET_RDI].format(co_slug=self.co_slug, rdi_id=rdi_id)

        try:
            self.client.post(
                url,
                {
                    "callback_url": callback_url,
                    "signed_token": signed_token,
                },
            )
        except HopeResponseError as exc:
            if exc.response.status_code == HTTPStatus.NOT_FOUND:
                return RdiResetResult.NOT_FOUND
            if exc.response.status_code == HTTPStatus.CONFLICT:
                match exc.error_code:
                    case "rdi_merge_in_progress":
                        return RdiResetResult.MERGE_IN_PROGRESS
                    case "rdi_already_merged":
                        return RdiResetResult.ALREADY_MERGED
            if exc.response.status_code >= HTTPStatus.INTERNAL_SERVER_ERROR:
                raise HopeRdiResetUnconfirmedError(str(exc)) from exc
            raise
        except RemoteError as exc:
            raise HopeRdiResetUnconfirmedError(str(exc)) from exc

        return RdiResetResult.ACCEPTED
