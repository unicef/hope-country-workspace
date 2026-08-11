from uuid import UUID, uuid4

import pytest
from django.core import signing
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture
from rest_framework import status

from country_workspace.api.callbacks.hope import views
from country_workspace.rdp import PUSH_READY_CALLBACK_SALT


VIEW_NAME = "api:callbacks:hope-rdp-push-ready"


@pytest.fixture
def callback_url() -> tuple[str, UUID]:
    push_attempt_id = uuid4()
    token = signing.dumps(
        {"rdp_id": 1, "push_attempt_id": str(push_attempt_id)},
        salt=PUSH_READY_CALLBACK_SALT,
    )
    return reverse(VIEW_NAME, kwargs={"signed_token": token}), push_attempt_id


@pytest.mark.parametrize("queued", [True, False])
def test_push_ready_callback(
    client: Client,
    mocker: MockerFixture,
    callback_url: tuple[str, UUID],
    queued: bool,
) -> None:
    url, push_attempt_id = callback_url
    handler = mocker.patch.object(views, "handle_push_ready_callback", return_value=queued)

    response = client.post(url)

    assert response.status_code == (status.HTTP_202_ACCEPTED if queued else status.HTTP_200_OK)
    assert response.json()["code"] == ("queued" if queued else "ignored")
    assert response.json()["rdp_id"] == 1
    assert response.json()["push_attempt_id"] == str(push_attempt_id)
    assert "no-store" in response["Cache-Control"]
    handler.assert_called_once_with(rdp_id=1, push_attempt_id=push_attempt_id)


def test_push_ready_callback_rejects_invalid_signature(client: Client, mocker: MockerFixture) -> None:
    handler = mocker.patch.object(views, "handle_push_ready_callback")

    response = client.post(reverse(VIEW_NAME, kwargs={"signed_token": "invalid"}))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid" in response.json()["detail"].lower()
    handler.assert_not_called()


def test_push_ready_callback_rejects_invalid_payload(client: Client, mocker: MockerFixture) -> None:
    token = signing.dumps(
        {"rdp_id": 0, "push_attempt_id": "invalid"},
        salt=PUSH_READY_CALLBACK_SALT,
    )
    handler = mocker.patch.object(views, "handle_push_ready_callback")

    response = client.post(reverse(VIEW_NAME, kwargs={"signed_token": token}))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    handler.assert_not_called()


def test_push_ready_callback_returns_server_error(
    client: Client,
    mocker: MockerFixture,
    callback_url: tuple[str, UUID],
) -> None:
    url, _ = callback_url
    mocker.patch.object(views, "handle_push_ready_callback", side_effect=RuntimeError("boom"))
    client.raise_request_exception = False

    response = client.post(url)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_push_ready_callback_rejects_get(client: Client, callback_url: tuple[str, UUID]) -> None:
    url, _ = callback_url

    response = client.get(url)

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
