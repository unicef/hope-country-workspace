import pytest

from country_workspace.contrib.hope.ocr.repository import apply_ocr_batch_result, resolve_ocr_documents
from country_workspace.models import OcrRun
from country_workspace.storages import HOPE_STORAGE

pytestmark = pytest.mark.django_db


def test_resolve_ocr_documents_yields_first_complete_document_type(rdp, make_individual, complete_document_flex_fields):
    ind = make_individual(complete_document_flex_fields)

    documents = list(resolve_ocr_documents(rdp))

    assert len(documents) == 1
    doc = documents[0]
    assert doc["individual_id"] == ind.pk
    assert doc["pattern"] == "ID-123"
    assert doc["filename"] == ind.hope_blob_key("national_id_photo")
    assert HOPE_STORAGE.exists(doc["filename"])


def test_resolve_ocr_documents_prefers_first_document_type_in_order(
    rdp, make_individual, complete_document_flex_fields
):
    """When both national_id and national_passport are complete, only national_id (first) is used."""
    flex_fields = dict(complete_document_flex_fields)
    flex_fields["national_passport_document_number"] = "PP-999"
    flex_fields["national_passport_photo"] = complete_document_flex_fields["national_id_photo"]
    make_individual(flex_fields)

    documents = list(resolve_ocr_documents(rdp))

    assert len(documents) == 1
    assert documents[0]["pattern"] == "ID-123"


@pytest.mark.parametrize(
    "flex_fields",
    [
        {},
        {"national_id_document_number": "ID-123", "national_id_photo": ""},
        {"national_id_document_number": "", "national_id_photo": "data:image/png;base64,Zm9v"},
        {"national_id_document_number": "   ", "national_id_photo": "data:image/png;base64,Zm9v"},
    ],
    ids=["nothing", "photo_missing", "number_missing", "number_blank"],
)
def test_resolve_ocr_documents_skips_incomplete_pairs(rdp, make_individual, flex_fields):
    make_individual(flex_fields)

    assert list(resolve_ocr_documents(rdp)) == []


def test_resolve_ocr_documents_skips_individuals_not_on_rdp(rdp, batch, complete_document_flex_fields):
    from testutils.factories import IndividualFactory

    IndividualFactory(household=None, batch=batch, flex_fields=complete_document_flex_fields, rdps=None)

    assert list(resolve_ocr_documents(rdp)) == []


@pytest.fixture
def ocr_run(rdp):
    return OcrRun.objects.create(rdp=rdp, batch_total=2)


def test_apply_ocr_batch_result_ignores_unknown_correlation_id():
    apply_ocr_batch_result(
        correlation_id="00000000-0000-0000-0000-000000000000",
        batch_id="batch-1",
        batch_total=1,
        documents=[{"individual_id": 1, "status": "matched"}],
    )
    # no exception raised; nothing to assert on since there is no run to inspect


def test_apply_ocr_batch_result_merges_batch(ocr_run):
    apply_ocr_batch_result(
        correlation_id=str(ocr_run.correlation_id),
        batch_id="batch-1",
        batch_total=2,
        documents=[{"individual_id": 1, "status": "matched"}],
    )

    ocr_run.refresh_from_db()
    assert ocr_run.received_batch_ids == ["batch-1"]
    assert ocr_run.results == {"batch-1": [{"individual_id": 1, "status": "matched"}]}
    assert ocr_run.status == OcrRun.Status.PENDING


def test_apply_ocr_batch_result_is_idempotent_for_redelivery(ocr_run):
    apply_ocr_batch_result(
        correlation_id=str(ocr_run.correlation_id),
        batch_id="batch-1",
        batch_total=2,
        documents=[{"individual_id": 1, "status": "matched"}],
    )
    apply_ocr_batch_result(
        correlation_id=str(ocr_run.correlation_id),
        batch_id="batch-1",
        batch_total=2,
        documents=[{"individual_id": 999, "status": "different-payload"}],
    )

    ocr_run.refresh_from_db()
    assert ocr_run.received_batch_ids == ["batch-1"]
    assert ocr_run.results == {"batch-1": [{"individual_id": 1, "status": "matched"}]}


def test_apply_ocr_batch_result_completes_run_when_all_batches_received(ocr_run):
    apply_ocr_batch_result(
        correlation_id=str(ocr_run.correlation_id),
        batch_id="batch-1",
        batch_total=2,
        documents=[{"individual_id": 1, "status": "matched"}],
    )
    apply_ocr_batch_result(
        correlation_id=str(ocr_run.correlation_id),
        batch_id="batch-2",
        batch_total=2,
        documents=[{"individual_id": 2, "status": "matched"}],
    )

    ocr_run.refresh_from_db()
    assert ocr_run.status == OcrRun.Status.COMPLETED
    assert ocr_run.completed_at is not None
    assert set(ocr_run.received_batch_ids) == {"batch-1", "batch-2"}
