import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.endpoint import (
    to_segments,
    join_paths,
    url_join,
    ensure_trailing_slash,
    Endpoint,
    DeduplicationSet,
    DeduplicationSets,
    APIRoot,
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
def test_urljoin(url: str, paths: tuple[str, ...], expected: str) -> None:
    assert url_join(url, *paths) == expected


@pytest.mark.parametrize("url", ["https://example.com", "https://example.com/"])
def test_ensure_trailing_slash(url: str) -> None:
    assert ensure_trailing_slash(url) == "https://example.com/"


@pytest.mark.parametrize("url", ["https://example.com", "https://example.com/"])
def test_endpoint_class(url: str) -> None:
    assert str(Endpoint(url)) == "https://example.com/"


def test_deduplication_set_class(mocker: MockerFixture) -> None:
    url_join_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.url_join")
    images_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.Images")
    process_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.Process")
    approve_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.Approve")
    reject_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.Reject")
    url_mock = mocker.Mock()
    deduplication_set = DeduplicationSet(url_mock)

    assert deduplication_set.images_bulk == images_class_mock.return_value
    images_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_once_with(url_mock, "images_bulk")

    assert deduplication_set.process == process_class_mock.return_value
    process_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_with(url_mock, "process")

    assert deduplication_set.approve == approve_class_mock.return_value
    approve_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_with(url_mock, "approve_or_reject")

    assert deduplication_set.reject == reject_class_mock.return_value
    reject_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_with(url_mock, "approve_or_reject")


def test_deduplication_sets_class(mocker: MockerFixture) -> None:
    url_join_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.url_join")
    deduplication_set_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.DeduplicationSet")
    url_mock = mocker.Mock()
    id_mock = mocker.Mock()
    deduplication_sets = DeduplicationSets(url_mock)

    assert deduplication_sets.deduplication_set(id_mock) == deduplication_set_class_mock.return_value
    deduplication_set_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_once_with(url_mock, str(id_mock))


def test_api_root_class(mocker: MockerFixture) -> None:
    url_join_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.url_join")
    deduplication_sets_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.endpoint.DeduplicationSets")
    url_mock = mocker.Mock()
    api_root = APIRoot(url_mock)

    assert api_root.deduplication_sets == deduplication_sets_class_mock.return_value
    deduplication_sets_class_mock.assert_called_once_with(url_join_mock.return_value)
    url_join_mock.assert_called_once_with(url_mock, "deduplication_sets")
