import re
from typing import TYPE_CHECKING

import pytest
from constance.test import override_config

from country_workspace.contrib.dedup.client import DeduplicationClient
from country_workspace.exceptions import RemoteError

if TYPE_CHECKING:
    import responses

DUMMY_TOKEN = "dummy_token"
DEDUP_API_URL = "https://dedup-dummy.org/api/rest"


@pytest.fixture
def client() -> DeduplicationClient:
    return DeduplicationClient(token=DUMMY_TOKEN, api_url=DEDUP_API_URL)


def test_create_or_update_deduplication_set(
    mocked_responses: "responses.RequestsMock", client: DeduplicationClient
) -> None:
    expected = {"reference_pk": "cw-batch-1"}
    mocked_responses.add(
        mocked_responses.POST,
        client.get_url("deduplicationsets/"),
        json=expected,
        status=201,
    )

    result = client.upsert_deduplication_set(reference_pk="cw-batch-1", name="Batch 1", settings={"batch_id": 1})

    assert result == expected


def test_bulk_add_images(mocked_responses: "responses.RequestsMock", client: DeduplicationClient) -> None:
    expected = [{"reference_pk": "1", "filename": "https://cdn.example/photo.jpg"}]
    mocked_responses.add(
        mocked_responses.POST,
        client.get_url("deduplicationsets/cw-batch-1/images_bulk/"),
        json=expected,
        status=201,
    )

    result = client.bulk_add_images("cw-batch-1", expected)

    assert result == expected


def test_process(mocked_responses: "responses.RequestsMock", client: DeduplicationClient) -> None:
    expected = {"message": "started"}
    mocked_responses.add(
        mocked_responses.POST,
        client.get_url("deduplicationsets/cw-batch-1/process/"),
        json=expected,
        status=200,
    )

    result = client.process("cw-batch-1")

    assert result == expected


@override_config(DEDUP_API_URL=DEDUP_API_URL, DEDUP_API_TOKEN=DUMMY_TOKEN)
def test_post_failure_status_code(mocked_responses: "responses.RequestsMock") -> None:
    client = DeduplicationClient()
    mocked_responses.add(
        mocked_responses.POST,
        client.get_url("deduplicationsets/"),
        json={"error": "bad request"},
        status=400,
    )

    with pytest.raises(RemoteError, match=re.escape("HTTP error posting to")):
        client.upsert_deduplication_set(reference_pk="cw-batch-1")
