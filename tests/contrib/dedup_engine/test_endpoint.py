import pytest

from country_workspace.contrib.dedup_engine.endpoint import to_segments, join_paths, url_join, ensure_trailing_slash


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


def test_ensure_trailing_slash() -> None:
    assert ensure_trailing_slash("https://example.com") == "https://example.com/"
