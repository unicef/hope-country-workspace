from itertools import batched
from typing import Any
from unittest.mock import Mock

from pytest import raises
from requests.sessions import Session
from requests.exceptions import Timeout

from country_workspace.contrib.kobo.api.client import _handle_paginated_response


SAMPLE_URL = "https://example.com"


def identity(x: Any) -> Any:
    return x


def test_all_data_is_fetched() -> None:
    data = tuple(range(10))
    paged_results = tuple(batched(data, 3))
    urls = tuple(f"{SAMPLE_URL}/{i}" for i in range(len(paged_results)))
    next_urls = urls[1:] + (None,)
    previous_urls = (None,) + urls[:-1]
    responses = tuple(
        {"count": len(data), "next": next_url, "previous": prev_url, "results": results}
        for results, next_url, prev_url in zip(
            paged_results, next_urls, previous_urls, strict=True
        )
    )
    session = Mock(spec=Session)
    session.get.return_value.json.side_effect = responses
    assert (
        tuple(
            _handle_paginated_response(
                session, urls[0], lambda x: x["results"], identity
            )
        )
        == data
    )


def test_error_is_propagated() -> None:
    session = Mock(spec=Session)
    session.get.return_value.raise_for_status.side_effect = Timeout
    with raises(Timeout):
        tuple(_handle_paginated_response(session, SAMPLE_URL, identity, identity))
