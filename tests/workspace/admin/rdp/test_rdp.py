import pytest
from django.urls import NoReverseMatch
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.rdp.policy import ActionCheck
from country_workspace.state import state
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def async_job_factory():
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory


@pytest.mark.parametrize(
    ("obj_attr", "status", "expected"),
    [
        (None, None, ["name", "status", "push_date", "hope_rdi_id", "processing_history", "operation_log_display"]),
        (False, None, ["name", "status", "push_date", "hope_rdi_id", "processing_history", "operation_log_display"]),
        (
            True,
            CountryRdp.PushStatus.PENDING,
            [
                "name",
                "status",
                "push_date",
                "hope_rdi_id",
                "dedup_engine_state",
                "deduplication_set_id",
                "processing_history",
                "operation_log_display",
            ],
        ),
        (
            True,
            CountryRdp.PushStatus.CANCELLED,
            [
                "name",
                "status",
                "push_date",
                "hope_rdi_id",
                "deduplication_set_id",
                "processing_history",
                "operation_log_display",
            ],
        ),
    ],
    ids=["no_obj", "dedup_off", "dedup_on", "dedup_terminal"],
)
def test_get_fieldsets(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    obj_attr,
    status,
    expected,
) -> None:
    obj = None if obj_attr is None else rdp
    if obj:
        obj.program.biometric_deduplication_enabled = obj_attr
        if status:
            obj.status = status

    fields = [field for _, options in admin_instance.get_fieldsets(mock_request, obj) for field in options["fields"]]

    assert fields == expected


def test_permissions(admin_instance, mock_request, rdp: CountryRdp) -> None:
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request, rdp) is False
    assert admin_instance.has_delete_permission(mock_request, rdp) is False


def test_change_view(admin_instance, mock_request, mocker: MockerFixture) -> None:
    parent = mocker.patch.object(rdp_admin_mod.WorkspaceModelAdmin, "change_view", return_value="response")

    result = admin_instance.change_view(mock_request, "1", extra_context={"extra": "value"})

    context = parent.call_args.args[3]
    assert result == "response"
    assert context["extra"] == "value"
    assert "dedup_engine_state" in context["dynamic_field_help_texts"]
    parent.assert_called_once_with(mock_request, "1", "", context)


def test_get_queryset(admin_instance, mock_request, mocker: MockerFixture) -> None:
    qs = mocker.MagicMock()
    base = mocker.patch.object(rdp_admin_mod.WorkspaceModelAdmin, "get_queryset", return_value=qs)

    assert admin_instance.get_queryset(mock_request) is qs.select_related.return_value.filter.return_value

    base.assert_called_once_with(mock_request)
    qs.select_related.assert_called_once_with("program__beneficiary_group")
    qs.select_related.return_value.filter.assert_called_once_with(program=state.program)


def test_processing_history(
    admin_instance,
    rdp: CountryRdp,
    async_job_factory,
    mocker: MockerFixture,
) -> None:
    assert admin_instance.processing_history(rdp) == "—"

    job = async_job_factory(rdp=rdp, program=rdp.program, description="Test job", datetime_queued=None)
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/job-url")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    assert admin_instance.processing_history(rdp) == "rendered"

    row = render.call_args.args[1]["rows"][0]
    assert row == {
        "url": "/job-url",
        "step": job.description,
        "scheduled_at": "—",
        "status": job.task_status or "—",
    }


def test_operation_log_display_empty(admin_instance, rdp: CountryRdp) -> None:
    rdp.operation_log = []

    assert admin_instance.operation_log_display(rdp) == "—"


def test_operation_log_display_formats_entries(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    date_format = mocker.patch.object(rdp_admin_mod, "date_format", return_value="formatted")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    rdp.operation_log = [
        {
            "action": RdpOperationAction.START_DEDUPLICATION.value,
            "timestamp": "2026-01-02T03:04:05+00:00",
            "result": {"ok": True},
        },
        {"action": "UNKNOWN", "timestamp": "bad"},
        {},
    ]

    assert admin_instance.operation_log_display(rdp) == "rendered"

    rows = render.call_args.args[1]["rows"]
    assert rows[0]["action"] == RdpOperationAction.START_DEDUPLICATION.label
    assert rows[0]["timestamp"] == "formatted"
    assert '"ok"' in rows[0]["result"]
    assert rows[1] == {"action": "UNKNOWN", "timestamp": "bad", "result": ""}
    assert rows[2] == {"action": "—", "timestamp": "—", "result": ""}
    date_format.assert_called_once()


def test_is_visible(mocker: MockerFixture) -> None:
    obj = mocker.MagicMock()
    policy = mocker.MagicMock()
    policy.is_push_visible.return_value = True
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=obj), "is_push_visible") is True
    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=None), "is_push_visible") is False


def test_is_allowed_without_object(mocker: MockerFixture) -> None:
    get_policy = mocker.patch.object(rdp_admin_mod, "get_rdp_policy")

    assert rdp_admin_mod._is_allowed(mocker.MagicMock(original=None), "start_push_check") is False

    get_policy.assert_not_called()


@pytest.mark.parametrize(
    ("exc", "captures"),
    [
        (None, False),
        (RemoteUnavailableError("unavailable"), True),
        (RemoteError("remote"), False),
    ],
    ids=["allowed", "remote_unavailable", "remote_error"],
)
def test_is_allowed(mocker: MockerFixture, exc: Exception | None, captures: bool) -> None:
    policy = mocker.MagicMock()
    policy.start_push_check.return_value = ActionCheck(True)
    policy.start_push_check.side_effect = exc
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = rdp_admin_mod._is_allowed(mocker.MagicMock(original=mocker.MagicMock()), "start_push_check")

    assert result is (exc is None)
    assert capture.called is captures


@pytest.mark.parametrize(
    ("state_check", "expected"),
    [
        ("Ready", "Ready"),
        (RemoteUnavailableError("unavailable"), str(rdp_admin_mod.DedupEngineState.unavailable())),
        (RemoteError("remote"), "remote"),
    ],
    ids=["ok", "remote_unavailable", "remote_error"],
)
def test_dedup_engine_state(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
    state_check,
    expected,
) -> None:
    policy = mocker.MagicMock()
    if isinstance(state_check, Exception):
        policy.dedup_engine_state.side_effect = state_check
    else:
        policy.dedup_engine_state.return_value = state_check
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == expected


def test_change_url(admin_instance, rdp: CountryRdp, mocker: MockerFixture) -> None:
    reverse = mocker.patch.object(rdp_admin_mod, "reverse", side_effect=["/change", NoReverseMatch(), "/list"])

    assert admin_instance._change_url(rdp) == "/change"
    assert admin_instance._change_url(rdp) == "/list"
    assert reverse.call_args_list == [
        mocker.call("workspace:workspaces_countryrdp_change", args=[rdp.pk]),
        mocker.call("workspace:workspaces_countryrdp_change", args=[rdp.pk]),
        mocker.call("workspace:workspaces_countryrdp_changelist"),
    ]


@pytest.mark.parametrize(
    "case",
    [
        (ActionCheck(True), None, False),
        (ActionCheck(False, "blocked"), "blocked", False),
        (ActionCheck(False), "Action is not allowed.", False),
        (RemoteUnavailableError("unavailable"), "unavailable", True),
        (RemoteError("remote"), "remote", False),
    ],
    ids=["allowed", "blocked", "default_reason", "remote_unavailable", "remote_error"],
)
def test_deny_if_not_allowed(admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture, case) -> None:
    check, message, captures = case
    policy = mocker.MagicMock()
    if isinstance(check, Exception):
        policy.cancel_check.side_effect = check
    else:
        policy.cancel_check.return_value = check
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    admin_instance._change_url = mocker.MagicMock(return_value="/change")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = admin_instance._deny_if_not_allowed(mock_request, rdp, "cancel_check")

    assert result == (None if message is None else "response")
    assert capture.called is captures

    if message is None:
        error.assert_not_called()
        redirect.assert_not_called()
    else:
        error.assert_called_once_with(mock_request, message)
        redirect.assert_called_once_with("/change")
