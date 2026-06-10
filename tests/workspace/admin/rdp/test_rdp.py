import pytest
from django.urls import NoReverseMatch
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.state import state
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("has_obj", "dedup_enabled", "expected"),
    [
        (
            False,
            False,
            ["name", "parent", "push_date", "status", "related_jobs"],
        ),
        (
            True,
            False,
            ["name", "parent", "push_date", "status", "related_jobs"],
        ),
        (
            True,
            True,
            [
                "name",
                "parent",
                "push_date",
                "status",
                "dedup_engine_state",
                "deduplication_set_id",
                "deduplication_snapshots",
                "related_jobs",
            ],
        ),
    ],
    ids=["no_obj", "dedup_off", "dedup_on"],
)
def test_get_fields_and_readonly_fields(
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


def test_permissions(admin_instance, mock_request, rdp) -> None:
    assert admin_instance.has_add_permission(mock_request) is False
    assert admin_instance.has_change_permission(mock_request, rdp) is False
    assert admin_instance.has_delete_permission(mock_request, rdp) is False


def test_get_common_context(
    admin_instance,
    mock_request,
    mocker: MockerFixture,
) -> None:
    base = mocker.patch.object(
        rdp_admin_mod.WorkspaceModelAdmin,
        "get_common_context",
        return_value={"ok": True},
    )

    result = admin_instance.get_common_context(mock_request, pk="1", title="T")

    assert result == {"ok": True}
    base.assert_called_once_with(
        mock_request,
        "1",
        title="T",
        modeladmin=admin_instance,
        modeladmin_name="CountryRdpAdmin",
    )


def test_get_queryset(
    admin_instance,
    mock_request,
    program,
    mocker: MockerFixture,
) -> None:
    base_qs = mocker.MagicMock()
    selected_qs = mocker.MagicMock()
    filtered_qs = mocker.MagicMock()

    base = mocker.patch.object(rdp_admin_mod.WorkspaceModelAdmin, "get_queryset", return_value=base_qs)
    base_qs.select_related.return_value = selected_qs
    selected_qs.filter.return_value = filtered_qs

    result = admin_instance.get_queryset(mock_request)

    assert result is filtered_qs
    base.assert_called_once_with(mock_request)
    base_qs.select_related.assert_called_once_with("program__beneficiary_group")
    selected_qs.filter.assert_called_once_with(program=state.program)


def test_related_jobs_empty(admin_instance, rdp) -> None:
    assert admin_instance.related_jobs(rdp) == "-"


def test_related_jobs_renders_links(
    admin_instance,
    rdp,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import AsyncJobFactory

    job = AsyncJobFactory(rdp=rdp, program=rdp.program)
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/job-url")

    result = str(admin_instance.related_jobs(rdp))

    assert "/job-url" in result
    assert str(job) in result


def test_is_visible(mocker: MockerFixture) -> None:
    obj = mocker.MagicMock()
    btn = mocker.MagicMock(original=obj)
    policy = mocker.MagicMock()
    policy.is_push_visible.return_value = True

    get_policy = mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert rdp_admin_mod._is_visible(btn, "is_push_visible") is True
    assert rdp_admin_mod._is_visible(mocker.MagicMock(original=None), "is_push_visible") is False

    get_policy.assert_called_once_with(obj)
    policy.is_push_visible.assert_called_once_with()


def test_is_allowed_returns_check_result(mocker: MockerFixture) -> None:
    obj = mocker.MagicMock()
    btn = mocker.MagicMock(original=obj)
    policy = mocker.MagicMock()
    policy.push_check.return_value = ActionCheck(True)

    get_policy = mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert rdp_admin_mod._is_allowed(btn, "push_check") is True
    assert rdp_admin_mod._is_allowed(mocker.MagicMock(original=None), "push_check") is False

    get_policy.assert_called_once_with(obj)
    policy.push_check.assert_called_once_with()


def test_is_allowed_returns_false_on_remote_unavailable(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.push_check.side_effect = RemoteUnavailableError("boom")

    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = rdp_admin_mod._is_allowed(mocker.MagicMock(original=mocker.MagicMock()), "push_check")

    assert result is False
    capture.assert_called_once()


def test_is_allowed_returns_false_on_remote_error(mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.push_check.side_effect = RemoteError("boom")

    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = rdp_admin_mod._is_allowed(mocker.MagicMock(original=mocker.MagicMock()), "push_check")

    assert result is False
    capture.assert_not_called()


def test_dedup_engine_state_returns_policy_value(
    admin_instance,
    rdp,
    mocker: MockerFixture,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.return_value = "Ready to start"
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == "Ready to start"


def test_dedup_engine_state_handles_remote_unavailable(
    admin_instance,
    rdp,
    mocker: MockerFixture,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.side_effect = RemoteUnavailableError("boom")
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == str(rdp_admin_mod.DedupEngineState.unavailable())


def test_dedup_engine_state_handles_remote_error(
    admin_instance,
    rdp,
    mocker: MockerFixture,
) -> None:
    policy = mocker.MagicMock()
    policy.dedup_engine_state.side_effect = RemoteError("boom")
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)

    assert admin_instance.dedup_engine_state(rdp) == "boom"


def test_change_url_happy_path(admin_instance, rdp, mocker: MockerFixture) -> None:
    reverse = mocker.patch.object(rdp_admin_mod, "reverse", return_value="/ok")

    assert admin_instance._change_url(rdp) == "/ok"

    reverse.assert_called_once_with("workspace:workspaces_countryrdp_change", args=[rdp.pk])


def test_change_url_fallback_to_changelist(admin_instance, rdp, mocker: MockerFixture) -> None:
    reverse = mocker.patch.object(
        rdp_admin_mod,
        "reverse",
        side_effect=[NoReverseMatch(), "/list"],
    )

    assert admin_instance._change_url(rdp) == "/list"

    assert reverse.call_args_list == [
        mocker.call("workspace:workspaces_countryrdp_change", args=[rdp.pk]),
        mocker.call("workspace:workspaces_countryrdp_changelist"),
    ]


@pytest.mark.parametrize(
    ("allowed", "reason", "expected"),
    [
        (True, None, None),
        (False, "blocked", "response"),
    ],
    ids=["allowed", "blocked"],
)
def test_deny_if_not_allowed(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
    allowed: bool,
    reason: str | None,
    expected: str | None,
) -> None:
    policy = mocker.MagicMock()
    policy.push_check.return_value = ActionCheck(allowed, reason)
    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    admin_instance._change_url = mocker.MagicMock(return_value="/change")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    result = admin_instance._deny_if_not_allowed(mock_request, rdp, "push_check")

    assert result == expected
    if allowed:
        error.assert_not_called()
        redirect.assert_not_called()
    else:
        error.assert_called_once_with(mock_request, "blocked")
        redirect.assert_called_once_with("/change")


@pytest.mark.parametrize(
    ("exc", "captures"),
    [
        (RemoteUnavailableError("unavailable"), True),
        (RemoteError("remote"), False),
    ],
    ids=["remote_unavailable", "remote_error"],
)
def test_deny_if_not_allowed_handles_remote_errors(
    admin_instance,
    mock_request,
    rdp,
    mocker: MockerFixture,
    exc: Exception,
    captures: bool,
) -> None:
    policy = mocker.MagicMock()
    policy.push_check.side_effect = exc

    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    admin_instance._change_url = mocker.MagicMock(return_value="/change")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")
    capture = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    result = admin_instance._deny_if_not_allowed(mock_request, rdp, "push_check")

    assert result == "response"
    error.assert_called_once_with(mock_request, str(exc))
    redirect.assert_called_once_with("/change")
    assert capture.called is captures


@pytest.mark.parametrize(
    ("status", "expected_visible"),
    [
        (CountryRdp.PushStatus.MERGED, False),
        (CountryRdp.PushStatus.PENDING, True),
        (CountryRdp.PushStatus.FAILURE, True),
    ],
    ids=["merged", "pending", "failure"],
)
def test_records_button(
    admin_instance,
    rdp,
    mocker: MockerFixture,
    status: str,
    expected_visible: bool,
) -> None:
    rdp.status = status
    owner = mocker.MagicMock(pk=777)
    policy = mocker.MagicMock(owner=owner)

    mocker.patch.object(rdp_admin_mod, "get_rdp_policy", return_value=policy)
    mocker.patch.object(rdp_admin_mod, "reverse", return_value="/records")

    btn = admin_instance.records.get_button({"original": rdp})
    admin_instance.records.func(None, btn)

    assert btn.visible is expected_visible
    if expected_visible:
        expected_item = "countryhousehold" if rdp.program.beneficiary_group.master_detail else "countryindividual"
        assert btn.href == "/records?rdp__exact=777"
        rdp_admin_mod.reverse.assert_called_with(f"workspace:workspaces_{expected_item}_changelist")
