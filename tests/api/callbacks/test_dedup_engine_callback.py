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
def callback_url() -> str:
    token = signing.dumps({"rdp_id": 1, "job_id": 2}, salt=DEDUP_CALLBACK_SALT)
    return reverse(VIEW_NAME, kwargs={"signed_token": token})


def test_deduplication_callback(client: Client, mocker: MockerFixture, callback_url: str) -> None:
    handler = mocker.patch.object(views, "dedup_callback_handle")

    response = client.get(callback_url)

    assert response.status_code == status.HTTP_200_OK
    assert "no-store" in response["Cache-Control"]
    handler.assert_called_once_with(rdp_id=1, job_id=2)


def test_deduplication_callback_rejects_invalid_signature(client: Client, mocker: MockerFixture) -> None:
    handler = mocker.patch.object(views, "dedup_callback_handle")

    response = client.get(reverse(VIEW_NAME, kwargs={"signed_token": "invalid"}))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "invalid" in response.json()["detail"].lower()
    handler.assert_not_called()


def test_deduplication_callback_rejects_invalid_payload(client: Client, mocker: MockerFixture) -> None:
    token = signing.dumps({"rdp_id": 0, "job_id": 0}, salt=DEDUP_CALLBACK_SALT)
    handler = mocker.patch.object(views, "dedup_callback_handle")

    response = client.get(reverse(VIEW_NAME, kwargs={"signed_token": token}))

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    handler.assert_not_called()


def test_deduplication_callback_acknowledges_handler_error(
    client: Client,
    mocker: MockerFixture,
    callback_url: str,
) -> None:
    handler = mocker.patch.object(views, "dedup_callback_handle", side_effect=RuntimeError("boom"))

    response = client.get(callback_url)

    assert response.status_code == status.HTTP_200_OK
    handler.assert_called_once_with(rdp_id=1, job_id=2)


def test_deduplication_callback_rejects_post(client: Client, callback_url: str) -> None:
    response = client.post(callback_url)

    assert response.status_code == status.HTTP_405_METHOD_NOT_ALLOWED
