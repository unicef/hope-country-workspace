"""Tests for the dedup engine callback HTTP endpoint."""

import pytest
from django.core import signing
from django.test import RequestFactory

from country_workspace.contrib.hope.push.orchestration import (
    DEDUP_CALLBACK_MAX_AGE,
    DEDUP_CALLBACK_SALT,
)
from country_workspace.contrib.hope.views import DeduplicationCallbackView

VIEW_MOD = "country_workspace.contrib.hope.views"


def _signed_token(data: dict) -> str:
    return signing.dumps(data, salt=DEDUP_CALLBACK_SALT)


def _expired_token(data: dict) -> str:
    import time
    from unittest.mock import patch

    with patch("django.core.signing.time") as mock_time:
        mock_time.time.return_value = time.time() - DEDUP_CALLBACK_MAX_AGE - 10
        return signing.dumps(data, salt=DEDUP_CALLBACK_SALT)


@pytest.fixture
def rf() -> RequestFactory:
    return RequestFactory()


def test_callback_view_valid_token_calls_handle_and_returns_200(rf, mocker) -> None:
    token = _signed_token({"rdp_id": 7, "job_id": 42})
    handle = mocker.patch(f"{VIEW_MOD}.dedup_callback_handle")

    request = rf.get(f"/hope/dedup/callback/{token}/")
    response = DeduplicationCallbackView.as_view()(request, signed_token=token)

    assert response.status_code == 200
    handle.assert_called_once_with(rdp_id=7, job_id=42)


def test_callback_view_invalid_token_returns_403(rf, mocker) -> None:
    mocker.patch(f"{VIEW_MOD}.dedup_callback_handle")

    request = rf.get("/hope/dedup/callback/bad-token/")
    response = DeduplicationCallbackView.as_view()(request, signed_token="bad-token")

    assert response.status_code == 403


def test_callback_view_expired_token_returns_403(rf, mocker) -> None:
    token = _expired_token({"rdp_id": 7, "job_id": 42})
    handle = mocker.patch(f"{VIEW_MOD}.dedup_callback_handle")

    request = rf.get(f"/hope/dedup/callback/{token}/")
    response = DeduplicationCallbackView.as_view()(request, signed_token=token)

    assert response.status_code == 403
    handle.assert_not_called()


def test_callback_view_missing_rdp_id_returns_403(rf, mocker) -> None:
    token = _signed_token({"job_id": 42})  # no rdp_id
    mocker.patch(f"{VIEW_MOD}.dedup_callback_handle")

    request = rf.get(f"/hope/dedup/callback/{token}/")
    response = DeduplicationCallbackView.as_view()(request, signed_token=token)

    assert response.status_code == 403


def test_callback_view_missing_job_id_returns_403(rf, mocker) -> None:
    token = _signed_token({"rdp_id": 7})  # no job_id
    mocker.patch(f"{VIEW_MOD}.dedup_callback_handle")

    request = rf.get(f"/hope/dedup/callback/{token}/")
    response = DeduplicationCallbackView.as_view()(request, signed_token=token)

    assert response.status_code == 403


def test_callback_view_handle_exception_still_returns_200(rf, mocker) -> None:
    """Even if dedup_callback_handle raises, the view must return 200 (idempotent contract)."""
    token = _signed_token({"rdp_id": 7, "job_id": 42})
    mocker.patch(f"{VIEW_MOD}.dedup_callback_handle", side_effect=RuntimeError("boom"))

    request = rf.get(f"/hope/dedup/callback/{token}/")
    response = DeduplicationCallbackView.as_view()(request, signed_token=token)

    assert response.status_code == 200
