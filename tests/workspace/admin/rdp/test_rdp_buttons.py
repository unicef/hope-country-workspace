import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp

pytestmark = pytest.mark.django_db


def _assert_job(create, *, description: str, action: str, owner, rdp: CountryRdp) -> None:
    create.assert_called_once_with(
        description=description,
        type=rdp_admin_mod.AsyncJob.JobType.TASK,
        owner=owner,
        action=action,
        program=rdp.program,
        rdp=rdp,
        config={"rdp_id": rdp.pk},
    )


@pytest.mark.parametrize("method", ["deduplicate", "cancel", "push"])
def test_buttons_redirect_when_rdp_not_found(admin_instance, mock_request, mocker: MockerFixture, method: str) -> None:
    admin_instance.get_object = mocker.Mock(return_value=None)
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk="999")

    error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert response == "response"


@pytest.mark.parametrize(
    ("method", "claim_name", "core", "description", "message"),
    [
        (
            "deduplicate",
            "claim_rdp_deduplication",
            rdp_admin_mod.dedup_existing_rdp_core,
            "Run Deduplication process on DedupEngine",
            "Dedup task scheduled",
        ),
        (
            "push",
            "claim_rdp_push",
            rdp_admin_mod.push_existing_rdp_core,
            "Push beneficiaries to HOPE",
            "Push to HOPE task scheduled",
        ),
    ],
    ids=["deduplicate", "push"],
)
def test_claim_buttons_schedule_jobs(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    method: str,
    claim_name: str,
    core,
    description: str,
    message: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    claim = mocker.patch.object(rdp_admin_mod, claim_name, return_value=(ActionCheck(True), rdp))
    on_commit = mocker.patch.object(rdp_admin_mod.transaction, "on_commit")
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    claim.assert_called_once_with(rdp_id=rdp.pk)
    _assert_job(create, description=description, action=rdp_admin_mod.fqn(core), owner=mock_request.user, rdp=rdp)
    on_commit.assert_called_once_with(job.queue)
    success.assert_called_once_with(mock_request, message)
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("method", "claim_name"),
    [("deduplicate", "claim_rdp_deduplication"), ("push", "claim_rdp_push")],
    ids=["deduplicate", "push"],
)
def test_claim_buttons_deny_when_claim_fails(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    method: str,
    claim_name: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    mocker.patch.object(rdp_admin_mod, claim_name, return_value=(ActionCheck(False, "blocked"), None))
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    error.assert_called_once_with(mock_request, "blocked")
    create.assert_not_called()
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("method", "claim_name", "exc", "captures"),
    [
        ("deduplicate", "claim_rdp_deduplication", RemoteUnavailableError("unavailable"), True),
        ("deduplicate", "claim_rdp_deduplication", RemoteError("remote"), False),
        ("push", "claim_rdp_push", RemoteUnavailableError("unavailable"), True),
        ("push", "claim_rdp_push", RemoteError("remote"), False),
    ],
    ids=["dedup_unavailable", "dedup_remote", "push_unavailable", "push_remote"],
)
def test_claim_buttons_handle_remote_errors(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    method: str,
    claim_name: str,
    exc: Exception,
    captures: bool,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    mocker.patch.object(rdp_admin_mod, claim_name, side_effect=exc)
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    error.assert_called_once_with(mock_request, str(exc))
    redirect.assert_called_once_with("/change")
    create.assert_not_called()
    assert capture.called is captures
    assert response == "response"


def test_cancel_schedules_job(admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, "cancel_check")
    _assert_job(
        create,
        description="Cancel RDP",
        action=rdp_admin_mod.fqn(rdp_admin_mod.cancel_existing_rdp_core),
        owner=mock_request.user,
        rdp=rdp,
    )
    job.queue.assert_called_once_with()
    success.assert_called_once_with(mock_request, "Cancel task scheduled")
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_cancel_returns_denial_response(admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value="denied")
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")

    assert admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk)) == "denied"

    create.assert_not_called()


def test_push_unlocks_rdp_on_unexpected_error(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.is_push_locked = True
    rdp.save(update_fields=["is_push_locked"])
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    mocker.patch.object(rdp_admin_mod, "claim_rdp_push", return_value=(ActionCheck(True), rdp))
    mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        admin_instance.push.func(admin_instance, mock_request, pk=str(rdp.pk))

    rdp.refresh_from_db()
    assert rdp.is_push_locked is False


@pytest.mark.parametrize(
    ("status", "master_detail", "expected_url"),
    [
        (CountryRdp.PushStatus.SUCCESS, True, None),
        (CountryRdp.PushStatus.PENDING, True, "workspace:workspaces_countryhousehold_changelist"),
        (CountryRdp.PushStatus.PENDING, False, "workspace:workspaces_countryindividual_changelist"),
    ],
    ids=["success_hidden", "households", "individuals"],
)
def test_records_button(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
    status: str,
    master_detail: bool,
    expected_url: str | None,
) -> None:
    rdp.status = status
    rdp.program.beneficiary_group.master_detail = master_detail
    reverse = mocker.patch.object(rdp_admin_mod, "reverse", return_value="/records")

    btn = admin_instance.records.get_button({"original": rdp})

    assert btn.visible is (expected_url is not None)
    if expected_url:
        assert btn.href == f"/records?rdp__exact={rdp.pk}"
        reverse.assert_called_once_with(expected_url)
    else:
        reverse.assert_not_called()
