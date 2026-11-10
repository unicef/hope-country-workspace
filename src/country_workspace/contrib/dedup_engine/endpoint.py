from posixpath import sep as posix_sep
from urllib.parse import urlparse, urlunparse
from uuid import UUID

type EndpointId = str | int | UUID


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
