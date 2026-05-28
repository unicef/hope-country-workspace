import pytest
from pytest_mock import MockerFixture
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    HTTPError,
    RequestException,
    Timeout as RequestsTimeout,
)

from country_workspace.contrib.dedup_engine.client import Client
from country_workspace.contrib.dedup_engine import resource
from country_workspace.exceptions import RemoteError, RemoteUnavailableError


@pytest.fixture
def client_ctx(mocker: MockerFixture) -> tuple[Client, object, object]:
    session = mocker.MagicMock()
    api_root = mocker.MagicMock()
    client = Client("PROGRAM_ID", session, api_root, deduplication_set_id="SET_ID")
    return client, session, api_root


def test_client_create_deduplication_set(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    collection_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetCollection")
    collection_cls.return_value.create.return_value = payload = {
        "id": "NEW_SET_ID",
        "reference_pk": "PROGRAM_ID",
        "state": "Empty",
    }
    client, session, api_root = client_ctx

    assert client.create_deduplication_set() == payload
    assert client.deduplication_set_id == "NEW_SET_ID"

    collection_cls.assert_called_once_with(session, api_root.deduplication_sets)
    collection_cls.return_value.create.assert_called_once_with({"reference_pk": "PROGRAM_ID", "id": "SET_ID"})


def test_client_create_deduplication_set_without_deduplication_set_id(mocker: MockerFixture) -> None:
    collection_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetCollection")
    collection_cls.return_value.create.return_value = payload = {
        "id": "GENERATED_SET_ID",
        "reference_pk": "PROGRAM_ID",
        "state": "Empty",
    }
    session = mocker.MagicMock()
    api_root = mocker.MagicMock()
    client = Client("PROGRAM_ID", session, api_root)

    assert client.create_deduplication_set() == payload
    assert client.deduplication_set_id == "GENERATED_SET_ID"

    collection_cls.assert_called_once_with(session, api_root.deduplication_sets)
    collection_cls.return_value.create.assert_called_once_with({"reference_pk": "PROGRAM_ID"})


@pytest.mark.parametrize("can_create", [True, False], ids=["can_create", "cannot_create"])
def test_client_can_create_deduplication_set(
    client_ctx: tuple[Client, object, object],
    can_create: bool,
) -> None:
    client, session, api_root = client_ctx
    group_endpoint = api_root.deduplication_set_groups.deduplication_set_group.return_value
    session.get.return_value.json.return_value = {"can_create": can_create}

    assert client.can_create_deduplication_set() is can_create

    api_root.deduplication_set_groups.deduplication_set_group.assert_called_once_with("PROGRAM_ID")
    session.get.assert_called_once_with(str(group_endpoint.status), timeout=resource.TIMEOUT)
    session.get.return_value.raise_for_status.assert_called_once_with()


@pytest.mark.parametrize(
    "can_create",
    ["true", "false", 1, 0, None, {}, []],
    ids=["str_true", "str_false", "int_1", "int_0", "none", "dict", "list"],
)
def test_client_can_create_deduplication_set_rejects_invalid_value(
    client_ctx: tuple[Client, object, object],
    can_create: object,
) -> None:
    client, session, _ = client_ctx
    session.get.return_value.json.return_value = {"can_create": can_create}

    with pytest.raises(RemoteError, match="invalid can_create value"):
        client.can_create_deduplication_set()

    session.get.return_value.raise_for_status.assert_called_once_with()


def test_client_create_images(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    collection_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.ImagesCollection")
    collection_cls.return_value.create.return_value = payload = [{"filename": "a.jpg", "reference_pk": "1"}]
    client, session, api_root = client_ctx
    images = [{"filename": "a.jpg", "reference_pk": "1"}]

    assert client.create_images(images) == payload

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("SET_ID")
    collection_cls.assert_called_once_with(session, endpoint.return_value.images)
    collection_cls.return_value.create.assert_called_once_with(images)


@pytest.mark.parametrize(
    ("method_name", "patch_target", "endpoint_attr"),
    [
        (
            "ready",
            "country_workspace.contrib.dedup_engine.client.resource.ReadyDeduplicationSetAction",
            "ready",
        ),
        (
            "reject",
            "country_workspace.contrib.dedup_engine.client.resource.RejectDeduplicationSetAction",
            "reject",
        ),
        (
            "approve",
            "country_workspace.contrib.dedup_engine.client.resource.ApproveDeduplicationSetAction",
            "approve",
        ),
    ],
    ids=["ready", "reject", "approve"],
)
def test_client_actions(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    method_name: str,
    patch_target: str,
    endpoint_attr: str,
) -> None:
    action_cls = mocker.patch(patch_target)
    client, session, api_root = client_ctx

    getattr(client, method_name)()

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("SET_ID")
    action_cls.assert_called_once_with(session, getattr(endpoint.return_value, endpoint_attr))
    action_cls.return_value.call.assert_called_once_with()


@pytest.mark.parametrize(
    ("encode_only", "params"),
    [(False, None), (True, {"encode_only": "true"})],
    ids=["default", "encode_only"],
)
def test_client_process(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    encode_only: bool,
    params: dict[str, str] | None,
) -> None:
    action_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.ProcessDeduplicationSetAction")
    client, session, api_root = client_ctx

    client.process(encode_only=encode_only)

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("SET_ID")
    action_cls.assert_called_once_with(session, endpoint.return_value.process)
    action_cls.return_value.call.assert_called_once_with(params=params)


def test_client_retrieve_deduplication_set(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    item_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetItem")
    item_cls.return_value.retrieve.return_value = payload = {
        "created_at": "2026-04-13T00:00:00Z",
        "findings_count": 2,
        "name": None,
        "reference_pk": "PROGRAM_ID",
        "state": "Ready",
        "updated_at": "2026-04-13T00:00:00Z",
    }
    client, session, api_root = client_ctx

    assert client.retrieve_deduplication_set() == payload

    endpoint = api_root.deduplication_sets.deduplication_set
    endpoint.assert_called_once_with("SET_ID")
    item_cls.assert_called_once_with(session, endpoint.return_value)
    item_cls.return_value.retrieve.assert_called_once_with()


@pytest.mark.parametrize(
    ("client_method", "resource_method", "payload", "expected_args"),
    [
        (
            "get_deduplication_set_group_config",
            "retrieve",
            {
                "face_detection_confidence_threshold": 0.1,
                "duplicate_confidence_threshold": 0.2,
            },
            (),
        ),
        (
            "post_deduplication_set_group_config",
            "update",
            {
                "face_detection_confidence_threshold": 0.5,
                "duplicate_confidence_threshold": 0.7,
            },
            (
                {
                    "face_detection_confidence_threshold": 0.5,
                    "duplicate_confidence_threshold": 0.7,
                },
            ),
        ),
    ],
    ids=["get_group_config", "post_group_config"],
)
def test_client_deduplication_set_group_config(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    client_method: str,
    resource_method: str,
    payload: dict[str, float],
    expected_args: tuple[dict[str, float], ...],
) -> None:
    item_cls = mocker.patch("country_workspace.contrib.dedup_engine.client.resource.DeduplicationSetGroupConfigItem")
    getattr(item_cls.return_value, resource_method).return_value = payload
    client, session, api_root = client_ctx

    if expected_args:
        assert getattr(client, client_method)(payload) == payload
    else:
        assert getattr(client, client_method)() == payload

    group_endpoint = api_root.deduplication_set_groups.deduplication_set_group.return_value
    api_root.deduplication_set_groups.deduplication_set_group.assert_called_once_with("PROGRAM_ID")
    item_cls.assert_called_once_with(session, group_endpoint.config)
    getattr(item_cls.return_value, resource_method).assert_called_once_with(*expected_args)


def test_client_requires_deduplication_set_id(mocker: MockerFixture) -> None:
    client = Client("PROGRAM_ID", mocker.MagicMock(), mocker.MagicMock())

    with pytest.raises(RemoteError, match="deduplication_set_id is not set"):
        client.retrieve_deduplication_set()


@pytest.mark.parametrize(
    "exc",
    [RequestsConnectionError("boom"), RequestsTimeout("boom")],
    ids=["connection_error", "timeout"],
)
def test_client_request_wraps_connection_errors(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    exc: Exception,
) -> None:
    client, _, _ = client_ctx
    fn = mocker.Mock(side_effect=exc)

    with pytest.raises(RemoteUnavailableError, match=r"op failed: boom"):
        client._request("op", fn)

    fn.assert_called_once_with()


@pytest.mark.parametrize(
    ("status_code", "text", "expected_exception"),
    [
        (404, "not found", RemoteError),
        (503, "err", RemoteUnavailableError),
    ],
    ids=["4xx", "5xx"],
)
def test_client_request_wraps_http_errors(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    status_code: int,
    text: str,
    expected_exception: type[Exception],
) -> None:
    client, _, _ = client_ctx
    response = mocker.MagicMock(status_code=status_code, text=text)
    response.request.method = "GET"
    response.request.url = "https://de/item"
    exc = HTTPError("boom", response=response)
    fn = mocker.Mock(side_effect=exc)

    with pytest.raises(
        expected_exception,
        match=rf"GET https://de/item failed: boom.*Status: {status_code}.*Response: {text}",
    ):
        client._request("op", fn)

    fn.assert_called_once_with()


@pytest.mark.parametrize(
    "exc",
    [ValueError("boom"), KeyError("boom"), TypeError("boom")],
    ids=["value_error", "key_error", "type_error"],
)
def test_client_request_wraps_parse_errors(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
    exc: Exception,
) -> None:
    client, _, _ = client_ctx
    fn = mocker.Mock(side_effect=exc)

    with pytest.raises(RemoteError, match=r"op failed: .*boom"):
        client._request("op", fn)

    fn.assert_called_once_with()


def test_client_request_wraps_request_exception(
    mocker: MockerFixture,
    client_ctx: tuple[Client, object, object],
) -> None:
    client, _, _ = client_ctx
    response = mocker.MagicMock(status_code=500, text="err")
    response.request.method = "POST"
    response.request.url = "https://de/images"
    exc = RequestException("boom")
    exc.response = response
    fn = mocker.Mock(side_effect=exc)

    with pytest.raises(
        RemoteUnavailableError,
        match=r"POST https://de/images failed: boom.*Status: 500.*Response: err",
    ):
        client._request("op", fn)

    fn.assert_called_once_with()
