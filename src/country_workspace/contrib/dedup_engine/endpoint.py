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


class DeduplicationSet(Endpoint):
    @property
    def images_bulk(self) -> Images:
        return Images(url_join(self.url, "images_bulk"))

    @property
    def process(self) -> Process:
        return Process(url_join(self.url, "process"))


class DeduplicationSets(Endpoint):
    def deduplication_set(self, id_: Any) -> DeduplicationSet:
        return DeduplicationSet(url_join(self.url, str(id_)))


class APIRoot(Endpoint):
    @property
    def deduplication_sets(self) -> DeduplicationSets:
        return DeduplicationSets(url_join(self.url, "deduplication_sets"))
