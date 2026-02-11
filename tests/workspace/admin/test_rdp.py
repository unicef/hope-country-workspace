from unittest.mock import MagicMock

import pytest
from django.contrib.auth.models import User
from django.http import HttpRequest
from django.urls import NoReverseMatch

from requests.exceptions import RequestException
from pytest_mock import MockerFixture

from country_workspace.state import state
from country_workspace.workspaces.admin.rdp import CountryRdpAdmin
from country_workspace.workspaces.models import CountryRdp


from country_workspace.contrib.dedup_engine.response import Status as DedupResponseStatus
from country_workspace.workspaces.admin import rdp as rdp_admin_mod


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


def _btn_for(obj):
    return MagicMock(original=obj)


def test_dedup_status_safe_returns_client_status(mocker: MockerFixture) -> None:
    expected = mocker.Mock()

    client = mocker.MagicMock()
    client.status.return_value = expected

    cm = mocker.MagicMock()
    cm.__enter__.return_value = client
    cm.__exit__.return_value = False

    mocker.patch.object(rdp_admin_mod, "make_client", return_value=cm)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    assert rdp_admin_mod._dedup_status_safe("P") is expected

    client.status.assert_called_once_with()
    cap.assert_not_called()


def test_dedup_status_safe_returns_unknown_on_request_exception(mocker: MockerFixture) -> None:
    cm = mocker.MagicMock()
    cm.__enter__.side_effect = RequestException("boom")
    cm.__exit__.return_value = False

    mocker.patch.object(rdp_admin_mod, "make_client", return_value=cm)
    cap = mocker.patch.object(rdp_admin_mod.sentry_sdk, "capture_exception")

    res = rdp_admin_mod._dedup_status_safe("P")

    assert res.status == DedupResponseStatus.UNKNOWN
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
def test_visible_workflow(status, expected):
    obj = MagicMock(status=status, PushStatus=CountryRdp.PushStatus)
    assert rdp_admin_mod.visible_workflow(_btn_for(obj)) is expected
    assert rdp_admin_mod.visible_workflow(_btn_for(None)) is False


@pytest.mark.parametrize(
    ("dedup_enabled", "dedup_state", "de_status", "expected"),
    [
        (False, CountryRdp.DedupRunState.NOT_RUN, None, False),
        (True, CountryRdp.DedupRunState.NOT_RUN, None, True),
        (True, CountryRdp.DedupRunState.FINISHED, None, False),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.FAILURE, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.REVOKED, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.UNKNOWN, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.NOT_SCHEDULED, True),
        (True, CountryRdp.DedupRunState.IN_PROGRESS, DedupResponseStatus.SUCCESS, False),
    ],
    ids=[
        "dedup_off",
        "not_run",
        "finished",
        "in_progress_failure",
        "in_progress_revoked",
        "in_progress_unknown",
        "in_progress_not_scheduled",
        "in_progress_success",
    ],
)
def test_enabled_deduplicate(mocker: MockerFixture, dedup_enabled, dedup_state, de_status, expected):
    obj = MagicMock(
        status=CountryRdp.PushStatus.PENDING,
        PushStatus=CountryRdp.PushStatus,
        DedupRunState=CountryRdp.DedupRunState,
        dedup_run_state=dedup_state,
        program=MagicMock(biometric_deduplication_enabled=dedup_enabled, code="P"),
    )
    if dedup_state == CountryRdp.DedupRunState.IN_PROGRESS:
        mocker.patch.object(
            rdp_admin_mod,
            "_dedup_status_safe",
            return_value=MagicMock(status=de_status),
        )

    assert rdp_admin_mod.enabled_deduplicate(_btn_for(obj)) is expected

    obj.status = CountryRdp.PushStatus.SUCCESS
    assert rdp_admin_mod.enabled_deduplicate(_btn_for(obj)) is False
    assert rdp_admin_mod.enabled_deduplicate(_btn_for(None)) is False


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
    obj = MagicMock(
        status=CountryRdp.PushStatus.PENDING,
        PushStatus=CountryRdp.PushStatus,
        DedupRunState=CountryRdp.DedupRunState,
        dedup_run_state=dedup_state,
        program=MagicMock(biometric_deduplication_enabled=dedup_enabled, code="P"),
    )
    if dedup_enabled and dedup_state == CountryRdp.DedupRunState.IN_PROGRESS:
        mocker.patch.object(
            rdp_admin_mod,
            "_dedup_status_safe",
            return_value=MagicMock(status=de_status),
        )

    assert rdp_admin_mod.enabled_push(_btn_for(obj)) is expected

    obj.status = CountryRdp.PushStatus.SUCCESS
    assert rdp_admin_mod.enabled_push(_btn_for(obj)) is False
    assert rdp_admin_mod.enabled_push(_btn_for(None)) is False


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
    mocker: MockerFixture, admin_instance, rdp, rdp_status, dedup_state, de_status, findings, expected
):
    rdp.status = rdp_status
    rdp.dedup_run_state = dedup_state

    mocker.patch.object(
        rdp_admin_mod,
        "_dedup_status_safe",
        return_value=MagicMock(status=de_status, duplicates_found=findings),
    )

    assert admin_instance.dedup_engine_state(rdp) == expected


@pytest.mark.django_db
def test_country_rdp_admin_deduplicate_schedules_job_and_updates_state(
    mocker: MockerFixture, admin_instance, mock_request, rdp
):
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/x")

    msg_success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=MagicMock())

    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)

    qs = mocker.MagicMock()
    mocker.patch.object(rdp._meta.model.objects, "filter", return_value=qs)

    resp = admin_instance.deduplicate.func(admin_instance, mock_request, pk=str(rdp.pk))

    create.assert_called_once()
    job.queue.assert_called_once()
    qs.update.assert_called_once_with(dedup_run_state=rdp.DedupRunState.IN_PROGRESS)
    msg_success.assert_called_once()
    redirect.assert_called_once_with("/x")
    assert resp is redirect.return_value


@pytest.mark.django_db
def test_country_rdp_admin_push_schedules_job(mocker: MockerFixture, admin_instance, mock_request, rdp):
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/x")

    msg_success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value=MagicMock())

    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)

    resp = admin_instance.push.func(admin_instance, mock_request, pk=str(rdp.pk))

    create.assert_called_once()
    job.queue.assert_called_once()
    msg_success.assert_called_once()
    redirect.assert_called_once_with("/x")
    assert resp is redirect.return_value


@pytest.mark.django_db
def test_country_rdp_admin_deduplicate_when_not_found_redirects(mocker: MockerFixture, admin_instance, mock_request):
    mod = rdp_admin_mod

    admin_instance.get_object = mocker.Mock(return_value=None)
    msg_error = mocker.patch.object(mod.messages, "error")
    redirect = mocker.patch.object(mod, "redirect", return_value=mocker.Mock())

    resp = admin_instance.deduplicate.func(admin_instance, mock_request, pk="999")

    msg_error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert resp is redirect.return_value


@pytest.mark.django_db
def test_country_rdp_admin_push_when_not_found_redirects(mocker: MockerFixture, admin_instance, mock_request):
    mod = rdp_admin_mod

    admin_instance.get_object = mocker.Mock(return_value=None)
    msg_error = mocker.patch.object(mod.messages, "error")
    redirect = mocker.patch.object(mod, "redirect", return_value=mocker.Mock())

    resp = admin_instance.push.func(admin_instance, mock_request, pk="999")

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
