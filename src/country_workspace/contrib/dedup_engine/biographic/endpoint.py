from ..endpoint import Endpoint, EndpointId, url_join


class Records(Endpoint): ...


class Process(Endpoint): ...


class Findings(Endpoint): ...


class Approve(Endpoint): ...


class Reject(Endpoint): ...


class Cancel(Endpoint): ...


class Dataset(Endpoint):
    @property
    def records(self) -> Records:
        return Records(url_join(self.url, "records"))

    @property
    def process(self) -> Process:
        return Process(url_join(self.url, "process"))

    @property
    def findings(self) -> Findings:
        return Findings(url_join(self.url, "findings"))

    @property
    def approve(self) -> Approve:
        return Approve(url_join(self.url, "approve"))

    @property
    def reject(self) -> Reject:
        return Reject(url_join(self.url, "reject"))

    @property
    def cancel(self) -> Cancel:
        return Cancel(url_join(self.url, "cancel"))


class Datasets(Endpoint):
    def dataset(self, dataset_id: EndpointId) -> Dataset:
        return Dataset(url_join(self.url, str(dataset_id)))


class APIRoot(Endpoint):
    def datasets(self, business_area_slug: str, program_code: str) -> Datasets:
        return Datasets(url_join(self.url, "api", "biographic", business_area_slug, program_code, "datasets"))
