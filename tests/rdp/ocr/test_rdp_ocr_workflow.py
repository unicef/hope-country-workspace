from uuid import UUID

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.hope.constants import DOCUMENT_TYPES
from country_workspace.models import RdpOperation
from country_workspace.rdp.exceptions import RdpWorkflowError
from country_workspace.rdp.ocr import workflow


pytestmark = pytest.mark.django_db


def test_ocr_correlation_id_is_attempt_specific(running_ocr_operation: RdpOperation) -> None:
    first = workflow._ocr_correlation_id(running_ocr_operation)
    assert workflow._ocr_correlation_id(running_ocr_operation) == first

    running_ocr_operation.attempt += 1

    assert workflow._ocr_correlation_id(running_ocr_operation) != first


@pytest.mark.parametrize("has_units", [True, False])
def test_prepare_ocr_units(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
    has_units: bool,
) -> None:
    has = mocker.patch.object(workflow, "has_rdp_operation_units", return_value=has_units)
    prepare = mocker.patch.object(workflow, "prepare_rdp_operation_units_for_retry", return_value=True)
    create = mocker.patch.object(workflow, "create_ocr_units", return_value=True)
    individuals = mocker.patch.object(workflow, "qs_individuals_for_rdp")
    iterator = individuals.return_value.only.return_value.iterator
    iterator.return_value = ["individual"]
    configs = mocker.patch.object(
        workflow,
        "iter_ocr_unit_configs",
        return_value=[(1, {"document_type": DOCUMENT_TYPES[0]})],
    )

    assert workflow._prepare_ocr_units(running_ocr_operation) is True
    has.assert_called_once_with(operation_id=running_ocr_operation.id)

    if has_units:
        prepare.assert_called_once_with(
            operation_id=running_ocr_operation.id,
            expected_attempt=running_ocr_operation.attempt,
        )
        create.assert_not_called()
        individuals.assert_not_called()
    else:
        prepare.assert_not_called()
        configs.assert_called_once_with(["individual"])
        create.assert_called_once_with(
            operation=running_ocr_operation,
            unit_configs=[(1, {"document_type": DOCUMENT_TYPES[0]})],
        )


def test_prepare_ocr_batch_marks_unavailable_units_failed(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    available = mocker.MagicMock(pk=1)
    unavailable = mocker.MagicMock(pk=2)
    document = {"individual_id": 1, "content": "IMAGE", "pattern": "ID-1"}
    build = mocker.patch.object(workflow, "build_ocr_document_request", side_effect=[document, None])
    fail = mocker.patch.object(workflow, "fail_rdp_operation_units")

    assert workflow._prepare_ocr_batch(running_ocr_operation, [available, unavailable]) == [document]

    assert build.call_count == 2
    fail.assert_called_once_with(
        operation_id=running_ocr_operation.id,
        expected_attempt=running_ocr_operation.attempt,
        unit_ids=[2],
        error={"message": "OCR document is no longer available."},
    )


def test_run_ocr_zero_eligible_documents(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "_prepare_ocr_units", return_value=True)
    mocker.patch.object(workflow, "has_rdp_operation_units", return_value=False)
    complete = mocker.patch.object(workflow, "complete_rdp_operation")
    publish = mocker.patch.object(workflow, "publish")

    workflow.run_ocr(running_ocr_operation)

    complete.assert_called_once_with(operation=running_ocr_operation)
    publish.assert_not_called()


def test_run_ocr_without_pending_units(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "_prepare_ocr_units", return_value=True)
    mocker.patch.object(workflow, "has_rdp_operation_units", return_value=True)
    units = mocker.patch.object(workflow, "pending_rdp_operation_units")
    units.return_value.count.return_value = 0
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    workflow.run_ocr(running_ocr_operation)

    finalize.assert_called_once_with(operation=running_ocr_operation)


def test_run_ocr_batches_and_publishes(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    units = [mocker.MagicMock(pk=index) for index in range(1, 4)]
    queryset = mocker.patch.object(workflow, "pending_rdp_operation_units").return_value
    queryset.count.return_value = len(units)
    queryset.iterator.return_value = iter(units)

    mocker.patch.object(workflow, "_prepare_ocr_units", return_value=True)
    mocker.patch.object(workflow, "has_rdp_operation_units", return_value=True)
    mocker.patch.object(workflow, "OCR_BATCH_SIZE", 2)
    mocker.patch.object(
        workflow,
        "_prepare_ocr_batch",
        side_effect=[
            [
                {"individual_id": 1, "content": "A", "pattern": "P1"},
                {"individual_id": 2, "content": "B", "pattern": "P2"},
            ],
            [{"individual_id": 3, "content": "C", "pattern": "P3"}],
        ],
    )
    mocker.patch.object(workflow, "lock_current_rdp_operation", return_value=running_ocr_operation)
    publish = mocker.patch.object(workflow, "publish", return_value=True)
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    workflow.run_ocr(running_ocr_operation)

    assert publish.call_count == 2
    first, second = [call.args for call in publish.call_args_list]
    assert first[0] == workflow.OCR_REQUEST_ROUTING_KEY
    assert second[0] == workflow.OCR_REQUEST_ROUTING_KEY
    assert (
        first[1]["correlation_id"]
        == second[1]["correlation_id"]
        == str(workflow._ocr_correlation_id(running_ocr_operation))
    )
    assert first[1]["rdp_id"] == running_ocr_operation.rdp_id
    assert (first[1]["batch_index"], first[1]["batch_total"]) == (1, 2)
    assert (second[1]["batch_index"], second[1]["batch_total"]) == (2, 2)
    assert first[1]["documents"] == [
        {"individual_id": 1, "content": "A", "pattern": "P1"},
        {"individual_id": 2, "content": "B", "pattern": "P2"},
    ]
    assert second[1]["documents"] == [{"individual_id": 3, "content": "C", "pattern": "P3"}]
    assert all(UUID(call.args[1]["batch_id"]) for call in publish.call_args_list)
    finalize.assert_called_once_with(operation=running_ocr_operation)


def test_run_ocr_continues_after_publish_failure(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    units = [mocker.MagicMock(pk=1), mocker.MagicMock(pk=2)]
    queryset = mocker.patch.object(workflow, "pending_rdp_operation_units").return_value
    queryset.count.return_value = 2
    queryset.iterator.return_value = iter(units)

    mocker.patch.object(workflow, "_prepare_ocr_units", return_value=True)
    mocker.patch.object(workflow, "has_rdp_operation_units", return_value=True)
    mocker.patch.object(workflow, "OCR_BATCH_SIZE", 1)
    mocker.patch.object(
        workflow,
        "_prepare_ocr_batch",
        side_effect=[
            [{"individual_id": 1, "content": "A", "pattern": "P1"}],
            [{"individual_id": 2, "content": "B", "pattern": "P2"}],
        ],
    )
    mocker.patch.object(workflow, "lock_current_rdp_operation", return_value=running_ocr_operation)
    publish = mocker.patch.object(workflow, "publish", side_effect=[False, True])
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    with pytest.raises(RdpWorkflowError, match="publish"):
        workflow.run_ocr(running_ocr_operation)

    assert publish.call_count == 2
    finalize.assert_not_called()


def test_run_ocr_stops_when_attempt_is_no_longer_current(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    unit = mocker.MagicMock(pk=1)
    queryset = mocker.patch.object(workflow, "pending_rdp_operation_units").return_value
    queryset.count.return_value = 1
    queryset.iterator.return_value = iter([unit])

    mocker.patch.object(workflow, "_prepare_ocr_units", return_value=True)
    mocker.patch.object(workflow, "has_rdp_operation_units", return_value=True)
    mocker.patch.object(
        workflow,
        "_prepare_ocr_batch",
        return_value=[{"individual_id": 1, "content": "A", "pattern": "P1"}],
    )
    mocker.patch.object(workflow, "lock_current_rdp_operation", return_value=None)
    publish = mocker.patch.object(workflow, "publish")
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    workflow.run_ocr(running_ocr_operation)

    publish.assert_not_called()
    finalize.assert_not_called()


def _result_payload(operation: RdpOperation, *, correlation_id: str | None = None) -> dict[str, object]:
    return {
        "correlation_id": correlation_id or str(workflow._ocr_correlation_id(operation)),
        "rdp_id": operation.rdp_id,
        "batch_id": "batch",
        "batch_index": 1,
        "batch_total": 1,
        "documents": [
            {
                "individual_id": 1,
                "status": "ok",
                "found": False,
                "match": None,
                "error": None,
            }
        ],
    }


def test_handle_ocr_result(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    payload = _result_payload(running_ocr_operation)
    mocker.patch.object(workflow, "validate_ocr_result", return_value=payload)
    mocker.patch.object(workflow, "lock_ocr_operation_for_update", return_value=running_ocr_operation)
    apply = mocker.patch.object(workflow, "apply_ocr_document_results")
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    workflow.handle_ocr_result(payload)

    apply.assert_called_once_with(operation=running_ocr_operation, documents=payload["documents"])
    finalize.assert_called_once_with(operation=running_ocr_operation)


@pytest.mark.parametrize("case", ["missing_operation", "not_running", "stale_attempt"])
def test_handle_ocr_result_ignores_stale_result(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
    case: str,
) -> None:
    payload = _result_payload(running_ocr_operation)
    if case == "stale_attempt":
        payload["correlation_id"] = "stale"

    mocker.patch.object(workflow, "validate_ocr_result", return_value=payload)
    if case == "missing_operation":
        operation = None
    else:
        operation = running_ocr_operation
        if case == "not_running":
            operation.status = RdpOperation.Status.SUCCESS

    mocker.patch.object(workflow, "lock_ocr_operation_for_update", return_value=operation)
    apply = mocker.patch.object(workflow, "apply_ocr_document_results")
    finalize = mocker.patch.object(workflow, "finalize_rdp_operation_from_units")

    workflow.handle_ocr_result(payload)

    apply.assert_not_called()
    finalize.assert_not_called()


def test_handle_ocr_result_records_processing_error(
    running_ocr_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    payload = _result_payload(running_ocr_operation)
    mocker.patch.object(workflow, "validate_ocr_result", return_value=payload)
    mocker.patch.object(workflow, "lock_ocr_operation_for_update", return_value=running_ocr_operation)
    error = ValueError("failed")
    mocker.patch.object(workflow, "apply_ocr_document_results", side_effect=error)
    handle_error = mocker.patch.object(workflow, "handle_rdp_operation_error")

    with pytest.raises(ValueError, match="failed"):
        workflow.handle_ocr_result(payload)

    handle_error.assert_called_once_with(operation=running_ocr_operation, exc=error)
