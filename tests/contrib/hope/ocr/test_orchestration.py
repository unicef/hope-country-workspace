import pytest

from country_workspace.contrib.hope import ocr as ocr_pkg
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.contrib.hope.ocr import orchestration
from country_workspace.models import OcrRun, Rdp
from country_workspace.models.rdp import RdpOperationAction
from country_workspace.stream.publish import OCR_REQUEST_ROUTING_KEY

pytestmark = pytest.mark.django_db


def test_claim_rdp_ocr_creates_run(rdp):
    check, locked = orchestration.claim_rdp_ocr(rdp.pk)

    assert check.allowed is True
    assert locked is not None
    assert OcrRun.objects.filter(rdp=rdp).exists()


def test_claim_rdp_ocr_blocked_when_rdp_not_open(rdp):
    rdp.status = Rdp.PushStatus.SUCCESS
    rdp.save(update_fields=["status"])

    check, locked = orchestration.claim_rdp_ocr(rdp.pk)

    assert check.allowed is False
    assert locked is None
    assert not OcrRun.objects.filter(rdp=rdp).exists()


def test_claim_rdp_ocr_blocked_when_run_already_exists(rdp):
    OcrRun.objects.create(rdp=rdp)

    check, locked = orchestration.claim_rdp_ocr(rdp.pk)

    assert check.allowed is False
    assert "already" in check.reason
    assert locked is None


@pytest.fixture
def job(rdp):
    from testutils.factories import AsyncJobFactory

    from country_workspace.models import AsyncJob

    return AsyncJobFactory(
        type=AsyncJob.JobType.TASK,
        program=rdp.program,
        rdp=rdp,
        config={"rdp_id": rdp.pk},
    )


def test_run_ocr_core_publishes_batches_and_marks_in_progress(
    rdp, make_individual, complete_document_flex_fields, job, mocker
):
    OcrRun.objects.create(rdp=rdp)
    ind1 = make_individual(complete_document_flex_fields)
    flex_fields2 = dict(complete_document_flex_fields)
    flex_fields2["national_id_document_number"] = "ID-456"
    ind2 = make_individual(flex_fields2)

    mocker.patch.object(orchestration, "OCR_BATCH_SIZE", 1)
    publish = mocker.patch.object(orchestration, "publish", return_value=True)

    result = orchestration.run_ocr_core(job)

    assert publish.call_count == 2
    routing_keys = {call.args[0] for call in publish.call_args_list}
    assert routing_keys == {OCR_REQUEST_ROUTING_KEY}

    payloads = [call.args[1] for call in publish.call_args_list]
    batch_indices = sorted(p["batch_index"] for p in payloads)
    assert batch_indices == [1, 2]
    for payload in payloads:
        assert payload["batch_total"] == 2
        assert payload["rdp_id"] == rdp.pk
        assert len(payload["documents"]) == 1

    individual_ids = {p["documents"][0]["individual_id"] for p in payloads}
    assert individual_ids == {ind1.pk, ind2.pk}

    ocr_run = rdp.ocr_run
    ocr_run.refresh_from_db()
    assert ocr_run.batch_total == 2
    assert ocr_run.status == OcrRun.Status.IN_PROGRESS

    rdp.refresh_from_db()
    assert rdp.operation_log[-1]["action"] == RdpOperationAction.START_OCR.value
    assert rdp.operation_log[-1]["result"]["batches_published"] == 2

    assert result["batch_total"] == 2
    assert result["batches_published"] == 2


def test_run_ocr_core_fails_when_no_documents(rdp, job):
    OcrRun.objects.create(rdp=rdp)

    with pytest.raises(RdpWorkflowError):
        orchestration.run_ocr_core(job)

    ocr_run = rdp.ocr_run
    ocr_run.refresh_from_db()
    assert ocr_run.status == OcrRun.Status.FAILED

    rdp.refresh_from_db()
    assert "no documents" in rdp.operation_log[-1]["result"]["error"]


def test_run_ocr_core_marks_failed_on_publish_failure(rdp, make_individual, complete_document_flex_fields, job, mocker):
    OcrRun.objects.create(rdp=rdp)
    make_individual(complete_document_flex_fields)

    mocker.patch.object(orchestration, "publish", return_value=False)

    with pytest.raises(RdpWorkflowError):
        orchestration.run_ocr_core(job)

    ocr_run = rdp.ocr_run
    ocr_run.refresh_from_db()
    assert ocr_run.status == OcrRun.Status.FAILED
    assert ocr_run.batch_total == 1  # persisted before publish, kept even on failure


def test_handle_ocr_result_ignores_incomplete_payload(mocker):
    apply = mocker.patch.object(orchestration, "apply_ocr_batch_result")

    orchestration.handle_ocr_result({"correlation_id": "abc"})
    orchestration.handle_ocr_result({"batch_id": "batch-1"})
    orchestration.handle_ocr_result({})

    apply.assert_not_called()


def test_handle_ocr_result_delegates_to_repository(mocker):
    apply = mocker.patch.object(orchestration, "apply_ocr_batch_result")

    orchestration.handle_ocr_result(
        {
            "correlation_id": "abc",
            "batch_id": "batch-1",
            "batch_total": 3,
            "documents": [{"individual_id": 1}],
        }
    )

    apply.assert_called_once_with(
        correlation_id="abc",
        batch_id="batch-1",
        batch_total=3,
        documents=[{"individual_id": 1}],
    )


def test_ocr_package_reexports_expected_symbols():
    assert ocr_pkg.claim_rdp_ocr is orchestration.claim_rdp_ocr
    assert ocr_pkg.run_ocr_core is orchestration.run_ocr_core
    assert ocr_pkg.handle_ocr_result is orchestration.handle_ocr_result
