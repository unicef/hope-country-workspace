from constance.test.unittest import override_config

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.client import make_client, Client
from country_workspace.contrib.dedup_engine.response import Status


def test_client_deduplicate(mocker: MockerFixture) -> None:
    program_id = "PROGRAM_ID"
    session_mock = mocker.Mock()
    api_root_mock = mocker.Mock()
    images_mock = mocker.Mock()
    settings_mock = mocker.Mock()

    deduplication_set_collection_class_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetCollection"
    )
    images_bulk_collection_class_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.ImagesBulkCollection"
    )
    process_deduplication_set_action_class_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.ProcessDeduplicationSetAction"
    )

    client = Client(program_id, session_mock, api_root_mock)
    client.deduplicate(images_mock, settings_mock)

    deduplication_set_collection_class_mock.assert_called_once_with(session_mock, api_root_mock.deduplication_sets)
    deduplication_set_collection_mock = deduplication_set_collection_class_mock.return_value
    deduplication_set_collection_mock.create.assert_called_once_with(
        {
            "reference_pk": program_id,
            "settings": settings_mock,
        }
    )
    deduplication_set_endpoint_mock = api_root_mock.deduplication_sets.deduplication_set
    deduplication_set_endpoint_mock.assert_has_calls([mocker.call(program_id), mocker.call(program_id)])
    assert deduplication_set_endpoint_mock.call_count == 2

    images_bulk_collection_class_mock.assert_called_once_with(
        session_mock, deduplication_set_endpoint_mock.return_value.images_bulk
    )
    images_bulk_collection_mock = images_bulk_collection_class_mock.return_value
    images_bulk_collection_mock.create.assert_called_once_with(images_mock)
    process_deduplication_set_action_class_mock.assert_called_once_with(
        session_mock, deduplication_set_endpoint_mock.return_value.process
    )
    process_deduplication_set_action_mock = process_deduplication_set_action_class_mock.return_value
    process_deduplication_set_action_mock.call.assert_called_once_with(None)


@pytest.mark.parametrize(
    ("deduplication_set_status", "duplicates_found", "expected_status", "expected_duplicates_found"),
    [
        ("STARTED", 0, Status.STARTED, 0),
        ("SUCCESS", 42, Status.SUCCESS, 42),
        ("PENDING", 0, Status.PENDING, 0),
        ("FAILURE", 0, Status.FAILURE, 0),
        ("REVOKED", 0, Status.REVOKED, 0),
        ("Something went wrong", 0, Status.UNKNOWN, 0),
    ],
)
def test_client_status(
    mocker: MockerFixture,
    deduplication_set_status: str,
    duplicates_found: int,
    expected_status: Status,
    expected_duplicates_found: int,
) -> None:
    program_id = "PROGRAM_ID"
    session_mock = mocker.MagicMock()
    api_root_mock = mocker.Mock()

    deduplication_set_item_class_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetItem"
    )
    deduplication_set_item_mock = deduplication_set_item_class_mock.return_value
    deduplication_set_data = deduplication_set_item_mock.retrieve.return_value
    deduplication_set_data.__getitem__.side_effect = deduplication_set_status, duplicates_found

    client = Client(program_id, session_mock, api_root_mock)

    assert client.status() == (expected_status, expected_duplicates_found)
    deduplication_set_endpoint_mock = api_root_mock.deduplication_sets.deduplication_set
    deduplication_set_endpoint_mock.assert_called_once_with(program_id)
    deduplication_set_item_mock.retrieve.assert_called_once_with()
    deduplication_set_data.__getitem__.assert_has_calls([mocker.call("status"), mocker.call("duplicates_found")])


def test_make_client(mocker: MockerFixture) -> None:
    session_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Session")
    auth_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Auth")
    client_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.Client")
    http_adapter_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.HTTPAdapter")
    api_root_class_mock = mocker.patch("country_workspace.contrib.dedup_engine.client.endpoint.APIRoot")

    with (
        override_config(DEDUP_API_URL=(url := "https://test.org")),
        override_config(DEDUP_API_TOKEN=(token := "token")),
    ):
        with make_client(program_id := "PROGRAM_ID") as client:
            assert client is client_class_mock.return_value

    session_class_mock.assert_called_once_with()
    session = session_class_mock.return_value.__enter__.return_value
    session.mount.assert_called_once_with("https://", http_adapter_class_mock.return_value)
    assert session.auth is auth_class_mock.return_value

    http_adapter_class_mock.assert_called_once_with(max_retries=3)
    auth_class_mock.assert_called_once_with(token)
    api_root_class_mock.assert_called_once_with(url)
    client_class_mock.assert_called_once_with(program_id, session, api_root_class_mock.return_value)
