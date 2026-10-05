import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def failed_rdp(rdp: CountryRdp) -> CountryRdp:
    rdp.status = CountryRdp.PushStatus.FAILURE
    rdp.save(update_fields=["status"])
    return rdp


@pytest.fixture
def review_rdp(rdp: CountryRdp) -> CountryRdp:
    rdp.status = CountryRdp.PushStatus.REVIEW_PENDING
    rdp.save(update_fields=["status"])
    return rdp


@pytest.fixture
def clean_rdp() -> CountryRdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(status=CountryRdp.PushStatus.CANCELLED)


@pytest.mark.parametrize(
    "method",
    ["cancel", "retry_failed_operations", "push_review", "retry_push", "create_clean_rdp"],
)
def test_button_redirects_when_rdp_not_found(
    admin_instance,
    mock_request,
    mocker: MockerFixture,
    method: str,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=None)
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk="999")

    assert "not found" in error.call_args.args[1].lower()
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert response == "response"


def test_cancel_denied(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=rdp)
    mocker.patch.object(admin_instance, "_deny_if_not_allowed", return_value="denied")
    cancel = mocker.patch.object(rdp_admin_mod, "cancel_rdp")

    assert admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk)) == "denied"

    cancel.assert_not_called()


def test_cancel(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.hope_rdi_id = None
    mocker.patch.object(admin_instance, "get_object", return_value=rdp)
    mocker.patch.object(admin_instance, "_deny_if_not_allowed", return_value=None)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    cancel = mocker.patch.object(rdp_admin_mod, "cancel_rdp", return_value=(ActionCheck(True), True))
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk))

    cancel.assert_called_once_with(rdp_id=rdp.pk, user_id=mock_request.user.pk)
    assert "cancelled" in success.call_args.args[1].lower()
    assert "scheduled" in success.call_args.args[1].lower()
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_cancel_requires_confirmation_for_existing_rdi(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.hope_rdi_id = "hope-rdi"
    mocker.patch.object(admin_instance, "get_object", return_value=rdp)
    mocker.patch.object(admin_instance, "_deny_if_not_allowed", return_value=None)
    confirm = mocker.patch.object(rdp_admin_mod, "confirm_action", return_value="response")
    cancel = mocker.patch.object(rdp_admin_mod, "cancel_rdp")

    response = admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk))

    assert rdp.hope_rdi_id in confirm.call_args.kwargs["message"]
    assert callable(confirm.call_args.args[2])
    cancel.assert_not_called()
    assert response == "response"


@pytest.mark.parametrize(
    ("count", "message_method"),
    [
        (2, "success"),
        (0, "warning"),
    ],
    ids=["scheduled", "nothing_to_retry"],
)
def test_retry_failed_operations(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    count: int,
    message_method: str,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=rdp)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    retry = mocker.patch.object(rdp_admin_mod, "retry_failed_rdp_operations", return_value=count)
    message = mocker.patch.object(rdp_admin_mod.messages, message_method)
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.retry_failed_operations.func(admin_instance, mock_request, pk=str(rdp.pk))

    retry.assert_called_once_with(rdp_id=rdp.pk, owner_id=mock_request.user.pk)
    message.assert_called_once()
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_push_review_denied(
    admin_instance,
    mock_request,
    review_rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=review_rdp)
    mocker.patch.object(admin_instance, "_deny_if_not_allowed", return_value="denied")
    claim = mocker.patch.object(rdp_admin_mod, "claim_review_rdp_push")

    assert admin_instance.push_review.func(admin_instance, mock_request, pk=str(review_rdp.pk)) == "denied"

    claim.assert_not_called()


def test_push_review(
    admin_instance,
    mock_request,
    review_rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=review_rdp)
    mocker.patch.object(admin_instance, "_deny_if_not_allowed", return_value=None)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    claim = mocker.patch.object(
        rdp_admin_mod,
        "claim_review_rdp_push",
        return_value=(ActionCheck(True), review_rdp),
    )
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    def confirm(_admin, request, callback, **_kwargs):
        return callback(request)

    mocker.patch.object(rdp_admin_mod, "confirm_action", side_effect=confirm)

    response = admin_instance.push_review.func(admin_instance, mock_request, pk=str(review_rdp.pk))

    claim.assert_called_once_with(rdp_id=review_rdp.pk, user_id=mock_request.user.pk)
    assert "scheduled" in success.call_args.args[1].lower()
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("check", "returned_rdp", "message_method"),
    [
        (ActionCheck(True), True, "success"),
        (ActionCheck(False, "blocked"), False, "error"),
    ],
    ids=["allowed", "denied"],
)
def test_retry_push(
    admin_instance,
    mock_request,
    failed_rdp: CountryRdp,
    mocker: MockerFixture,
    check: ActionCheck,
    returned_rdp: bool,
    message_method: str,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=failed_rdp)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    retry = mocker.patch.object(
        rdp_admin_mod,
        "retry_rdp_push",
        return_value=(check, failed_rdp if returned_rdp else None),
    )
    message = mocker.patch.object(rdp_admin_mod.messages, message_method)
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.retry_push.func(admin_instance, mock_request, pk=str(failed_rdp.pk))

    retry.assert_called_once_with(rdp_id=failed_rdp.pk, user_id=mock_request.user.pk)
    message.assert_called_once()
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_create_clean_rdp(
    admin_instance,
    mock_request,
    review_rdp: CountryRdp,
    clean_rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=review_rdp)
    change_url = mocker.patch.object(admin_instance, "_change_url", return_value="/clean")
    create = mocker.patch.object(
        rdp_admin_mod,
        "create_clean_rdp_workflow",
        return_value=(ActionCheck(True), clean_rdp),
    )
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    def confirm(_admin, request, callback, **_kwargs):
        return callback(request)

    mocker.patch.object(rdp_admin_mod, "confirm_action", side_effect=confirm)

    response = admin_instance.create_clean_rdp.func(admin_instance, mock_request, pk=str(review_rdp.pk))

    create.assert_called_once_with(rdp_id=review_rdp.pk, user_id=mock_request.user.pk)
    change_url.assert_called_once_with(clean_rdp)
    assert "clean rdp" in success.call_args.args[1].lower()
    redirect.assert_called_once_with("/clean")
    assert response == "response"


@pytest.mark.parametrize(
    "error",
    [
        RemoteError("remote"),
        RemoteUnavailableError("unavailable"),
        RdpWorkflowError({"errors": ["invalid selection"]}),
    ],
    ids=["remote", "unavailable", "workflow"],
)
def test_create_clean_rdp_handles_error(
    admin_instance,
    mock_request,
    review_rdp: CountryRdp,
    mocker: MockerFixture,
    error: Exception,
) -> None:
    mocker.patch.object(admin_instance, "get_object", return_value=review_rdp)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    mocker.patch.object(rdp_admin_mod, "create_clean_rdp_workflow", side_effect=error)
    message = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    def confirm(_admin, request, callback, **_kwargs):
        return callback(request)

    mocker.patch.object(rdp_admin_mod, "confirm_action", side_effect=confirm)

    response = admin_instance.create_clean_rdp.func(admin_instance, mock_request, pk=str(review_rdp.pk))

    message.assert_called_once()
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("master_detail", "url_name"),
    [
        (True, "workspace:workspaces_countryhousehold_changelist"),
        (False, "workspace:workspaces_countryindividual_changelist"),
    ],
    ids=["households", "individuals"],
)
def test_records_button(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
    master_detail: bool,
    url_name: str,
) -> None:
    rdp.program.beneficiary_group.master_detail = master_detail
    reverse = mocker.patch.object(rdp_admin_mod, "reverse", return_value="/records")

    button = admin_instance.records.get_button({"original": rdp})

    assert button.href == f"/records?rdp_id={rdp.pk}"
    reverse.assert_called_once_with(url_name)
