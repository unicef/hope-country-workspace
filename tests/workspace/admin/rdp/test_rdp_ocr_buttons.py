import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.push.policy import ActionCheck
from country_workspace.models import OcrRun
from country_workspace.workspaces.admin import rdp as rdp_admin_mod
from country_workspace.workspaces.models import CountryRdp

pytestmark = pytest.mark.django_db


def test_run_ocr_redirects_when_rdp_not_found(admin_instance, mock_request, mocker: MockerFixture) -> None:
    admin_instance.get_object = mocker.Mock(return_value=None)
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.run_ocr.func(admin_instance, mock_request, pk="999")

    error.assert_called_once_with(mock_request, "RDP not found")
    redirect.assert_called_once_with("workspace:workspaces_countryrdp_changelist")
    assert response == "response"


def test_run_ocr_schedules_job(admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    job = mocker.MagicMock()
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create", return_value=job)
    claim = mocker.patch.object(rdp_admin_mod, "claim_rdp_ocr", return_value=(ActionCheck(True), rdp))
    on_commit = mocker.patch.object(rdp_admin_mod.transaction, "on_commit")
    success = mocker.patch.object(rdp_admin_mod.messages, "success")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.run_ocr.func(admin_instance, mock_request, pk=str(rdp.pk))

    claim.assert_called_once_with(rdp_id=rdp.pk)
    create.assert_called_once_with(
        description="Run OCR on RDP identity documents",
        type=rdp_admin_mod.AsyncJob.JobType.TASK,
        owner=mock_request.user,
        action=rdp_admin_mod.fqn(rdp_admin_mod.run_ocr_core),
        program=rdp.program,
        rdp=rdp,
        config={"rdp_id": rdp.pk},
    )
    on_commit.assert_called_once_with(job.queue)
    success.assert_called_once_with(mock_request, "OCR task scheduled")
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_run_ocr_denies_when_claim_fails(admin_instance, mock_request, rdp: CountryRdp, mocker: MockerFixture) -> None:
    admin_instance.get_object = mocker.Mock(return_value=rdp)
    admin_instance._change_url = mocker.Mock(return_value="/change")
    mocker.patch.object(rdp_admin_mod, "claim_rdp_ocr", return_value=(ActionCheck(False, "blocked"), None))
    create = mocker.patch.object(rdp_admin_mod.AsyncJob.objects, "create")
    error = mocker.patch.object(rdp_admin_mod.messages, "error")
    redirect = mocker.patch.object(rdp_admin_mod, "redirect", return_value="response")

    response = admin_instance.run_ocr.func(admin_instance, mock_request, pk=str(rdp.pk))

    error.assert_called_once_with(mock_request, "blocked")
    create.assert_not_called()
    redirect.assert_called_once_with("/change")
    assert response == "response"


def test_run_ocr_button_visible_and_enabled_wiring(rdp: CountryRdp, mocker: MockerFixture) -> None:
    policy = mocker.MagicMock()
    policy.is_ocr_visible.return_value = True
    policy.ocr_check.return_value = ActionCheck(True)
    mocker.patch.object(rdp_admin_mod, "get_ocr_policy", return_value=policy)

    btn = rdp_admin_mod.CountryRdpAdmin.run_ocr.get_button({"original": rdp})

    assert btn.visible is True
    assert btn.enabled is True


def test_run_ocr_button_hidden_when_no_object(mocker: MockerFixture) -> None:
    btn = rdp_admin_mod.CountryRdpAdmin.run_ocr.get_button({"original": None})
    assert btn.visible is False


def test_ocr_run_display_no_run(admin_instance, rdp: CountryRdp) -> None:
    assert admin_instance.ocr_run_display(rdp) == "-"


def test_ocr_run_display_shows_progress_and_results(admin_instance, rdp: CountryRdp) -> None:
    run = OcrRun.objects.create(rdp=rdp, batch_total=2, received_batch_ids=["b1"], results={"b1": [{"ok": True}]})

    result = str(admin_instance.ocr_run_display(rdp))

    assert run.get_status_display() in result
    assert "1/2" in result
    assert str(run.correlation_id) in result
    assert "ok" in result


def test_get_fields_includes_ocr_run_display_when_present(admin_instance, mock_request, rdp: CountryRdp) -> None:
    OcrRun.objects.create(rdp=rdp)

    fields = admin_instance.get_fields(mock_request, rdp)

    assert "ocr_run_display" in fields
