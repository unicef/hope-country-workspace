from dataclasses import dataclass

from requests import Session

from country_workspace.contrib.dedup_engine import endpoint, request, response


@dataclass
class GenericResource[T]:
    session: Session
    endpoint: T


class CreateMixin[T, R]:
    def create(self: GenericResource, body: T) -> R:
        result = self.session.post(str(self.endpoint), json=body)
        result.raise_for_status()
        return result.json()


class RetrieveMixin[R]:
    def retrieve(self: GenericResource) -> R:
        result = self.session.get(str(self.endpoint))
        result.raise_for_status()
        return result.json()


class ActionMixin[T]:
    def call(self: GenericResource, body: T) -> None:
        result = self.session.post(str(self.endpoint), json=body)
        result.raise_for_status()


class DeduplicationSetCollection(
    GenericResource[endpoint.DeduplicationSets],
    CreateMixin[request.DeduplicationSet, response.DeduplicationSet],
):
    pass


class DeduplicationSetItem(
    GenericResource[endpoint.DeduplicationSet],
    RetrieveMixin[response.DeduplicationSet],
):
    pass


class ImagesBulkCollection(
    GenericResource[endpoint.Images],
    CreateMixin[list[request.Image], None],
):
    pass


class ProcessDeduplicationSetAction(
    GenericResource[endpoint.Process],
    ActionMixin[None],
):
    pass


class ApproveDeduplicationSetAction(
    GenericResource[endpoint.Approve],
    ActionMixin[request.Approve],
):
    pass


class RejectDeduplicationSetAction(
    GenericResource[endpoint.Reject],
    ActionMixin[request.Reject],
):
    pass


class DeduplicationSetGroupConfigItem(
    GenericResource[endpoint.DeduplicationSetGroupConfig],
    RetrieveMixin[response.DeduplicationSetGroupConfig],
):
    pass


class DeduplicationSetGroupConfigAction(
    GenericResource[endpoint.DeduplicationSetGroupConfig],
    ActionMixin[request.DeduplicationSetGroupConfig],
):
    pass
