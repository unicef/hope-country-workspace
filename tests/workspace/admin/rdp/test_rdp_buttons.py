import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.workspaces.admin import rdp as rdp_admin_mod


pytestmark = pytest.mark.django_db


def _assert_job(
    create,
    job,
    *,
    description: str,
    action: str,
    owner,
    rdp,
) -> None:
    create.assert_called_once_with(
        description=description,
        type=rdp_admin_mod.AsyncJob.JobType.TASK,
        owner=owner,
        action=action,
        program=rdp.program,
        rdp=rdp,
        config={"rdp_id": rdp.pk},
    )
    job.queue.assert_called_once_with()


@pytest.mark.parametrize(
    "method",
    ["deduplicate", "reject_ds", "push", "clone_rdp"],
    ids=["deduplicate", "reject_ds", "push", "clone_rdp"],
)
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
    rdp,
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
    job.queue.assert_not_called()
    success.assert_called_once_with(mock_request, "Dedup task scheduled")
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_deduplicate_denies_when_claim_fails(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")

    mocker.patch.object(
        rdp_admin_mod,
        "claim_rdp_deduplication",
        return_value=(ActionCheck(False, "blocked"), None),
    )
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    on_commit = mocker.patch.object(rdp_admin_mod.transaction, "on_commit")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.deduplicate.func(admin_instance, mock_request, pk=str(rdp.pk))

    error.assert_called_once_with(mock_request, "blocked")
    create.assert_not_called()
    on_commit.assert_not_called()
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("exc", "captures"),
    [
        (RemoteUnavailableError("unavailable"), True),
        (RemoteError("remote"), False),
    ],
    ids=["remote_unavailable", "remote_error"],
)
def test_deduplicate_handles_remote_errors(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
    exc: Exception,
    captures: bool,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")

    mocker.patch.object(rdp_admin_mod, "claim_rdp_deduplication", side_effect=exc)
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    response = admin_instance.deduplicate.func(admin_instance, mock_request, pk=str(rdp.pk))

    error.assert_called_once_with(mock_request, str(exc))
    redirect.assert_called_once_with("/change")
    create.assert_not_called()
    assert capture.called is captures
    assert response == "response"


@pytest.mark.parametrize(
    ("method", "check_action", "description", "action", "success_message"),
    [
        (
            "reject_ds",
            "reject_ds_check",
            "Reject RDP by rejecting its active DE deduplication set",
            rdp_admin_mod.fqn(rdp_admin_mod.reject_deduplication_set_existing_rdp_core),
            "Reject task scheduled",
        ),
        (
            "push",
            "push_check",
            "Push beneficiaries to HOPE",
            rdp_admin_mod.fqn(rdp_admin_mod.push_existing_rdp_core),
            "Push to HOPE task scheduled",
        ),
    ],
    ids=["reject_ds", "push"],
)
def test_workflow_buttons_schedule_jobs(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
    method: str,
    check_action: str,
    description: str,
    action: str,
    success_message: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)

    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, check_action)
    _assert_job(
        create,
        job,
        description=description,
        action=action,
        owner=mock_request.user,
        rdp=rdp,
    )
    success.assert_called_once_with(mock_request, success_message)
    redirect.assert_called_once_with("/change")
    assert response == "response"


@pytest.mark.parametrize(
    ("method", "check_action"),
    [
        ("reject_ds", "reject_ds_check"),
        ("push", "push_check"),
        ("clone_rdp", "clone_check"),
    ],
    ids=["reject_ds", "push", "clone_rdp"],
)
def test_buttons_return_denial_response(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
    method: str,
    check_action: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value="denied")

    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    render = mocker.patch.object(rdp_admin_mod, "render")
    clone = mocker.patch.object(rdp_admin_mod, "clone_rdp_core")

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, check_action)
    assert response == "denied"
    create.assert_not_called()
    render.assert_not_called()
    clone.assert_not_called()


def test_clone_rdp_get_renders_form(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    admin_instance.get_common_context = mocker.Mock(return_value={"ctx": True})

    form = mocker.MagicMock()
    form_cls = mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/list")
    render = mocker.patch.object(rdp_admin_mod, "render", return_value="response")

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, "clone_check")
    form_cls.assert_called_once_with(
        initial={
            "action": "clone_rdp",
            "select_across": False,
            "_selected_action": [str(rdp.pk)],
        }
    )
    admin_instance.get_common_context.assert_called_once_with(
        mock_request,
        title="Clone RDP",
        form=form,
        original=rdp,
        changelist_url="/list",
        original_change_url="/change",
        intro_text="A new RDP will be created using the parent RDP beneficiary selection.",
        submit_label="Clone RDP",
        submit_name="_clone",
    )
    render.assert_called_once_with(mock_request, "workspace/actions/create_rdp.html", {"ctx": True})
    assert response == "response"


def test_clone_rdp_post_success(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
) -> None:
    mock_request.method = "POST"
    mock_request.POST = {"_clone": "1"}

    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)
    admin_instance._change_url = mocker.Mock(return_value="/cloned")

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {"batch_name": ""}
    form_cls = mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    mocker.patch.object(rdp_admin_mod, "rdi_name_default", return_value="AUTO")

    cloned = mocker.MagicMock()
    clone = mocker.patch.object(rdp_admin_mod, "clone_rdp_core", return_value=cloned)
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

    form_cls.assert_called_once_with(mock_request.POST)
    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, "clone_check")
    clone.assert_called_once_with(
        source=rdp,
        batch_name="AUTO",
        pushed_by_id=mock_request.user.id,
    )
    success.assert_called_once_with(mock_request, "RDP cloned")
    redirect.assert_called_once_with("/cloned")
    admin_instance._change_url.assert_called_once_with(cloned)
    assert response == "response"


def test_clone_rdp_post_error_renders_form(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
) -> None:
    mock_request.method = "POST"
    mock_request.POST = {"_clone": "1"}

    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._deny_if_not_allowed = mocker.Mock(return_value=None)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    admin_instance.get_common_context = mocker.Mock(return_value={"ctx": True})

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {"batch_name": "Batch"}
    form_cls = mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    mocker.patch.object(rdp_admin_mod, "clone_rdp_core", side_effect=HopePushError({"errors": ["boom"]}))
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/list")

    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    render = mocker.patch.object(rdp_admin_mod, "render", return_value="response")

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

    admin_instance._deny_if_not_allowed.assert_called_once_with(mock_request, rdp, "clone_check")
    form_cls.assert_called_once_with(mock_request.POST)
    error.assert_called_once()
    assert "boom" in error.call_args.args[1]
    render.assert_called_once_with(mock_request, "workspace/actions/create_rdp.html", {"ctx": True})
    assert response == "response"
