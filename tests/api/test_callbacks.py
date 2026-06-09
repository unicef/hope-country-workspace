import pytest
from django.urls import resolve
from pytest_mock import MockerFixture
from rest_framework import status
from rest_framework.exceptions import ValidationError

from country_workspace.api.grants import APIGrant
from country_workspace.api.serializers import HopeRdiCallbackSerializer
from country_workspace.api.views import HopeRdiCallbackView, _callback_payload
from country_workspace.contrib.hope.exceptions import (
    HopeRdiCallbackConflictError,
    HopeRdiCallbackError,
    HopeRdiCallbackNotFoundError,
)
from country_workspace.contrib.hope.push import HopeRdiCallbackCode, HopeRdiCallbackPayload
from country_workspace.models import Rdp

MOD = "country_workspace.api.views"


def test_api_grant_values() -> None:
    assert APIGrant.HOPE_RDI_CALLBACK == "HOPE_RDI_CALLBACK"


@pytest.mark.parametrize(
    ("raw_status", "expected_status"),
    [
        ("MERGED", Rdp.PushStatus.MERGED),
        ("REJECTED", Rdp.PushStatus.REJECTED),
    ],
    ids=["merged", "rejected"],
)
def test_hope_rdi_callback_serializer_accepts_final_statuses(
    raw_status: str,
    expected_status: Rdp.PushStatus,
) -> None:
    serializer = HopeRdiCallbackSerializer(data={"status": raw_status})

    assert serializer.is_valid(), serializer.errors
    assert serializer.validated_data["status"] == expected_status


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"status": "PUSHED"},
        {"status": "FOO"},
    ],
    ids=["missing", "non_final", "unknown"],
)
def test_hope_rdi_callback_serializer_rejects_invalid_status(payload: dict[str, str]) -> None:
    serializer = HopeRdiCallbackSerializer(data=payload)

    assert not serializer.is_valid()
    assert "status" in serializer.errors


def test_hope_rdi_callback_url_resolves() -> None:
    match = resolve(
        "/callbacks/hope/rdis/RDI-1/",
        urlconf="country_workspace.api.urls",
    )

    assert match.url_name == "hope-rdi-callback"
    assert match.kwargs == {"hope_rdi_id": "RDI-1"}
    assert match.func.view_class is HopeRdiCallbackView


@pytest.mark.parametrize(
    "exc",
    [
        HopeRdiCallbackError(
            HopeRdiCallbackPayload.error(
                code=HopeRdiCallbackCode.CALLBACK_ERROR,
                detail="boom",
                rdi_id="RDI-1",
            )
        ),
        HopeRdiCallbackError({"detail": "boom"}),
    ],
    ids=["payload", "dict"],
)
def test_callback_payload_returns_stable_payload(exc: HopeRdiCallbackError) -> None:
    payload = _callback_payload(exc)

    assert isinstance(payload, dict)
    assert payload


def test_callback_payload_wraps_unknown_error() -> None:
    payload = _callback_payload(HopeRdiCallbackError("boom"))

    assert payload["changed"] is False
    assert payload["code"] == HopeRdiCallbackCode.CALLBACK_ERROR
    assert payload["detail"] == "boom"


def test_hope_rdi_callback_view_success(mocker: MockerFixture) -> None:
    token = mocker.MagicMock()
    request = mocker.MagicMock(data={"status": Rdp.PushStatus.MERGED}, auth=token)
    payload = HopeRdiCallbackPayload(
        rdp_id=1,
        rdi_id="RDI-1",
        status=Rdp.PushStatus.MERGED,
        changed=True,
        code=HopeRdiCallbackCode.FINALIZED,
        detail="RDP status updated to MERGED.",
    )
    apply_status = mocker.patch(f"{MOD}.apply_hope_rdi_final_status", return_value=payload)

    response = HopeRdiCallbackView().post(request, hope_rdi_id="RDI-1")

    assert response.status_code == status.HTTP_200_OK
    assert response.data == payload.as_dict()
    apply_status.assert_called_once_with(
        hope_rdi_id="RDI-1",
        status=Rdp.PushStatus.MERGED,
        token=token,
    )


@pytest.mark.parametrize(
    ("exc_cls", "http_status"),
    [
        (HopeRdiCallbackNotFoundError, status.HTTP_404_NOT_FOUND),
        (HopeRdiCallbackConflictError, status.HTTP_409_CONFLICT),
        (HopeRdiCallbackError, status.HTTP_400_BAD_REQUEST),
    ],
    ids=["not_found", "conflict", "callback_error"],
)
def test_hope_rdi_callback_view_maps_domain_errors(
    mocker: MockerFixture,
    exc_cls: type[HopeRdiCallbackError],
    http_status: int,
) -> None:
    request = mocker.MagicMock(data={"status": Rdp.PushStatus.REJECTED}, auth=mocker.MagicMock())
    payload = HopeRdiCallbackPayload.error(
        code=HopeRdiCallbackCode.CALLBACK_ERROR,
        detail="boom",
        rdi_id="RDI-1",
    )
    mocker.patch(f"{MOD}.apply_hope_rdi_final_status", side_effect=exc_cls(payload))

    response = HopeRdiCallbackView().post(request, hope_rdi_id="RDI-1")

    assert response.status_code == http_status
    assert response.data == payload.as_dict()


def test_hope_rdi_callback_view_raises_validation_error(mocker: MockerFixture) -> None:
    request = mocker.MagicMock(data={"status": "FOO"}, auth=mocker.MagicMock())
    apply_status = mocker.patch(f"{MOD}.apply_hope_rdi_final_status")

    with pytest.raises(ValidationError):
        HopeRdiCallbackView().post(request, hope_rdi_id="RDI-1")

    apply_status.assert_not_called()
