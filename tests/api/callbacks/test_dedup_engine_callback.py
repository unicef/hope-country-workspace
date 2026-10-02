from uuid import UUID, uuid4

import pytest
from django.core import signing
from django.test import Client
from django.urls import reverse
from pytest_mock import MockerFixture
from rest_framework import status

from country_workspace.api.callbacks.dedup_engine import views
from country_workspace.rdp import DEDUP_CALLBACK_SALT


VIEW_NAME = "api:callbacks:dedup-engine-rdp-state-changed"


@pytest.fixture
def callback_url() -> tuple[str, UUID]:
    operation_id = uuid4()
    token = signing.dumps({"operation_id": str(operation_id)}, salt=DEDUP_CALLBACK_SALT)
    return reverse(VIEW_NAME, kwargs={"signed_token": token}), operation_id


@pytest.mark.parametrize(
    ("synchronized", "code"),
    [
        (True, "updated"),
        (False, "unchanged"),
    ],
)
def test_dedup_callback(
    client: Client,
    mocker: MockerFixture,
    callback_url: tuple[str, UUID],
    synchronized: bool,
    code: str,
) -> None:
    url, operation_id = callback_url
    sync = mocker.patch.object(
        views,
        "sync_biometric_deduplication_result",
        return_value=synchronized,
    )

    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["code"] == code
    assert "no-store" in response["Cache-Control"]
    sync.assert_called_once_with(operation_id=operation_id)


def test_dedup_callback_rejects_invalid_signature(client: Client, mocker: MockerFixture) -> None:
    sync = mocker.patch.object(views, "sync_biometric_deduplication_result")
    url = reverse(VIEW_NAME, kwargs={"signed_token": "invalid"})

    response = client.get(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid" in response.json()["detail"].lower()
    assert "no-store" in response["Cache-Control"]
    sync.assert_not_called()


def test_dedup_callback_rejects_invalid_payload(client: Client, mocker: MockerFixture) -> None:
    token = signing.dumps({"operation_id": "invalid"}, salt=DEDUP_CALLBACK_SALT)
    url = reverse(VIEW_NAME, kwargs={"signed_token": token})
    sync = mocker.patch.object(views, "sync_biometric_deduplication_result")

    response = client.get(url)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid" in response.json()["detail"].lower()
    assert "no-store" in response["Cache-Control"]
    sync.assert_not_called()


def test_dedup_callback_returns_server_error(
    client: Client,
    mocker: MockerFixture,
    callback_url: tuple[str, UUID],
) -> None:
    url, _ = callback_url
    mocker.patch.object(
        views,
        "sync_biometric_deduplication_result",
        side_effect=RuntimeError("boom"),
    )
    client.raise_request_exception = False

    response = client.get(url)

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR


def test_dedup_callback_rejects_post(client: Client, callback_url: tuple[str, UUID]) -> None:
    url, _ = callback_url

    response = client.post(url)

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
