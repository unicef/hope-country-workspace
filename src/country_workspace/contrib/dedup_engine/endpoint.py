from posixpath import sep as posix_sep
from typing import Any
from urllib.parse import urlparse, urlunparse


def to_segments(path: str) -> tuple[str, ...]:
    return tuple(filter(None, path.split(posix_sep)))


def join_paths(*paths: str) -> str:
    segments = sum((to_segments(path) for path in paths), start=())
    return posix_sep.join(segments)


def url_join(url: str, *paths: str) -> str:
    parsed_url = urlparse(url)
    new_path = join_paths(parsed_url.path, *paths)
    new_parsed_url = parsed_url._replace(path=new_path)
    return urlunparse(new_parsed_url)


def ensure_trailing_slash(url: str) -> str:
    if url.endswith(posix_sep):
        return url

    return url + posix_sep


class Endpoint:
    def __init__(self, url: str) -> None:
        self.url = url

    def __str__(self) -> str:
        return ensure_trailing_slash(self.url)


class Images(Endpoint):
    pass


class Process(Endpoint):
    pass


class Approve(Endpoint):
    pass


class Reject(Endpoint):
    pass


class DeduplicationSetGroupConfig(Endpoint):
    pass


class DeduplicationSet(Endpoint):
    @property
    def images_bulk(self) -> Images:
        return Images(url_join(self.url, "images_bulk"))

    @property
    def process(self) -> Process:
        return Process(url_join(self.url, "process"))

    @property
    def approve(self) -> Approve:
        return Approve(url_join(self.url, "approve_or_reject"))

    @property
    def reject(self) -> Reject:
        return Reject(url_join(self.url, "approve_or_reject"))


class DeduplicationSets(Endpoint):
    def deduplication_set(self, id_: Any) -> DeduplicationSet:
        return DeduplicationSet(url_join(self.url, str(id_)))


class DeduplicationSetGroups(Endpoint):
    def config(self, ref_id: Any) -> DeduplicationSetGroupConfig:
        return DeduplicationSetGroupConfig(url_join(self.url, "config", str(ref_id)))


class APIRoot(Endpoint):
    @property
    def deduplication_sets(self) -> DeduplicationSets:
        return DeduplicationSets(url_join(self.url, "deduplication_sets"))

    @property
    def deduplication_set_groups(self) -> DeduplicationSetGroups:
        return DeduplicationSetGroups(url_join(self.url, "deduplication_set_groups"))
