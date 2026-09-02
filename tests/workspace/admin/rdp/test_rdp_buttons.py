from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.rdp.policy import ActionCheck
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("method", ["deduplicate", "cancel", "push"])
def test_buttons_redirect_when_rdp_not_found(
    admin_instance,
    mock_request,
    mocker: MockerFixture,
    method: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=None)
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk="999")

    error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert response == "response"


def test_deduplicate_schedules_job(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    claim = mocker.patch.object(
        rdp_admin_mod,
        "claim_rdp_deduplication",
        return_value=(ActionCheck(True), rdp),
    )
    on_commit = mocker.patch.object(rdp_admin_mod.transaction, "on_commit")
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.deduplicate.func(admin_instance, mock_request, pk=str(rdp.pk))

    claim.assert_called_once_with(rdp_id=rdp.pk)
    create.assert_called_once_with(
        description="Run Deduplication process on DedupEngine",
        type=rdp_admin_mod.AsyncJob.JobType.TASK,
        owner=mock_request.user,
        action=rdp_admin_mod.fqn(rdp_admin_mod.dedup_existing_rdp_core),
        program=rdp.program,
        rdp=rdp,
        config={"rdp_id": rdp.pk},
    )
    on_commit.assert_called_once_with(job.queue)
    success.assert_called_once_with(mock_request, "Dedup task scheduled")
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_push_schedules_preparation_job(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    push_attempt_id = uuid4()
    rdp.status = CountryRdp.PushStatus.PUSH_PENDING
    rdp.push_attempt_id = push_attempt_id

    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    claim = mocker.patch.object(rdp_admin_mod, "claim_rdp_push", return_value=(ActionCheck(True), rdp))
    on_commit = mocker.patch.object(rdp_admin_mod.transaction, "on_commit")
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.push.func(admin_instance, mock_request, pk=str(rdp.pk))

    claim.assert_called_once_with(rdp_id=rdp.pk)
    create.assert_called_once_with(
        description="Prepare RDP for HOPE push",
        type=rdp_admin_mod.AsyncJob.JobType.TASK,
        owner=mock_request.user,
        action=rdp_admin_mod.fqn(rdp_admin_mod.push_existing_rdp_core),
        program=rdp.program,
        rdp=rdp,
        config={
            "rdp_id": rdp.pk,
            "push_attempt_id": str(push_attempt_id),
            "rdi_id_to_reset": rdp.hope_rdi_id,
        },
    )
    on_commit.assert_called_once_with(job.queue)
    success.assert_called_once_with(mock_request, "Push to HOPE task scheduled")
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(("deduplicate", "claim_rdp_deduplication"), id="deduplicate"),
        pytest.param(("push", "claim_rdp_push"), id="push"),
    ],
)
def test_claim_buttons_deny_when_claim_fails(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    case: tuple[str, str],
) -> None:
    method, claim_name = case
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
    "case",
    [
        pytest.param(
            ("deduplicate", "claim_rdp_deduplication", RemoteUnavailableError("unavailable"), True),
            id="dedup_unavailable",
        ),
        pytest.param(
            ("deduplicate", "claim_rdp_deduplication", RemoteError("remote"), False),
            id="dedup_remote",
        ),
        pytest.param(
            ("push", "claim_rdp_push", RemoteUnavailableError("unavailable"), True),
            id="push_unavailable",
        ),
        pytest.param(
            ("push", "claim_rdp_push", RemoteError("remote"), False),
            id="push_remote",
        ),
    ],
)
def test_claim_buttons_handle_remote_errors(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    case: tuple[str, str, Exception, bool],
) -> None:
    method, claim_name, exc, captures = case
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


@pytest.mark.parametrize(
    "case",
    [
        (None, False),
        ("N/A", False),
        ("hope-rdi-1", True),
    ],
    ids=["no_rdi", "not_applicable", "existing_rdi"],
)
def test_cancel(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    case,
) -> None:
    hope_rdi_id, requires_confirmation = case
    rdp.hope_rdi_id = hope_rdi_id

    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    confirm = mocker.patch.object(rdp_admin_mod, "confirm_action", return_value="response")
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, "cancel_check")

    if requires_confirmation:
        confirm.assert_called_once()
        assert confirm.call_args.args[:2] == (admin_instance, mock_request)
        assert callable(confirm.call_args.args[2])
        assert hope_rdi_id in confirm.call_args.kwargs["message"]
        create.assert_not_called()
        success.assert_not_called()
        redirect.assert_not_called()
    else:
        confirm.assert_not_called()
        create.assert_called_once_with(
            description="Cancel RDP",
            type=rdp_admin_mod.AsyncJob.JobType.TASK,
            owner=mock_request.user,
            action=rdp_admin_mod.fqn(rdp_admin_mod.cancel_existing_rdp_core),
            program=rdp.program,
            rdp=rdp,
            config={"rdp_id": rdp.pk},
        )
        job.queue.assert_called_once_with()
        success.assert_called_once_with(mock_request, "Cancel task scheduled")
        redirect.assert_called_once_with("/change")

    assert response == "response"


def test_cancel_returns_denial_response(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value="denied")
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")

    assert admin_instance.cancel.func(admin_instance, mock_request, pk=str(rdp.pk)) == "denied"

    create.assert_not_called()


def test_push_rolls_back_claim_when_job_creation_fails(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    push_attempt_id = uuid4()

    def claim_rdp_push(*, rdp_id: int) -> tuple[ActionCheck, CountryRdp]:
        assert rdp_id == rdp.pk
        rdp.status = CountryRdp.PushStatus.PUSH_PENDING
        rdp.push_attempt_id = push_attempt_id
        rdp.save(update_fields=["status", "push_attempt_id"])
        return ActionCheck(True), rdp

    admin_instance.get_object = mocker.Mock(return_value=rdp)
    mocker.patch.object(rdp_admin_mod, "claim_rdp_push", side_effect=claim_rdp_push)
    mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        admin_instance.push.func(admin_instance, mock_request, pk=str(rdp.pk))

    rdp.refresh_from_db()

    assert rdp.status == CountryRdp.PushStatus.PENDING
    assert rdp.push_attempt_id is None


def test_push_fails_when_attempt_is_not_initialized(
    admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture
) -> None:
    rdp.push_attempt_id = None
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    mocker.patch.object(rdp_admin_mod, "claim_rdp_push", return_value=(ActionCheck(True), rdp))
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")

    with pytest.raises(RuntimeError, match="push attempt was not initialized"):
        admin_instance.push.func(admin_instance, mock_request, pk=str(rdp.pk))

    create.assert_not_called()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param((CountryRdp.PushStatus.SUCCESS, True, None), id="success_hidden"),
        pytest.param(
            (
                CountryRdp.PushStatus.PENDING,
                True,
                "workspace:workspaces_countryhousehold_changelist",
            ),
            id="households",
        ),
        pytest.param(
            (
                CountryRdp.PushStatus.PENDING,
                False,
                "workspace:workspaces_countryindividual_changelist",
            ),
            id="individuals",
        ),
    ],
)
def test_records_button(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
    case: tuple[str, bool, str | None],
) -> None:
    status, master_detail, expected_url = case
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
