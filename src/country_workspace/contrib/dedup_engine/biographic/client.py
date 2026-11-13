from dataclasses import dataclass
from functools import partial

from requests import Session

from country_workspace.exceptions import RemoteError

from ..client import BaseClient
from ..resource import UPLOAD_TIMEOUT
from . import endpoint, request, resource, response


FINDINGS_PAGE_SIZE = 10_000


@dataclass(slots=True)
class Client(BaseClient):
    """Client of the DedupEngine biographic API for one dataset of a program.

    Country Workspace assigns the dataset id (the id of the RDP operation) and sends it on `create_dataset`.
    """

    business_area_slug: str
    program_code: str
    session: Session
    api_root: endpoint.APIRoot
    dataset_id: str

    @property
    def datasets_endpoint(self) -> endpoint.Datasets:
        return self.api_root.datasets(self.business_area_slug, self.program_code)

    @property
    def dataset_endpoint(self) -> endpoint.Dataset:
        return self.datasets_endpoint.dataset(self.dataset_id)

    def create_dataset(self, notification_url: str | None = None) -> response.Dataset:
        collection = resource.DatasetCollection(self.session, self.datasets_endpoint)
        payload: request.CreateDataset = {"dataset_id": self.dataset_id}
        if notification_url:
            payload["notification_url"] = notification_url
            payload["notify"] = True

        return self._request("create_dataset", lambda: collection.create(payload))

    def retrieve_dataset(self) -> response.Dataset:
        item = resource.DatasetItem(self.session, self.dataset_endpoint)
        return self._request("retrieve_dataset", item.retrieve)

    def retrieve_dataset_or_none(self) -> response.Dataset | None:
        item = resource.DatasetItem(self.session, self.dataset_endpoint)
        return self._request("retrieve_dataset", item.retrieve_or_none)

    def create_records(self, records: list[request.Record]) -> response.RecordsBatchResult:
        """Add a batch of people to a pending dataset. Sending a `reference_pk` again replaces its record."""
        collection = resource.RecordsCollection(self.session, self.dataset_endpoint.records)
        return self._request(
            "create_records",
            partial(collection.create, {"records": records}, timeout=UPLOAD_TIMEOUT),
        )

    def process(self, overrides: request.ProcessOverrides | None = None) -> response.Dataset:
        """Start (or retry) indexing and scoring; `overrides` apply to this run only."""
        action = resource.DatasetAction(self.session, self.dataset_endpoint.process)
        return self._request("process", partial(action.call, overrides or {}))

    def retrieve_findings(self) -> list[response.Finding]:
        """Retrieve every finding of the dataset and check that none is missing."""
        collection = resource.FindingsCollection(self.session, self.dataset_endpoint.findings)
        findings: list[response.Finding] = []
        expected: int | None = None
        page = 1

        while True:
            result = self._request(
                "retrieve_findings",
                partial(collection.list, params={"page": str(page), "page_size": str(FINDINGS_PAGE_SIZE)}),
            )
            expected = result["count"] if expected is None else expected
            findings.extend(result["results"])
            if result.get("next") is None:
                break
            page += 1

        if len(findings) != expected:
            raise RemoteError(f"DedupEngine: findings count={expected!r}, received={len(findings)}")
        return findings

    def approve(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.approve)
        return self._request("approve", action.call)

    def reject(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.reject)
        return self._request("reject", action.call)

    def cancel(self) -> response.Dataset:
        action = resource.DatasetAction(self.session, self.dataset_endpoint.cancel)
        return self._request("cancel", action.call)
