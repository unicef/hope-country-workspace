from http import HTTPStatus
from typing import Any

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.client import HopeClient
from country_workspace.contrib.hope.exceptions import HopeResponseError
from country_workspace.contrib.hope.rdi import HopeApi, HopeRdiResetUnconfirmedError, RdiResetResult
from country_workspace.exceptions import RemoteError


MOD = "country_workspace.contrib.hope.rdi.api"

CO_SLUG = "CO"
RDI_ID = "RID"
CALLBACK_URL = "https://cw.example/callback/"
RDI_URL = f"{CO_SLUG}/rdi/{RDI_ID}"


@pytest.fixture
def hope_api(mocker: MockerFixture, hope_client: HopeClient) -> HopeApi:
    mocker.patch(f"{MOD}.HopeClient", return_value=hope_client)
    return HopeApi(co_slug=CO_SLUG)


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(("create_rdi", ({"a": 1},), f"{CO_SLUG}/rdi/create/", {"a": 1}), id="create"),
        pytest.param(
            ("post_individuals", (RDI_ID, [{"x": 1}]), f"{RDI_URL}/push/lax/individuals/", [{"x": 1}]),
            id="individuals",
        ),
        pytest.param(
            ("post_households", (RDI_ID, [{"x": 1}]), f"{RDI_URL}/push/lax/households/", [{"x": 1}]),
            id="households",
        ),
        pytest.param(
            ("post_people", (RDI_ID, [{"x": 1}]), f"{RDI_URL}/push/people/", [{"x": 1}]),
            id="people",
        ),
        pytest.param(("complete_rdi", (RDI_ID,), f"{RDI_URL}/completed/", {}), id="complete"),
    ],
)
def test_post_methods(
    hope_api: HopeApi,
    hope_client: HopeClient,
    case: tuple[str, tuple[Any, ...], str, Any],
) -> None:
    method, args, url, payload = case
    hope_client.post.return_value = {"ok": True}

    result = getattr(hope_api, method)(*args)

    assert result == {"ok": True}
    hope_client.post.assert_called_once_with(url, payload)


def test_reset_rdi_accepted(hope_api: HopeApi, hope_client: HopeClient) -> None:
    result = hope_api.reset_rdi(RDI_ID, CALLBACK_URL)

    assert result is RdiResetResult.ACCEPTED
    hope_client.post.assert_called_once_with(f"{RDI_URL}/reset/", {"callback_url": CALLBACK_URL})


def test_reset_rdi_not_found(
    hope_api: HopeApi,
    hope_client: HopeClient,
    mocker: MockerFixture,
) -> None:
    response = mocker.Mock(status_code=HTTPStatus.NOT_FOUND)
    hope_client.post.side_effect = HopeResponseError("not found", response=response)

    result = hope_api.reset_rdi(RDI_ID, CALLBACK_URL)

    assert result is RdiResetResult.NOT_FOUND


@pytest.mark.parametrize(
    "status_code",
    [
        HTTPStatus.INTERNAL_SERVER_ERROR,
        HTTPStatus.BAD_GATEWAY,
        HTTPStatus.SERVICE_UNAVAILABLE,
        HTTPStatus.GATEWAY_TIMEOUT,
    ],
)
def test_reset_rdi_server_error_is_unconfirmed(
    hope_api: HopeApi,
    hope_client: HopeClient,
    mocker: MockerFixture,
    status_code: HTTPStatus,
) -> None:
    response = mocker.Mock(status_code=status_code)
    hope_client.post.side_effect = HopeResponseError("server error", response=response)

    with pytest.raises(HopeRdiResetUnconfirmedError):
        hope_api.reset_rdi(RDI_ID, CALLBACK_URL)


def test_reset_rdi_remote_error_is_unconfirmed(hope_api: HopeApi, hope_client: HopeClient) -> None:
    hope_client.post.side_effect = RemoteError("connection failed")

    with pytest.raises(HopeRdiResetUnconfirmedError):
        hope_api.reset_rdi(RDI_ID, CALLBACK_URL)


def test_reset_rdi_client_error_propagates(
    hope_api: HopeApi,
    hope_client: HopeClient,
    mocker: MockerFixture,
) -> None:
    response = mocker.Mock(status_code=HTTPStatus.CONFLICT)
    response.json.return_value = {"error": "unknown_conflict"}
    error = HopeResponseError("conflict", response=response)
    hope_client.post.side_effect = error

    with pytest.raises(HopeResponseError) as exc_info:
        hope_api.reset_rdi(RDI_ID, CALLBACK_URL)

    assert exc_info.value is error


@pytest.mark.parametrize(
    ("error_code", "expected"),
    [
        ("rdi_merge_in_progress", RdiResetResult.MERGE_IN_PROGRESS),
        ("rdi_already_merged", RdiResetResult.ALREADY_MERGED),
    ],
)
def test_reset_rdi_conflict(
    hope_api: HopeApi,
    hope_client: HopeClient,
    mocker: MockerFixture,
    error_code: str,
    expected: RdiResetResult,
) -> None:
    response = mocker.Mock(status_code=HTTPStatus.CONFLICT)
    response.json.return_value = {"error": error_code}
    hope_client.post.side_effect = HopeResponseError("conflict", response=response)

    assert hope_api.reset_rdi(RDI_ID, CALLBACK_URL) is expected
