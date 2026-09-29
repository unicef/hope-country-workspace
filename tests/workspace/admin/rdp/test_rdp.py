import pytest
from django.urls import NoReverseMatch
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import AsyncJob, RdpOperation
from country_workspace.models.rdp import RdpLogEntryType
from country_workspace.rdp.policy import ActionCheck
from country_workspace.state import state
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import RdpOperationFactory

    return RdpOperationFactory(rdp=rdp)


@pytest.fixture
def successful_biometric_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import RdpOperationFactory, RdpOperationFindingFactory

    operation = RdpOperationFactory(
        rdp=rdp,
        status=RdpOperation.Status.SUCCESS,
        attempt=2,
        config={"threshold_type": "COUNT", "threshold_value": "3"},
        log=[
            {
                "action": "APPROVE_DEDUPLICATION_SET",
                "timestamp": "2026-01-02T03:04:05+00:00",
                "result": {"success": True},
            }
        ],
    )
    RdpOperationFindingFactory(operation=operation)
    return operation


@pytest.fixture
def failed_biometric_operation(rdp: CountryRdp) -> RdpOperation:
    from testutils.factories import RdpOperationFactory

    return RdpOperationFactory(
        rdp=rdp,
        status=RdpOperation.Status.FAILURE,
        error={"code": "remote_error", "message": "Something failed"},
    )


@pytest.fixture
def async_job(rdp: CountryRdp) -> AsyncJob:
    from testutils.factories import AsyncJobFactory

    return AsyncJobFactory(rdp=rdp, program=rdp.program, description="Test job", datetime_queued=None)


def test_get_fieldsets_without_operations(admin_instance, mock_request, rdp: CountryRdp) -> None:
    fields = [field for _, options in admin_instance.get_fieldsets(mock_request, rdp) for field in options["fields"]]

    assert "operations_display" not in fields
    assert "rdp_log_display" in fields


def test_get_fieldsets_with_operations(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    rdp_operation: RdpOperation,
) -> None:
    fields = [field for _, options in admin_instance.get_fieldsets(mock_request, rdp) for field in options["fields"]]

    assert "operations_display" in fields


def test_permissions(admin_instance, mock_request, rdp: CountryRdp) -> None:
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request, rdp) is False
    assert admin_instance.has_delete_permission(mock_request, rdp) is False


def test_get_queryset(admin_instance, mock_request, mocker: MockerFixture) -> None:
    queryset = mocker.MagicMock()
    base = mocker.patch.object(rdp_admin_mod.WorkspaceModelAdmin, "get_queryset", return_value=queryset)

    result = admin_instance.get_queryset(mock_request)

    assert result is queryset.select_related.return_value.filter.return_value
    base.assert_called_once_with(mock_request)
    queryset.select_related.assert_called_once_with("program__beneficiary_group")
    queryset.select_related.return_value.filter.assert_called_once_with(program=state.program)


def test_operations_display_empty(admin_instance, rdp: CountryRdp) -> None:
    assert admin_instance.operations_display(rdp) == "-"


def test_operations_display_successful_biometric(
    admin_instance,
    successful_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    duplicates = mocker.patch.object(rdp_admin_mod, "qs_biometric_duplicate_individuals")
    duplicates.return_value.count.return_value = 2
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    assert admin_instance.operations_display(successful_biometric_operation.rdp) == "rendered"

    row = render.call_args.args[1]["rows"][0]
    assert row["id"] == str(successful_biometric_operation.id)
    assert row["status"] == successful_biometric_operation.get_status_display()
    assert row["attempts"] == 2
    assert row["findings"] == 1
    assert row["marked_individuals"] == 2
    assert '"threshold_type": "COUNT"' in row["config"]
    assert '"success": true' in row["log"][0]["result"]
    duplicates.assert_called_once_with(operation=successful_biometric_operation)


def test_operations_display_failed_biometric(
    admin_instance,
    failed_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    duplicates = mocker.patch.object(rdp_admin_mod, "qs_biometric_duplicate_individuals")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    admin_instance.operations_display(failed_biometric_operation.rdp)

    row = render.call_args.args[1]["rows"][0]
    assert '"code": "remote_error"' in row["error"]
    assert row["findings"] is None
    assert row["marked_individuals"] is None
    duplicates.assert_not_called()


def test_processing_history_empty(admin_instance, rdp: CountryRdp) -> None:
    assert admin_instance.processing_history(rdp) == "-"


def test_processing_history(
    admin_instance,
    async_job: AsyncJob,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/job-url")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    assert admin_instance.processing_history(async_job.rdp) == "rendered"

    row = render.call_args.args[1]["rows"][0]
    assert row["url"] == "/job-url"
    assert row["step"] == async_job.description
    assert row["status"] == (async_job.task_status or "-")
    assert row["scheduled_at"] == "-"


def test_rdp_log_display_empty(admin_instance, rdp: CountryRdp) -> None:
    assert admin_instance.rdp_log_display(rdp) == "-"


def test_rdp_log_display(
    admin_instance,
    rdp: CountryRdp,
    mocker: MockerFixture,
) -> None:
    rdp.operation_log = [
        {
            "action": RdpLogEntryType.REVIEW_REQUIRED.value,
            "timestamp": "2026-01-02T03:04:05+00:00",
            "result": {"count": 3},
        }
    ]
    mocker.patch.object(rdp_admin_mod, "date_format", return_value="formatted")
    render = mocker.patch.object(rdp_admin_mod, "render_to_string", return_value="rendered")

    assert admin_instance.rdp_log_display(rdp) == "rendered"

    row = render.call_args.args[1]["rows"][0]
    assert row["action"] == RdpLogEntryType.REVIEW_REQUIRED.label
    assert row["timestamp"] == "formatted"
    assert '"count": 3' in row["result"]


def test_is_visible(mocker: MockerFixture) -> None:
    obj = mocker.MagicMock()
    policy = mocker.MagicMock()
    policy.is_cancel_visible.return_value = True
    get_policy = mocker.Mock(return_value=policy)

    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=obj), get_policy, "is_cancel_visible") is True
    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=None), get_policy, "is_cancel_visible") is False

    get_policy.assert_called_once_with(obj)


@pytest.mark.parametrize(
    ("check", "expected", "captures"),
    [
        (ActionCheck(True), True, False),
        (ActionCheck(False), False, False),
        (RemoteUnavailableError("unavailable"), False, True),
        (RemoteError("remote"), False, False),
    ],
    ids=["allowed", "denied", "unavailable", "remote_error"],
)
def test_is_allowed(
    mocker: MockerFixture,
    check: ActionCheck | Exception,
    expected: bool,
    captures: bool,
) -> None:
    policy = mocker.MagicMock()
    if isinstance(check, Exception):
        policy.cancel_check.side_effect = check
    else:
        policy.cancel_check.return_value = check

    get_policy = mocker.Mock(return_value=policy)
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = rdp_admin_mod._is_allowed(
        mocker.MagicMock(original=mocker.MagicMock()),
        get_policy,
        "cancel_check",
    )

    assert result is expected
    assert capture.called is captures


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
    ("check", "message_fragment", "captures"),
    [
        (ActionCheck(True), None, False),
        (ActionCheck(False, "blocked"), "blocked", False),
        (ActionCheck(False), "not allowed", False),
        (RemoteUnavailableError("unavailable"), "unavailable", True),
        (RemoteError("remote"), "remote", False),
    ],
    ids=["allowed", "denied", "denied_without_reason", "unavailable", "remote_error"],
)
def test_deny_if_not_allowed(
    admin_instance,
    mock_request,
    rdp: CountryRdp,
    mocker: MockerFixture,
    check: ActionCheck | Exception,
    message_fragment: str | None,
    captures: bool,
) -> None:
    policy = mocker.MagicMock()
    if isinstance(check, Exception):
        policy.cancel_check.side_effect = check
    else:
        policy.cancel_check.return_value = check

    get_policy = mocker.Mock(return_value=policy)
    mocker.patch.object(admin_instance, "_change_url", return_value="/change")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = admin_instance._deny_if_not_allowed(mock_request, rdp, get_policy, "cancel_check")

    assert capture.called is captures

    if message_fragment is None:
        assert result is None
        error.assert_not_called()
        redirect.assert_not_called()
    else:
        assert result == "response"
        assert message_fragment in error.call_args.args[1]
        redirect.assert_called_once_with("/change")
