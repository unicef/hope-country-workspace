from dataclasses import dataclass
from functools import partial
from uuid import UUID

from requests import Session

from country_workspace.exceptions import RemoteError

from ..client import BaseClient
from . import endpoint, request, resource, response


@dataclass(slots=True)
class Client(BaseClient):
    business_area_slug: str
    program_code: str
    dataset_id: UUID
    session: Session
    api_root: endpoint.APIRoot

    @property
    def datasets_endpoint(self) -> endpoint.Datasets:
        return self.api_root.datasets(self.business_area_slug, self.program_code)

    @property
    def dataset_endpoint(self) -> endpoint.Dataset:
        return self.datasets_endpoint.dataset(self.dataset_id)

    def create_dataset(self, notification_url: str | None = None) -> response.Dataset:
        dataset_id = str(self.dataset_id)
        collection = resource.DatasetCollection(self.session, self.datasets_endpoint)
        payload: request.CreateDataset = {"dataset_id": dataset_id}
        if notification_url:
            payload["notification_url"] = notification_url
            payload["notify"] = True

        def create() -> response.Dataset:
            dataset = collection.create(payload)
            if (created_id := dataset.get("dataset_id")) != dataset_id:
                raise RemoteError(f"DedupEngine: dataset id mismatch: expected={dataset_id}, got={created_id!r}")
            return dataset

        return self._request("create_dataset", create)

    def retrieve_dataset(self) -> response.Dataset:
        item = resource.DatasetItem(self.session, self.dataset_endpoint)
        return self._request("retrieve_dataset", item.retrieve)

    def retrieve_dataset_or_none(self) -> response.Dataset | None:
        item = resource.DatasetItem(self.session, self.dataset_endpoint)
        return self._request("retrieve_dataset", item.retrieve_or_none)

    def create_records(self, records: list[request.Record]) -> response.RecordsBatchResult:
        collection = resource.RecordsCollection(self.session, self.dataset_endpoint.records)
        return self._request("create_records", lambda: collection.create({"records": records}))

    def process(self, overrides: request.ProcessOverrides | None = None) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.process)
        return self._request("process", partial(action.call, overrides))

    def retrieve_findings(self) -> list[response.Finding]:
        collection = resource.FindingsCollection(self.session, self.dataset_endpoint.findings)
        findings: list[response.Finding] = []
        page = 1

        while True:
            result = self._request(
                "retrieve_findings",
                partial(collection.list, params={"page": str(page)}),
            )
            findings.extend(result["results"])
            if result.get("next") is None:
                return findings
            page += 1

    def approve(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.approve)
        return self._request("approve", action.call)

    def reject(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.reject)
        return self._request("reject", action.call)

    def cancel(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.cancel)
        return self._request("cancel", action.call)
