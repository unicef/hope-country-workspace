import pytest

from country_workspace.contrib.dedup_engine.endpoint import (
    APIRoot,
    Approve,
    DeduplicationSet,
    DeduplicationSetGroup,
    DeduplicationSetGroupConfig,
    DeduplicationSetGroups,
    DeduplicationSetGroupStatus,
    DeduplicationSets,
    Endpoint,
    Images,
    Process,
    Ready,
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
    endpoint = DeduplicationSet("https://example.com/deduplication_sets/set-id")
    images = endpoint.images
    ready = endpoint.ready
    process = endpoint.process
    reject = endpoint.reject
    approve = endpoint.approve

    assert images.url == "https://example.com/deduplication_sets/set-id/images"
    assert ready.url == "https://example.com/deduplication_sets/set-id/ready"
    assert process.url == "https://example.com/deduplication_sets/set-id/process"
    assert reject.url == "https://example.com/deduplication_sets/set-id/reject"
    assert approve.url == "https://example.com/deduplication_sets/set-id/approve"

    assert isinstance(images, Images)
    assert isinstance(ready, Ready)
    assert isinstance(process, Process)
    assert isinstance(reject, Reject)
    assert isinstance(approve, Approve)


def test_deduplication_sets_endpoint() -> None:
    endpoint = DeduplicationSets("https://example.com/deduplication_sets").deduplication_set("set-id")

    assert isinstance(endpoint, DeduplicationSet)
    assert endpoint.url == "https://example.com/deduplication_sets/set-id"


def test_deduplication_set_group_endpoints() -> None:
    endpoint = DeduplicationSetGroup("https://example.com/deduplication_set_groups/program-id")
    config = endpoint.config
    status = endpoint.status

    assert config.url == "https://example.com/deduplication_set_groups/program-id/config"
    assert status.url == "https://example.com/deduplication_set_groups/program-id/status"

    assert isinstance(config, DeduplicationSetGroupConfig)
    assert isinstance(status, DeduplicationSetGroupStatus)


def test_deduplication_set_groups_endpoint() -> None:
    endpoint = DeduplicationSetGroups("https://example.com/deduplication_set_groups").deduplication_set_group(
        "program-id"
    )

    assert isinstance(endpoint, DeduplicationSetGroup)
    assert endpoint.url == "https://example.com/deduplication_set_groups/program-id"


def test_api_root_endpoints() -> None:
    api_root = APIRoot("https://example.com/api")
    deduplication_sets = api_root.deduplication_sets
    deduplication_set_groups = api_root.deduplication_set_groups

    assert isinstance(deduplication_sets, DeduplicationSets)
    assert deduplication_sets.url == "https://example.com/api/deduplication_sets"

    assert isinstance(deduplication_set_groups, DeduplicationSetGroups)
    assert deduplication_set_groups.url == "https://example.com/api/deduplication_set_groups"
