from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState, FindingStatusCode
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Individual, Rdp, RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication import processing
from country_workspace.rdp.deduplication.biometric import workflow


pytestmark = pytest.mark.django_db


def test_build_biometric_findings(people_rdp: tuple[Rdp, list[Individual]]) -> None:
    from testutils.factories import BiometricRdpOperationFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    findings = [
        {
            "first": {"reference_pk": str(individuals[0].pk)},
            "second": {"reference_pk": str(individuals[1].pk)},
            "status_code": FindingStatusCode.DUPLICATE,
            "score": 0.9,
            "updated_at": "",
        },
        {
            "first": {"reference_pk": str(individuals[2].pk)},
            "second": {"reference_pk": ""},
            "status_code": FindingStatusCode.BAD_IMAGE_QUALITY,
            "updated_at": "",
        },
    ]

    result = workflow._build_biometric_findings(operation, findings)

    assert [(finding.finding_type, finding.individual_id) for finding in result] == [
        (FindingStatusCode.DUPLICATE.name, individuals[0].pk),
        (FindingStatusCode.BAD_IMAGE_QUALITY.name, individuals[2].pk),
    ]
    assert result[0].related_individual_id == individuals[1].pk
    assert result[0].details == {"related_reference_pk": individuals[1].pk, "score": 0.9}
    assert result[1].related_individual_id is None


def test_build_biometric_findings_allows_related_individual_from_same_program(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, IndividualFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    related = IndividualFactory(household=None, batch__program=rdp.program)

    result = workflow._build_biometric_findings(
        operation,
        [
            {
                "first": {"reference_pk": str(individuals[0].pk)},
                "second": {"reference_pk": str(related.pk)},
                "status_code": FindingStatusCode.DUPLICATE,
                "updated_at": "",
            }
        ],
    )

    assert result[0].related_individual_id == related.pk


def test_build_biometric_findings_rejects_individual_outside_rdp(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, IndividualFactory

    rdp, _ = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    outside = IndividualFactory(household=None, batch__program=rdp.program)

    with pytest.raises(RemoteError, match="not part of the current RDP"):
        workflow._build_biometric_findings(
            operation,
            [
                {
                    "first": {"reference_pk": str(outside.pk)},
                    "second": {"reference_pk": ""},
                    "status_code": FindingStatusCode.BAD_IMAGE_QUALITY,
                    "updated_at": "",
                }
            ],
        )


@pytest.mark.parametrize("exists", [True, False], ids=["other-program", "missing"])
def test_build_biometric_findings_preserves_unlinked_related_reference(
    people_rdp: tuple[Rdp, list[Individual]], exists: bool
) -> None:
    from testutils.factories import BiometricRdpOperationFactory, IndividualFactory, ProgramFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    related = IndividualFactory(household=None, batch__program=ProgramFactory())
    related_id = related.pk
    if not exists:
        related.delete()

    result = workflow._build_biometric_findings(
        operation,
        [
            {
                "first": {"reference_pk": str(individuals[0].pk)},
                "second": {"reference_pk": str(related_id)},
                "status_code": FindingStatusCode.DUPLICATE,
                "updated_at": "",
            }
        ],
    )

    assert result[0].related_individual_id is None
    assert result[0].details == {"related_reference_pk": related_id}


@pytest.mark.parametrize(
    ("expected", "count", "valid"),
    [
        (2, 2, True),
        (1, 2, False),
        ("2", 2, False),
        (-1, 2, False),
    ],
)
def test_validate_findings_count(expected: object, count: int, valid: bool) -> None:
    findings = [{}] * count

    if valid:
        workflow._validate_findings_count(expected=expected, findings=findings)
    else:
        with pytest.raises(RemoteError, match="findings_count"):
            workflow._validate_findings_count(expected=expected, findings=findings)


@pytest.mark.parametrize(
    ("operation_type", "status"),
    [
        (RdpOperation.Type.BIOMETRIC_DEDUPLICATION, RdpOperation.Status.PENDING),
        (RdpOperation.Type.OCR, RdpOperation.Status.RUNNING),
    ],
)
def test_sync_ignores_ineligible_operation(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    operation_type: RdpOperation.Type,
    status: RdpOperation.Status,
) -> None:
    biometric_operation.operation_type = operation_type
    biometric_operation.status = status
    make_client = mocker.patch.object(workflow, "make_operation_client")

    assert workflow.sync_biometric_result(biometric_operation) is False
    make_client.assert_not_called()


@pytest.mark.parametrize(
    "state",
    [DeduplicationSetState.ENCODING_FAILED, DeduplicationSetState.DEDUPLICATION_FAILED],
)
def test_sync_fails_operation_for_failed_remote_state(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState,
) -> None:
    make_client = mocker.patch.object(workflow, "make_operation_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {"state": state, "findings_count": 0}
    fail = mocker.patch.object(processing, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_result(running_biometric_operation) is True

    fail.assert_called_once()
    assert fail.call_args.kwargs["error"]["state"] == state.value


def test_sync_ignores_unfinished_remote_state(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    make_client = mocker.patch.object(workflow, "make_operation_client")
    make_client.return_value.__enter__.return_value.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.ENCODING_IN_PROGRESS,
        "findings_count": 0,
    }

    assert workflow.sync_biometric_result(running_biometric_operation) is False


@pytest.mark.parametrize(
    "status",
    [None, FindingStatusCode.FILE_NOT_FOUND],
    ids=["no_findings", "file_not_found"],
)
def test_sync_completes_operation(
    running_biometric_operation: RdpOperation,
    people_rdp,
    mocker: MockerFixture,
    status: FindingStatusCode | None,
) -> None:
    _, individuals = people_rdp
    findings = (
        []
        if status is None
        else [
            {
                "first": {"reference_pk": str(individuals[0].pk)},
                "second": {"reference_pk": ""},
                "status_code": status,
                "updated_at": "",
            }
        ]
    )
    make_client = mocker.patch.object(workflow, "make_operation_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.DEDUPLICATED,
        "findings_count": len(findings),
    }
    client.retrieve_findings.return_value = findings
    complete = mocker.patch.object(processing, "complete_rdp_operation", return_value=True)

    assert workflow.sync_biometric_result(running_biometric_operation) is True

    complete.assert_called_once()
    result = complete.call_args.kwargs["findings"]
    assert [(finding.finding_type, finding.individual_id) for finding in result] == (
        [] if status is None else [(status.name, individuals[0].pk)]
    )


def test_sync_fails_operation_for_system_error(
    running_biometric_operation: RdpOperation,
    people_rdp,
    mocker: MockerFixture,
) -> None:
    _, individuals = people_rdp
    make_client = mocker.patch.object(workflow, "make_operation_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.DEDUPLICATED,
        "findings_count": 1,
    }
    client.retrieve_findings.return_value = [
        {
            "first": {"reference_pk": str(individuals[0].pk)},
            "second": {"reference_pk": ""},
            "status_code": FindingStatusCode.GENERIC_ERROR,
            "updated_at": "",
        }
    ]
    fail = mocker.patch.object(processing, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_result(running_biometric_operation) is True

    error = fail.call_args.kwargs["error"]
    assert error["count"] == 1
    assert error["findings"][0]["status"] == FindingStatusCode.GENERIC_ERROR.name
    assert error["findings"][0]["reference_pk"] == str(individuals[0].pk)


def test_sync_fails_operation_for_findings_count_mismatch(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    make_client = mocker.patch.object(workflow, "make_operation_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.DEDUPLICATED,
        "findings_count": 1,
    }
    client.retrieve_findings.return_value = []
    fail = mocker.patch.object(processing, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_result(running_biometric_operation) is True
    assert "findings_count" in fail.call_args.kwargs["error"]["message"]


@pytest.mark.parametrize(
    "error",
    [RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["remote_error", "unavailable"],
)
def test_sync_fails_operation_on_remote_error(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
    error: Exception,
) -> None:
    make_client = mocker.patch.object(workflow, "make_operation_client")
    make_client.return_value.__enter__.return_value.retrieve_deduplication_set.side_effect = error
    fail = mocker.patch.object(processing, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_result(running_biometric_operation) is True
    assert str(error) in fail.call_args.kwargs["error"]["message"]


def test_get_or_create_biometric_set_state_reuses_existing_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = {"state": DeduplicationSetState.READY}
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")

    assert (
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)
        == DeduplicationSetState.READY
    )

    processor.assert_not_called()
    client.can_create_deduplication_set.assert_not_called()
    client.create_deduplication_set.assert_not_called()


def test_get_or_create_biometric_set_state_rejects_empty_images(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = None
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.has_images.return_value = False

    with pytest.raises(RdpWorkflowError, match="no biometric images"):
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)

    client.can_create_deduplication_set.assert_not_called()
    client.create_deduplication_set.assert_not_called()
    processor.return_value.has_images.assert_called_once_with()


def test_get_or_create_biometric_set_state_rejects_active_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = None
    client.can_create_deduplication_set.return_value = False
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.has_images.return_value = True

    with pytest.raises(RemoteError, match="another deduplication set"):
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)

    client.create_deduplication_set.assert_not_called()


def test_get_or_create_biometric_set_state_creates_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = None
    client.can_create_deduplication_set.return_value = True
    client.create_deduplication_set.return_value = {
        "id": str(biometric_operation.id),
        "state": DeduplicationSetState.EMPTY,
    }
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.has_images.return_value = True
    callback_url = mocker.patch.object(
        processing,
        "build_dedup_operation_callback_url",
        return_value="https://example.org/callback",
    )

    assert (
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)
        == DeduplicationSetState.EMPTY
    )

    callback_url.assert_called_once_with(operation_id=biometric_operation.id)
    client.create_deduplication_set.assert_called_once_with(
        notification_url="https://example.org/callback",
    )


def test_get_or_create_biometric_set_state_rejects_id_mismatch(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = None
    client.can_create_deduplication_set.return_value = True
    client.create_deduplication_set.return_value = {
        "id": str(uuid4()),
        "state": DeduplicationSetState.EMPTY,
    }
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.has_images.return_value = True
    mocker.patch.object(processing, "build_dedup_operation_callback_url", return_value="https://example.org/callback")

    with pytest.raises(RemoteError, match="id mismatch"):
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)


def test_prepare_biometric_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    mocker.patch.object(
        workflow,
        "_get_or_create_biometric_set_state",
        return_value=DeduplicationSetState.EMPTY,
    )
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.upload_images.return_value = 2

    assert workflow._prepare_biometric_set(client=client, operation=biometric_operation) == DeduplicationSetState.READY

    processor.return_value.upload_images.assert_called_once_with(client)
    client.ready.assert_called_once_with()


def test_prepare_biometric_set_returns_existing_state(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    mocker.patch.object(
        workflow,
        "_get_or_create_biometric_set_state",
        return_value=DeduplicationSetState.ENCODED,
    )
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")

    assert (
        workflow._prepare_biometric_set(client=client, operation=biometric_operation) == DeduplicationSetState.ENCODED
    )

    processor.assert_not_called()
    client.ready.assert_not_called()


def test_prepare_biometric_set_rejects_empty_images(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    client = mocker.MagicMock()
    mocker.patch.object(
        workflow,
        "_get_or_create_biometric_set_state",
        return_value=DeduplicationSetState.EMPTY,
    )
    processor = mocker.patch.object(workflow, "BiometricDedupProcessor")
    processor.return_value.upload_images.return_value = 0

    with pytest.raises(RdpWorkflowError, match="no biometric images"):
        workflow._prepare_biometric_set(client=client, operation=biometric_operation)

    client.ready.assert_not_called()


@pytest.mark.parametrize(
    ("state", "sync_called", "process_called"),
    [
        (DeduplicationSetState.DEDUPLICATED, True, False),
        (DeduplicationSetState.ENCODING_IN_PROGRESS, False, False),
        (DeduplicationSetState.DEDUPLICATION_IN_PROGRESS, False, False),
        (DeduplicationSetState.READY, False, True),
    ],
)
def test_run_biometric_deduplication(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState,
    sync_called: bool,
    process_called: bool,
) -> None:
    make_client = mocker.patch.object(workflow, "make_operation_client")
    client = make_client.return_value.__enter__.return_value
    mocker.patch.object(workflow, "_prepare_biometric_set", return_value=state)
    sync = mocker.patch.object(workflow, "sync_biometric_result")

    workflow.run_biometric_deduplication(biometric_operation)

    assert sync.called is sync_called
    assert client.process.called is process_called


def test_run_biometric_deduplication_rejects_invalid_state(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "make_operation_client")
    mocker.patch.object(
        workflow,
        "_prepare_biometric_set",
        return_value=DeduplicationSetState.APPROVED,
    )

    with pytest.raises(RdpWorkflowError, match="can not process"):
        workflow.run_biometric_deduplication(biometric_operation)


@pytest.mark.parametrize(
    "finding",
    [
        {},
        {"status_code": 999},
        {"status_code": FindingStatusCode.BAD_IMAGE_QUALITY, "first": {}},
        {
            "status_code": FindingStatusCode.BAD_IMAGE_QUALITY,
            "first": {"reference_pk": 123},
        },
        {
            "status_code": FindingStatusCode.BAD_IMAGE_QUALITY,
            "first": {"reference_pk": "invalid"},
        },
    ],
)
def test_build_biometric_findings_rejects_malformed_finding(
    biometric_operation: RdpOperation,
    finding: dict,
) -> None:
    with pytest.raises(RemoteError):
        workflow._build_biometric_findings(biometric_operation, [finding])


@pytest.mark.parametrize(
    "payload",
    [{}, {"state": "unknown"}, {"state": None}],
)
def test_get_or_create_biometric_set_state_rejects_malformed_existing_set(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    payload: dict,
) -> None:
    client = mocker.MagicMock()
    client.retrieve_deduplication_set_or_none.return_value = payload

    with pytest.raises(RemoteError, match="malformed deduplication set"):
        workflow._get_or_create_biometric_set_state(client=client, operation=biometric_operation)
