from country_workspace.contrib.kobo.api.common import CachedResponse


def test_cached_response() -> None:
    cached_response = CachedResponse(
        {
            "json": (expected_json := {"foo": "bar"}),
            "status_code": (expected_status_code := 42),
        }
    )
    assert cached_response.json() == expected_json
    assert cached_response.status_code == expected_status_code
    # we should not get an exception here
    cached_response.raise_for_status()
