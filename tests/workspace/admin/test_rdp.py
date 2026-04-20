import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.urls import NoReverseMatch
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.exceptions import HopePushError
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.state import state
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.admin.rdp import CountryRdpAdmin
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def program(office, master_detail):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(
        country_office=office,
        beneficiary_group__master_detail=master_detail,
    )
    state.program = program
    return program


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def admin_instance(mocker: MockerFixture):
    return CountryRdpAdmin(model=CountryRdp, admin_site=mocker.MagicMock())


@pytest.fixture
def mock_request(mocker: MockerFixture):
    request = mocker.MagicMock(spec=HttpRequest)
    request.user = mocker.MagicMock(spec=User)
    request.method = "GET"
    request.POST = {}
    return request


def _assert_job(create, job, *, description, action, owner, rdp):
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["description"] == description
    assert kwargs["type"] == rdp_admin_mod.AsyncJob.JobType.TASK
    assert kwargs["action"] == action
    assert kwargs["owner"] == owner
    assert kwargs["program"] == rdp.program
    assert kwargs["rdp"] == rdp
    assert kwargs["config"] == {"rdp_id": rdp.pk}
    job.queue.assert_called_once_with()


@pytest.mark.parametrize(
    ("has_obj", "dedup_enabled", "expected"),
    [
        (
            False,
            False,
            ["name", "parent", "push_date", "status", "biometric_deduplication_enabled", "related_jobs"],
        ),
        (
            True,
            False,
            ["name", "parent", "push_date", "status", "biometric_deduplication_enabled", "related_jobs"],
        ),
        (
            True,
            True,
            [
                "name",
                "parent",
                "push_date",
                "status",
                "biometric_deduplication_enabled",
                "dedup_engine_state",
                "deduplication_set_id",
                "related_jobs",
            ],
        ),
    ],
    ids=["no_obj", "dedup_off", "dedup_on"],
)
def test_country_rdp_admin_fields_and_readonly_fields(
    admin_instance,
    mock_request,
    rdp,
    has_obj: bool,
    dedup_enabled: bool,
    expected: list[str],
) -> None:
    obj = rdp if has_obj else None
    if obj is not None:
        obj.program.biometric_deduplication_enabled = dedup_enabled

    assert admin_instance.get_fields(mock_request, obj) == expected
    assert admin_instance.get_readonly_fields(mock_request, obj) == expected


def test_country_rdp_admin_permissions(admin_instance, mock_request, rdp) -> None:
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request, rdp) is False
    assert admin_instance.has_delete_permission(mock_request, rdp) is False


def test_country_rdp_admin_get_common_context(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
) -> None:
    spy = mocker.patch.object(
        rdp_admin_mod.WorkspaceModelAdmin,
        "get_common_context",
        return_value={"ok": True},
    )

    assert admin_instance.get_common_context(mock_request, pk="1", title="T") == {"ok": True}

    spy.assert_called_once_with(
        mock_request,
        "1",
        title="T",
        modeladmin=admin_instance,
        modeladmin_name="CountryRdpAdmin",
    )


def test_country_rdp_admin_get_queryset(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    program,
) -> None:
    base_qs = mocker.MagicMock()
    selected_qs = mocker.MagicMock()
    filtered_qs = mocker.MagicMock()
    spy = mocker.patch.object(rdp_admin_mod.WorkspaceModelAdmin, "get_queryset", return_value=base_qs)
    base_qs.select_related.return_value = selected_qs
    selected_qs.filter.return_value = filtered_qs

    assert admin_instance.get_queryset(mock_request) is filtered_qs

    spy.assert_called_once_with(mock_request)
    base_qs.select_related.assert_called_once_with("program__beneficiary_group")
    selected_qs.filter.assert_called_once_with(program=state.program)


def test_country_rdp_admin_related_jobs_empty(admin_instance, rdp) -> None:
    assert admin_instance.related_jobs(rdp) == "-"


def test_country_rdp_admin_related_jobs_renders_links(
    mocker: MockerFixture,
    admin_instance,
    rdp,
) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(rdp=rdp, program=rdp.program)
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/job-url")

    result = admin_instance.related_jobs(rdp)

    assert "/job-url" in result
    assert str(job) in result


@pytest.mark.parametrize("flag", [True, False], ids=["enabled", "disabled"])
def test_country_rdp_admin_biometric_deduplication_enabled(admin_instance, rdp, flag: bool) -> None:
    rdp.program.biometric_deduplication_enabled = flag

    assert admin_instance.biometric_deduplication_enabled(rdp) is flag


def test_is_visible(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.is_push_visible.return_value = True
    obj = mocker.MagicMock()
    btn = mocker.MagicMock(original=obj)
    spy = mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert rdp_admin_mod._is_visible(btn, "is_push_visible") is True
    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=None), "is_push_visible") is False

    spy.assert_called_once_with(obj)
    policy.is_push_visible.assert_called_once_with()


def test_is_allowed_returns_action_allowed(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.push_check.return_value = mocker.MagicMock(allowed=True)
    obj = mocker.MagicMock()
    btn = mocker.MagicMock(original=obj)
    spy = mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert rdp_admin_mod._is_allowed(btn, "push_check") is True
    assert rdp_admin_mod._is_allowed(mocker.MagicMock(original=None), "push_check") is False

    spy.assert_called_once_with(obj)
    policy.push_check.assert_called_once_with()


def test_is_allowed_returns_false_on_remote_unavailable(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.push_check.side_effect = RemoteUnavailableError("boom")
    btn = mocker.MagicMock(original=mocker.MagicMock())
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    assert rdp_admin_mod._is_allowed(btn, "push_check") is False

    cap.assert_called_once()


def test_is_allowed_returns_false_on_remote_error(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.push_check.side_effect = RemoteError("boom")
    btn = mocker.MagicMock(original=mocker.MagicMock())
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    assert rdp_admin_mod._is_allowed(btn, "push_check") is False

    cap.assert_not_called()


def test_country_rdp_admin_dedup_engine_state_returns_policy_value(
    mocker: MockerFixture,
    admin_instance,
    rdp,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.return_value = "Ready to start"
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == "Ready to start"


def test_country_rdp_admin_dedup_engine_state_handles_remote_unavailable(
    mocker: MockerFixture,
    admin_instance,
    rdp,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.side_effect = RemoteUnavailableError("boom")
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == str(rdp_admin_mod.DedupEngineState.unavailable())


def test_country_rdp_admin_dedup_engine_state_handles_remote_error(
    mocker: MockerFixture,
    admin_instance,
    rdp,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.side_effect = RemoteError("boom")
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == "Remote error"


def test_country_rdp_admin_change_url_happy_path(mocker: MockerFixture, admin_instance, rdp) -> None:
    mock_reverse = mocker.patch.object(rdp_admin_mod, "reverse", return_value="/ok")

    assert admin_instance._change_url(rdp) == "/ok"

    mock_reverse.assert_called_once_with("workspace:workspaces_countryrdp_change", args=[rdp.pk])


def test_country_rdp_admin_change_url_fallback_to_changelist(mocker: MockerFixture, admin_instance, rdp) -> None:
    mock_reverse = mocker.patch.object(
        rdp_admin_mod,
        "reverse",
        side_effect=[NoReverseMatch(), "/list"],
    )

    assert admin_instance._change_url(rdp) == "/list"

    assert mock_reverse.call_args_list == [
        mocker.call("workspace:workspaces_countryrdp_change", args=[rdp.pk]),
        mocker.call("workspace:workspaces_countryrdp_changelist"),
    ]


@pytest.mark.parametrize(
    ("status", "expected_visible"),
    [
        (CountryRdp.PushStatus.SUCCESS, False),
        (CountryRdp.PushStatus.PENDING, True),
        (CountryRdp.PushStatus.FAILURE, True),
    ],
    ids=["success", "pending", "failure"],
)
def test_country_rdp_admin_records_button(
    mocker: MockerFixture,
    admin_instance,
    rdp,
    status: str,
    expected_visible: bool,
) -> None:
    rdp.status = status
    owner = mocker.MagicMock(pk=777)
    policy = mocker.MagicMock(owner=owner)
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    btn = admin_instance.records.get_button({"original": rdp})
    admin_instance.records.func(None, btn)

    assert btn.visible is expected_visible
    if expected_visible:
        expected_item = "countryhousehold" if rdp.program.beneficiary_group.master_detail else "countryindividual"
        assert expected_item in btn.href
        assert "rdp__exact=777" in btn.href


@pytest.mark.parametrize(
    ("method", "description", "action", "success_message"),
    [
        (
            "deduplicate",
            "Run Deduplication process on DedupEngine",
            rdp_admin_mod.fqn(rdp_admin_mod.dedup_existing_rdp_core),
            "Dedup task scheduled",
        ),
        (
            "reject_ds",
            "Reject RDP by rejecting its active DE deduplication set",
            rdp_admin_mod.fqn(rdp_admin_mod.reject_deduplication_set_existing_rdp_core),
            "Reject task scheduled",
        ),
        (
            "push",
            "Push beneficiaries to HOPE",
            rdp_admin_mod.fqn(rdp_admin_mod.push_existing_rdp_core),
            "Push to HOPE task scheduled",
        ),
    ],
    ids=["deduplicate", "reject_ds", "push"],
)
def test_country_rdp_admin_workflow_buttons_schedule_jobs(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    rdp,
    method: str,
    description: str,
    action: str,
    success_message: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/x")

    msg_success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=mocker.Mock())
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    _assert_job(
        create,
        job,
        description=description,
        action=action,
        owner=mock_request.user,
        rdp=rdp,
    )
    msg_success.assert_called_once_with(mock_request, success_message)
    redirect.assert_called_once_with("/x")
    assert response is redirect.return_value


@pytest.mark.parametrize(
    "method",
    ["deduplicate", "reject_ds", "push", "clone_rdp"],
    ids=["deduplicate", "reject_ds", "push", "clone_rdp"],
)
def test_country_rdp_admin_buttons_redirect_when_not_found(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    method: str,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=None)
    msg_error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=mocker.Mock())

    response = getattr(admin_instance, method).func(admin_instance, mock_request, pk="999")

    msg_error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert response is redirect.return_value


def test_country_rdp_admin_clone_rdp_get_renders_form(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    rdp,
) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    form = mocker.MagicMock()
    form_cls = mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    admin_instance.get_common_context = mocker.Mock(return_value={"ctx": True})
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/list")
    render = mocker.patch.object(rdp_admin_mod, "render", return_value=mocker.MagicMock())

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

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
    assert response is render.return_value


def test_country_rdp_admin_clone_rdp_post_success(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    rdp,
) -> None:
    mock_request.method = "POST"
    mock_request.POST = {"_clone": "1"}
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/cloned")

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {"batch_name": ""}
    mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    mocker.patch.object(rdp_admin_mod, "rdi_name_default", return_value="AUTO")
    cloned = mocker.MagicMock()
    clone = mocker.patch.object(rdp_admin_mod, "clone_rdp_core", return_value=cloned)
    msg_success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=mocker.MagicMock())

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

    clone.assert_called_once_with(
        source=rdp,
        batch_name="AUTO",
        pushed_by_id=mock_request.user.id,
    )
    msg_success.assert_called_once_with(mock_request, "RDP cloned")
    redirect.assert_called_once_with("/cloned")
    assert response is redirect.return_value


def test_country_rdp_admin_clone_rdp_post_error_renders_form(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    rdp,
) -> None:
    mock_request.method = "POST"
    mock_request.POST = {"_clone": "1"}
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")

    form = mocker.MagicMock()
    form.is_valid.return_value = True
    form.cleaned_data = {"batch_name": "Batch"}
    mocker.patch.object(rdp_admin_mod, "CreateRDPForm", return_value=form)
    mocker.patch.object(rdp_admin_mod, "clone_rdp_core", side_effect=HopePushError({"errors": ["boom"]}))
    msg_error = mocker.patch.object(rdp_admin_mod.messages, "error")
    admin_instance.get_common_context = mocker.Mock(return_value={"ctx": True})
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/list")
    render = mocker.patch.object(rdp_admin_mod, "render", return_value=mocker.MagicMock())

    response = admin_instance.clone_rdp.func(admin_instance, mock_request, pk=str(rdp.pk))

    msg_error.assert_called_once()
    assert "boom" in msg_error.call_args.args[1]
    render.assert_called_once_with(mock_request, "workspace/actions/create_rdp.html", {"ctx": True})
    assert response is render.return_value
