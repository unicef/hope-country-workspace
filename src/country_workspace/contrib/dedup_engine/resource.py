from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

from requests import Session
from requests.exceptions import HTTPError


TIMEOUT: Final[tuple[int, int]] = (10, 20)
UPLOAD_TIMEOUT: Final[tuple[int, int]] = (10, 120)


@dataclass(slots=True)
class GenericResource[T]:
    session: Session
    endpoint: T


class CreateMixin[T, R]:
    def create(
        self: GenericResource,
        body: T,
        *,
        params: Mapping[str, str] | None = None,
        timeout: tuple[int, int] = TIMEOUT,
    ) -> R:
        result = self.session.post(str(self.endpoint), json=body, params=params, timeout=timeout)
        result.raise_for_status()
        return result.json()


class ListMixin[R]:
    def list(self: GenericResource, *, params: Mapping[str, str] | None = None) -> R:
        result = self.session.get(str(self.endpoint), params=params, timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()


class RetrieveMixin[R]:
    def retrieve(self: GenericResource, *, timeout: tuple[int, int] = TIMEOUT) -> R:
        result = self.session.get(str(self.endpoint), timeout=timeout)
        result.raise_for_status()
        return result.json()

    def retrieve_or_none(self: GenericResource, *, timeout: tuple[int, int] = TIMEOUT) -> R | None:
        result = self.session.get(str(self.endpoint), timeout=timeout)
        try:
            result.raise_for_status()
        except HTTPError as exc:
            if getattr(exc.response, "status_code", None) == HTTPStatus.NOT_FOUND:
                return None
            raise
        return result.json()


class UpdateMixin[T, R]:
    def update(self: GenericResource, body: T) -> R:
        result = self.session.post(str(self.endpoint), json=body, timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()


class DeleteMixin:
    def delete(self: GenericResource) -> None:
        result = self.session.delete(str(self.endpoint), timeout=TIMEOUT)
        result.raise_for_status()


class ActionMixin[T]:
    def call(self: GenericResource, body: T | None = None, *, params: Mapping[str, str] | None = None) -> None:
        kwargs = {"json": body} if body is not None else {}
        result = self.session.post(str(self.endpoint), params=params, timeout=TIMEOUT, **kwargs)
        result.raise_for_status()
