import pytest

from country_workspace.contrib.dedup_engine.endpoint import (
    APIRoot,
    Approve,
    DeduplicationSet,
    DeduplicationSetGroupConfig,
    DeduplicationSetGroups,
    DeduplicationSets,
    Endpoint,
    Images,
    Process,
    Reject,
    ensure_trailing_slash,
    join_paths,
    to_segments,
    url_join,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("", ()),
        ("/", ()),
        ("foo", ("foo",)),
        ("/foo", ("foo",)),
        ("foo/", ("foo",)),
        ("/foo/", ("foo",)),
        ("foo/bar", ("foo", "bar")),
        ("/foo/bar", ("foo", "bar")),
        ("foo/bar/", ("foo", "bar")),
        ("/foo/bar/", ("foo", "bar")),
    ],
)
def test_to_segments(path: str, expected: tuple[str, ...]) -> None:
    assert to_segments(path) == expected


@pytest.mark.parametrize(
    ("paths", "expected"),
    [
        ((), ""),
        (("",), ""),
        (("", ""), ""),
        (("foo",), "foo"),
        (("foo", "bar"), "foo/bar"),
    ],
)
def test_join_paths(paths: tuple[str, ...], expected: str) -> None:
    assert join_paths(*paths) == expected


@pytest.mark.parametrize(
    ("url", "paths", "expected"),
    [
        ("https://example.com", (), "https://example.com"),
        ("https://example.com/", (), "https://example.com"),
        ("https://example.com", ("foo",), "https://example.com/foo"),
        ("https://example.com/", ("foo",), "https://example.com/foo"),
        ("https://example.com", ("/foo",), "https://example.com/foo"),
        ("https://example.com", ("foo/",), "https://example.com/foo"),
        ("https://example.com", ("/foo/",), "https://example.com/foo"),
        ("https://example.com", ("foo", "bar"), "https://example.com/foo/bar"),
        ("https://example.com", ("foo/", "bar"), "https://example.com/foo/bar"),
        ("https://example.com", ("foo", "/bar"), "https://example.com/foo/bar"),
        ("https://example.com", ("foo", "bar/"), "https://example.com/foo/bar"),
        ("https://example.com", ("foo", "/bar/"), "https://example.com/foo/bar"),
    ],
)
def test_url_join(url: str, paths: tuple[str, ...], expected: str) -> None:
    assert url_join(url, *paths) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com", "https://example.com/"),
        ("https://example.com/", "https://example.com/"),
    ],
)
def test_ensure_trailing_slash(url: str, expected: str) -> None:
    assert ensure_trailing_slash(url) == expected


def test_endpoint_str() -> None:
    assert str(Endpoint("https://example.com/foo")) == "https://example.com/foo/"


def test_deduplication_set_endpoints() -> None:
    endpoint = DeduplicationSet("https://example.com/deduplication_sets/program-id")

    assert endpoint.images_bulk.url == "https://example.com/deduplication_sets/program-id/images_bulk"
    assert endpoint.process.url == "https://example.com/deduplication_sets/program-id/process"
    assert endpoint.approve.url == "https://example.com/deduplication_sets/program-id/approve_or_reject"
    assert endpoint.reject.url == "https://example.com/deduplication_sets/program-id/approve_or_reject"

    assert isinstance(endpoint.images_bulk, Images)
    assert isinstance(endpoint.process, Process)
    assert isinstance(endpoint.approve, Approve)
    assert isinstance(endpoint.reject, Reject)


def test_deduplication_sets_endpoint() -> None:
    endpoint = DeduplicationSets("https://example.com/deduplication_sets").deduplication_set("program-id")

    assert isinstance(endpoint, DeduplicationSet)
    assert endpoint.url == "https://example.com/deduplication_sets/program-id"


def test_deduplication_set_groups_config_endpoint() -> None:
    endpoint = DeduplicationSetGroups("https://example.com/deduplication_set_groups").config("program-id")

    assert isinstance(endpoint, DeduplicationSetGroupConfig)
    assert endpoint.url == "https://example.com/deduplication_set_groups/config/program-id"


def test_api_root_endpoints() -> None:
    api_root = APIRoot("https://example.com/api")

    assert isinstance(api_root.deduplication_sets, DeduplicationSets)
    assert api_root.deduplication_sets.url == "https://example.com/api/deduplication_sets"

    assert isinstance(api_root.deduplication_set_groups, DeduplicationSetGroups)
    assert api_root.deduplication_set_groups.url == "https://example.com/api/deduplication_set_groups"
