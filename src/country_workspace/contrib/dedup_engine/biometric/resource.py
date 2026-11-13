from ..resource import ActionMixin, CreateMixin, DeleteMixin, GenericResource, ListMixin, RetrieveMixin, UpdateMixin
from . import endpoint, request, response


class DeduplicationSetGroupConfigItem(
    GenericResource[endpoint.DeduplicationSetGroupConfig],
    RetrieveMixin[response.DeduplicationSetGroupConfig],
    UpdateMixin[request.DeduplicationSetGroupConfig, response.DeduplicationSetGroupConfig],
): ...


class DeduplicationSetGroupItem(
    GenericResource[endpoint.DeduplicationSetGroup],
    DeleteMixin,
): ...


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


class FindingsCollection(
    GenericResource[endpoint.Findings],
    ListMixin[response.PaginatedFindings],
): ...


class ApproveDeduplicationSetAction(
    GenericResource[endpoint.Approve],
    ActionMixin[None],
): ...


class RejectDeduplicationSetAction(
    GenericResource[endpoint.Reject],
    ActionMixin[None],
): ...
