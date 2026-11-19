from ..endpoint import Endpoint, EndpointId, url_join


class DeduplicationSetGroupConfig(Endpoint): ...


class DeduplicationSetGroupStatus(Endpoint): ...


class DeduplicationSetGroup(Endpoint):
    @property
    def config(self) -> DeduplicationSetGroupConfig:
        return DeduplicationSetGroupConfig(url_join(self.url, "config"))

    @property
    def status(self) -> DeduplicationSetGroupStatus:
        return DeduplicationSetGroupStatus(url_join(self.url, "status"))


class DeduplicationSetGroups(Endpoint):
    def deduplication_set_group(self, reference_id: EndpointId) -> DeduplicationSetGroup:
        return DeduplicationSetGroup(url_join(self.url, str(reference_id)))


class Images(Endpoint): ...


class Ready(Endpoint): ...


class Process(Endpoint): ...


class Findings(Endpoint): ...


class Approve(Endpoint): ...


class Reject(Endpoint): ...


class DeduplicationSet(Endpoint):
    @property
    def images(self) -> Images:
        return Images(url_join(self.url, "images"))

    @property
    def ready(self) -> Ready:
        return Ready(url_join(self.url, "ready"))

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


class DeduplicationSets(Endpoint):
    def deduplication_set(self, id_: EndpointId) -> DeduplicationSet:
        return DeduplicationSet(url_join(self.url, str(id_)))


class APIRoot(Endpoint):
    @property
    def deduplication_sets(self) -> DeduplicationSets:
        return DeduplicationSets(url_join(self.url, "deduplication_sets"))

    @property
    def deduplication_set_groups(self) -> DeduplicationSetGroups:
        return DeduplicationSetGroups(url_join(self.url, "deduplication_set_groups"))
