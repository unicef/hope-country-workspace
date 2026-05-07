from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from requests import Session

from . import endpoint, request, response


TIMEOUT: Final[tuple[int, int]] = (10, 20)


@dataclass(slots=True)
class GenericResource[T]:
    session: Session
    endpoint: T


class CreateMixin[T, R]:
    def create(self: GenericResource, body: T, *, params: Mapping[str, str] | None = None) -> R:
        result = self.session.post(str(self.endpoint), json=body, params=params, timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()


class RetrieveMixin[R]:
    def retrieve(self: GenericResource) -> R:
        result = self.session.get(str(self.endpoint), timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()


class UpdateMixin[T, R]:
    def update(self: GenericResource, body: T) -> R:
        result = self.session.post(str(self.endpoint), json=body, timeout=TIMEOUT)
        result.raise_for_status()
        return result.json()


class ActionMixin[T]:
    def call(self: GenericResource, body: T | None = None, *, params: Mapping[str, str] | None = None) -> None:
        kwargs = {"json": body} if body is not None else {}
        result = self.session.post(str(self.endpoint), params=params, timeout=TIMEOUT, **kwargs)
        result.raise_for_status()


class DeduplicationSetCollection(
    GenericResource[endpoint.DeduplicationSets],
    CreateMixin[request.CreateDeduplicationSet, response.CreatedDeduplicationSet],
): ...


class DeduplicationSetItem(
    GenericResource[endpoint.DeduplicationSet],
    RetrieveMixin[response.DeduplicationSet],
): ...


class ImagesCollection(
    GenericResource[endpoint.Images],
    CreateMixin[list[request.CreateEncoding], list[response.CreatedEncoding]],
): ...


class ReadyDeduplicationSetAction(
    GenericResource[endpoint.Ready],
    ActionMixin[None],
): ...


class ProcessDeduplicationSetAction(
    GenericResource[endpoint.Process],
    ActionMixin[None],
): ...


class RejectDeduplicationSetAction(
    GenericResource[endpoint.Reject],
    ActionMixin[None],
): ...


class DeduplicationSetGroupConfigItem(
    GenericResource[endpoint.DeduplicationSetGroupConfig],
    RetrieveMixin[response.DeduplicationSetGroupConfig],
    UpdateMixin[request.DeduplicationSetGroupConfig, response.DeduplicationSetGroupConfig],
): ...
