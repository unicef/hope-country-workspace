from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.urls import NoReverseMatch

from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError
from country_workspace.state import state
from country_workspace.workspaces.admin.rdp import CountryRdpAdmin
from country_workspace.workspaces.models import CountryRdp

from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.workspaces.admin import rdp as rdp_admin_mod


UNICEF_ID = "office-p"


@pytest.fixture
def office():
    from testutils.factories import OfficeFactory

    co = OfficeFactory()
    state.tenant = co
    return co


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request):
    return request.param


@pytest.fixture(params=[True, False])
def job(request, rdp):
    from testutils.factories import AsyncJobFactory

    if request.param:
        return AsyncJobFactory(rdp=rdp, program=rdp.program)
    return None


@pytest.fixture
def program(office, master_detail):
    from testutils.factories import CountryProgramFactory

    program = CountryProgramFactory(country_office=office, beneficiary_group__master_detail=master_detail)
    state.program = program
    return program


@pytest.fixture
def rdp(program):
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(program=program)


@pytest.fixture
def admin_instance():
    return CountryRdpAdmin(model=CountryRdp, admin_site=MagicMock())


@pytest.fixture
def mock_request():
    request = MagicMock(spec=HttpRequest)
    request.user = MagicMock(spec=User)
    return request


def test_country_rdp_admin_permissions_and_context(admin_instance, mock_request):
    assert admin_instance.has_add_permission(mock_request) is False

    result = admin_instance.get_common_context(mock_request, pk="1")
    assert result["modeladmin"] == admin_instance
    assert result["modeladmin_name"] == "CountryRdpAdmin"

    assert admin_instance.get_queryset(mock_request) is not None


def test_country_rdp_admin_related_job(admin_instance, rdp, job):
    result = admin_instance.related_job(rdp)

    if job:
        assert "/workspaces/countryasyncjob/" in result
        assert "/change/" in result
    else:
        assert result == "-"


@pytest.mark.parametrize(
    ("status", "expected_visible"),
    [
        (CountryRdp.PushStatus.SUCCESS, False),
        (CountryRdp.PushStatus.PENDING, True),
        (CountryRdp.PushStatus.FAILURE, True),
    ],
    ids=["success", "pending", "failure"],
)
def test_country_rdp_admin_records_button(admin_instance, rdp, status, expected_visible):
    rdp.status = status

    btn = admin_instance.records.get_button({"original": rdp})
    admin_instance.records.func(None, btn)

    assert btn.visible is expected_visible
    if expected_visible:
        expected_item = "countryhousehold" if rdp.program.beneficiary_group.master_detail else "countryindividual"
        assert expected_item in btn.href
        assert f"rdp__exact={rdp.pk}" in btn.href


def _assert_job(create, job, *, action, owner, rdp):
    create.assert_called_once()
    kwargs = create.call_args.kwargs
    assert kwargs["action"] == action
    assert kwargs["owner"] == owner
    assert kwargs["program"] == rdp.program
    assert kwargs["rdp"] == rdp
    assert kwargs["config"] == {"rdp_id": rdp.pk}
    job.queue.assert_called_once_with()


def test_dedup_status_safe_returns_client_status(mocker: MockerFixture) -> None:
    expected = mocker.Mock()
    client = mocker.MagicMock()
    client.status.return_value = expected

    cm = mocker.MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False

    mocker.patch.object(rdp_admin_mod, "make_client", return_value=cm)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    assert rdp_admin_mod._dedup_status_safe(UNICEF_ID) is expected
    client.status.assert_called_once_with()
    cap.assert_not_called()


def test_dedup_status_safe_returns_status_unavailable_on_remote_error(mocker: MockerFixture) -> None:
    cm = mocker.MagicMock()
    cm.__enter__.side_effect = RemoteError("boom")
    cm.__exit__.return_value = False

    mocker.patch.object(rdp_admin_mod, "make_client", return_value=cm)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    res = rdp_admin_mod._dedup_status_safe(UNICEF_ID)

    assert res.status == DedupResponseStatus.STATUS_UNAVAILABLE
    assert res.duplicates_found == -1
    cap.assert_called_once()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (CountryRdp.PushStatus.PENDING, True),
        (CountryRdp.PushStatus.SUCCESS, False),
        (CountryRdp.PushStatus.FAILURE, False),
    ],
    ids=["pending", "success", "failure"],
)
def test_visible_workflow(mocker: MockerFixture, status, expected):
    obj = mocker.MagicMock(status=status, PushStatus=CountryRdp.PushStatus)
    assert rdp_admin_mod.visible_workflow(mocker.MagicMock(original=obj)) is expected
    assert rdp_admin_mod.visible_workflow(mocker.MagicMock(original=None)) is False


def test_visible_reject_ds(mocker: MockerFixture) -> None:
    btn = mocker.MagicMock()
    btn.original = mocker.MagicMock()
    btn.original.program.biometric_deduplication_enabled = True
    btn.original.deduplication_set_id = "DS-1"

    assert rdp_admin_mod.visible_reject_ds(btn) is True

    btn.original.program.biometric_deduplication_enabled = False
    assert rdp_admin_mod.visible_reject_ds(btn) is False

    btn.original.program.biometric_deduplication_enabled = True
    btn.original.deduplication_set_id = ""
    assert rdp_admin_mod.visible_reject_ds(btn) is False
    assert rdp_admin_mod.visible_reject_ds(mocker.MagicMock(original=None)) is False


@pytest.mark.parametrize(
    ("dedup_enabled", "set_id", "de_status", "expected"),
    [
        (False, "DS-1", None, False),
        (True, "", None, False),
        (True, "DS-1", DedupResponseStatus.SUCCESS, True),
        (True, "DS-1", DedupResponseStatus.DS_NOT_EXPOSED, False),
        (True, "DS-1", DedupResponseStatus.STATUS_UNAVAILABLE, False),
    ],
    ids=["dedup_off", "no_set_id", "success", "ds_not_exposed", "status_unavailable"],
)
def test_enabled_reject_ds(mocker: MockerFixture, dedup_enabled, set_id, de_status, expected):
    btn = mocker.MagicMock()
    btn.original = mocker.MagicMock()
    btn.original.program.biometric_deduplication_enabled = dedup_enabled
    btn.original.program.unicef_id = UNICEF_ID
    btn.original.deduplication_set_id = set_id

    safe = mocker.patch.object(
        rdp_admin_mod,
        "_dedup_status_safe",
        return_value=mocker.MagicMock(status=de_status),
    )

    assert rdp_admin_mod.enabled_reject_ds(btn) is expected
    if dedup_enabled and set_id:
        safe.assert_called_once_with(UNICEF_ID)
    else:
        safe.assert_not_called()
    assert rdp_admin_mod.enabled_reject_ds(mocker.MagicMock(original=None)) is False


@pytest.mark.parametrize(
    ("dedup_enabled", "dedup_state", "de_status", "expected"),
    [
        (False, CountryRdp.DedupRunState.NOT_RUN, None, False),
        (True, CountryRdp.DedupRunState.NOT_RUN, None, True),
        (True, CountryRdp.DedupRunState.FINISHED, None, False),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.FAILURE, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.REVOKED, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.DS_NOT_EXPOSED, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.STATUS_UNAVAILABLE, False),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.SUCCESS, False),
    ],
    ids=[
        "dedup_off",
        "not_run",
        "finished",
        "in_progress_failure",
        "in_progress_revoked",
        "in_progress_ds_not_exposed",
        "in_progress_status_unavailable",
        "in_progress_success",
    ],
)
def test_enabled_deduplicate(mocker: MockerFixture, dedup_enabled, dedup_state, de_status, expected):
    btn = mocker.MagicMock()
    btn.original = mocker.MagicMock()
    btn.original.status = CountryRdp.PushStatus.PENDING
    btn.original.PushStatus = CountryRdp.PushStatus
    btn.original.DedupRunState = CountryRdp.DedupRunState
    btn.original.dedup_run_state = dedup_state
    btn.original.program.biometric_deduplication_enabled = dedup_enabled
    btn.original.program.unicef_id = UNICEF_ID

    safe = mocker.patch.object(
        rdp_admin_mod,
        "_dedup_status_safe",
        return_value=mocker.MagicMock(status=de_status),
    )

    assert rdp_admin_mod.enabled_deduplicate(btn) is expected
    if dedup_enabled and dedup_state == CountryRdp.DedupRunState.IN_PROGRESS:
        safe.assert_called_once_with(UNICEF_ID)
    else:
        safe.assert_not_called()

    btn.original.status = CountryRdp.PushStatus.SUCCESS
    assert rdp_admin_mod.enabled_deduplicate(btn) is False
    assert rdp_admin_mod.enabled_deduplicate(mocker.MagicMock(original=None)) is False


@pytest.mark.parametrize(
    ("dedup_enabled", "dedup_state", "de_status", "expected"),
    [
        (False, CountryRdp.DedupRunState.NOT_RUN, None, True),
        (True, CountryRdp.DedupRunState.NOT_RUN, None, False),
        (True, CountryRdp.DedupRunState.FINISHED, None, False),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.SUCCESS, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.FAILURE, False),
    ],
    ids=["dedup_off", "not_run", "finished", "in_progress_success", "in_progress_failure"],
)
def test_enabled_push(mocker: MockerFixture, dedup_enabled, dedup_state, de_status, expected):
    btn = mocker.MagicMock()
    btn.original = mocker.MagicMock()
    btn.original.status = CountryRdp.PushStatus.PENDING
    btn.original.PushStatus = CountryRdp.PushStatus
    btn.original.DedupRunState = CountryRdp.DedupRunState
    btn.original.dedup_run_state = dedup_state
    btn.original.program.biometric_deduplication_enabled = dedup_enabled
    btn.original.program.unicef_id = UNICEF_ID

    safe = mocker.patch.object(
        rdp_admin_mod,
        "_dedup_status_safe",
        return_value=mocker.MagicMock(status=de_status),
    )

    assert rdp_admin_mod.enabled_push(btn) is expected
    if dedup_enabled and dedup_state == CountryRdp.DedupRunState.IN_PROGRESS:
        safe.assert_called_once_with(UNICEF_ID)
    else:
        safe.assert_not_called()

    btn.original.status = CountryRdp.PushStatus.SUCCESS
    assert rdp_admin_mod.enabled_push(btn) is False
    assert rdp_admin_mod.enabled_push(mocker.MagicMock(original=None)) is False


@pytest.mark.parametrize(
    ("rdp_status", "dedup_state", "de_status", "findings", "expected"),
    [
        (CountryRdp.PushStatus.SUCCESS, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.SUCCESS, 3, "N/A"),
        (CountryRdp.PushStatus.PENDING, CountryRdp.DedupRunState.NOT_RUN, DedupResponseStatus.SUCCESS, 3, "N/A"),
        (
            CountryRdp.PushStatus.PENDING,
            CountryRdp.DedupRunState.IN_PROGRESS,
            DedupResponseStatus.FAILURE,
            3,
            "failure",
        ),
        (
            CountryRdp.PushStatus.PENDING,
            CountryRdp.DedupRunState.IN_PROGRESS,
            DedupResponseStatus.SUCCESS,
            7,
            "success with findings=7",
        ),
    ],
    ids=["not_pending", "pending_not_in_progress", "pending_in_progress_failure", "pending_in_progress_success"],
)
def test_country_rdp_admin_dedup_engine_state(
    mocker: MockerFixture,
    admin_instance,
    rdp,
    rdp_status,
    dedup_state,
    de_status,
    findings,
    expected,
):
    rdp.status = rdp_status
    rdp.dedup_run_state = dedup_state

    mocker.patch.object(
        rdp_admin_mod,
        "_dedup_status_safe",
        return_value=mocker.MagicMock(status=de_status, duplicates_found=findings),
    )

    assert admin_instance.dedup_engine_state(rdp) == expected


@pytest.mark.parametrize(
    ("method", "action"),
    [
        ("deduplicate", rdp_admin_mod.fqn(rdp_admin_mod.dedup_existing_rdp_core)),
        ("reject_ds", rdp_admin_mod.fqn(rdp_admin_mod.reject_deduplication_set_existing_rdp_core)),
        ("push", rdp_admin_mod.fqn(rdp_admin_mod.push_existing_rdp_core)),
    ],
    ids=["deduplicate", "reject_ds", "push"],
)
@pytest.mark.django_db
def test_country_rdp_admin_workflow_buttons_schedule_jobs(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    rdp,
    method,
    action,
):
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/x")

    mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=mocker.Mock())
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)

    resp = getattr(admin_instance, method).func(admin_instance, mock_request, pk=str(rdp.pk))

    _assert_job(create, job, action=action, owner=mock_request.user, rdp=rdp)
    redirect.assert_called_once_with("/x")
    assert resp is redirect.return_value


@pytest.mark.parametrize("method", ["deduplicate", "push"], ids=["deduplicate", "push"])
@pytest.mark.django_db
def test_country_rdp_admin_workflow_buttons_redirect_when_not_found(
    mocker: MockerFixture,
    admin_instance,
    mock_request,
    method,
):
    admin_instance.get_object = mocker.Mock(return_value=None)
    msg_error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=mocker.Mock())

    resp = getattr(admin_instance, method).func(admin_instance, mock_request, pk="999")

    msg_error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert resp is redirect.return_value


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


@pytest.mark.parametrize("flag", [True, False], ids=["enabled", "disabled"])
def test_country_rdp_admin_biometric_deduplication_enabled(admin_instance, rdp, flag: bool) -> None:
    rdp.program.biometric_deduplication_enabled = flag
    assert admin_instance.biometric_deduplication_enabled(rdp) is flag
