import pytest

from country_workspace.contrib.kobo.sync import is_submission_data_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("", False),
        ("https://example.com", False),
        ("https://example.com/api/v2/assets/abc42/data/", True),
        ("https://example.com/api/v2/assets/abc42/data", True),
        ("https://example.com/api/v2/assets/abc42/data/?format=json", True),
        ("https://example.com/api/v2/assets/abc42/files/", False),
    ],
)
def test_is_submission_data_url(url: str, expected: bool) -> None:
    assert is_submission_data_url(url) is expected
