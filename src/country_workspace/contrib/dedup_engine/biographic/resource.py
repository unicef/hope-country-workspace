from ..endpoint import Endpoint
from ..resource import CreateMixin, GenericResource, ListMixin, RetrieveMixin, TIMEOUT
from . import endpoint, request, response


class DatasetCollection(
    GenericResource[endpoint.Datasets],
    CreateMixin[request.CreateDataset, response.Dataset],
): ...


class DatasetItem(
    GenericResource[endpoint.Dataset],
    RetrieveMixin[response.Dataset],
): ...


class RecordsCollection(
    GenericResource[endpoint.Records],
    CreateMixin[request.RecordsBatch, response.RecordsBatchResult],
): ...


class FindingsCollection(
    GenericResource[endpoint.Findings],
    ListMixin[response.PaginatedFindings],
): ...


class DatasetAction(GenericResource[Endpoint]):
    def call(self, body: request.ProcessOverrides | None = None) -> response.Dataset:
        kwargs = {"json": body} if body is not None else {}
        result = self.session.post(str(self.endpoint), timeout=TIMEOUT, **kwargs)
        result.raise_for_status()
        return result.json()
