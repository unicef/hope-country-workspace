from constance.test.unittest import override_config

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine.client import Client, make_client
from country_workspace.contrib.dedup_engine.response import Status


@pytest.fixture
def client_ctx(mocker: MockerFixture) -> tuple[Client, object, object]:
    session = mocker.MagicMock()
    api_root = mocker.MagicMock()
    return Client("PROGRAM_ID", session, api_root), session, api_root


def test_client_create_deduplication_set(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    collection_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetCollection")
    collection_cls.return_value.create.return_value = {"id": "SET_ID"}
    client, session, api_root = client_ctx

    assert client.create_deduplication_set() == "SET_ID"

    collection_cls.assert_called_once_with(session, api_root.deduplication_sets)
    collection_cls.return_value.create.assert_called_once_with({"reference_pk": "PROGRAM_ID"})


def test_client_create_images(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    collection_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.ImagesBulkCollection")
    client, session, api_root = client_ctx
    images = mocker.Mock()

    client.create_images(images)

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("PROGRAM_ID")
    collection_cls.assert_called_once_with(session, endpoint.return_value.images_bulk)
    collection_cls.return_value.create.assert_called_once_with(images)


def test_client_process(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    action_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.ProcessDeduplicationSetAction")
    client, session, api_root = client_ctx

    client.process()

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("PROGRAM_ID")
    action_cls.assert_called_once_with(session, endpoint.return_value.process)
    action_cls.return_value.call.assert_called_once_with(None)


def test_client_approve(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    action_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.RejectDeduplicationSetAction")
    client, session, api_root = client_ctx

    client.approve()

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("PROGRAM_ID")
    action_cls.assert_called_once_with(session, endpoint.return_value.reject)
    action_cls.return_value.call.assert_called_once_with({"action": "reject", "reference_pks": []})


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ({"status": "STARTED", "duplicates_found": 0}, (Status.STARTED, 0)),
        ({"status": "SUCCESS", "duplicates_found": 42}, (Status.SUCCESS, 42)),
        ({"status": "PENDING", "duplicates_found": 0}, (Status.PENDING, 0)),
        ({"status": "FAILURE", "duplicates_found": 0}, (Status.FAILURE, 0)),
        ({"status": "REVOKED", "duplicates_found": 0}, (Status.REVOKED, 0)),
        ({"status": "Something went wrong", "duplicates_found": 0}, (Status.UNKNOWN, 0)),
        ({}, (Status.UNKNOWN, -1)),
    ],
)
def test_client_status(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    payload: dict[str, object],
    expected: tuple[Status, int],
) -> None:
    item_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetItem")
    item_cls.return_value.retrieve.return_value = payload
    client, session, api_root = client_ctx

    assert client.status() == expected

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("PROGRAM_ID")
    item_cls.assert_called_once_with(session, endpoint.return_value)
    item_cls.return_value.retrieve.assert_called_once_with()


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


def test_client_get_deduplication_set_group_config(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    item_cls_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetGroupConfigItem"
    )
    item_cls_mock.return_value.retrieve.return_value = {"threshold_1": 0.1, "threshold_2": 0.2}
    client, session, api_root = client_ctx

    assert client.get_deduplication_set_group_config() == {
        "threshold_1": 0.1,
        "threshold_2": 0.2,
    }

    api_root.deduplication_set_groups.config.assert_called_once_with("PROGRAM_ID")
    item_cls_mock.assert_called_once_with(
        session,
        api_root.deduplication_set_groups.config.return_value,
    )
    item_cls_mock.return_value.retrieve.assert_called_once_with()


def test_client_post_deduplication_set_group_config(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    action_cls_mock = mocker.patch(
        "country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetGroupConfigAction"
    )
    client, session, api_root = client_ctx
    payload = {"threshold_1": 0.5, "threshold_2": 0.7}

    client.post_deduplication_set_group_config(payload)

    api_root.deduplication_set_groups.config.assert_called_once_with("PROGRAM_ID")
    action_cls_mock.assert_called_once_with(
        session,
        api_root.deduplication_set_groups.config.return_value,
    )
    action_cls_mock.return_value.call.assert_called_once_with(payload)
