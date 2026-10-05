from uuid import uuid4

import pytest
from constance.test import override_config
from pytest_mock import MockerFixture

from country_workspace.contrib.dedup_engine import DeduplicationSetState, FindingStatusCode
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Rdp, RdpOperation
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication import workflow


pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org", "https://example.org"),
        ("https://example.org/", "https://example.org"),
    ],
)
def test_get_dedup_callback_base_url(url: str, expected: str) -> None:
    with override_config(APP_BASE_URL=url):
        assert workflow.get_dedup_callback_base_url() == expected


@pytest.mark.parametrize("url", ["", "example.org", "ftp://example.org", "https://example.org/?a=1"])
def test_get_dedup_callback_base_url_rejects_invalid_url(url: str) -> None:
    with override_config(APP_BASE_URL=url):
        with pytest.raises(ValueError, match="valid absolute HTTP"):
            workflow.get_dedup_callback_base_url()


def test_build_biometric_findings(people_rdp) -> None:
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
    assert result[0].details == {"score": 0.9}
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


def test_build_biometric_findings_ignores_related_individual_from_other_program(people_rdp) -> None:
    from testutils.factories import BiometricRdpOperationFactory, IndividualFactory, ProgramFactory

    rdp, individuals = people_rdp
    operation = BiometricRdpOperationFactory(rdp=rdp)
    related = IndividualFactory(household=None, batch__program=ProgramFactory())

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

    assert result[0].related_individual_id is None


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


def test_sync_missing_operation(mocker: MockerFixture) -> None:
    mocker.patch.object(workflow, "get_rdp_operation", side_effect=RdpOperation.DoesNotExist)

    assert workflow.sync_biometric_deduplication_result(operation_id=uuid4()) is False


def test_sync_ignores_non_running_operation(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "get_rdp_operation", return_value=biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")

    assert workflow.sync_biometric_deduplication_result(operation_id=biometric_operation.id) is False
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
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {"state": state, "findings_count": 0}
    fail = mocker.patch.object(workflow, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is True

    fail.assert_called_once()
    assert fail.call_args.kwargs["error"]["state"] == state.value


def test_sync_ignores_unfinished_remote_state(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    make_client.return_value.__enter__.return_value.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.ENCODING_IN_PROGRESS,
        "findings_count": 0,
    }

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is False


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
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.DEDUPLICATED,
        "findings_count": len(findings),
    }
    client.retrieve_findings.return_value = findings
    complete = mocker.patch.object(workflow, "complete_rdp_operation", return_value=True)

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is True

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
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
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
    fail = mocker.patch.object(workflow, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is True

    error = fail.call_args.kwargs["error"]
    assert error["count"] == 1
    assert error["findings"][0]["status"] == FindingStatusCode.GENERIC_ERROR.name
    assert error["findings"][0]["reference_pk"] == str(individuals[0].pk)


def test_sync_fails_operation_for_findings_count_mismatch(
    running_biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    client.retrieve_deduplication_set.return_value = {
        "state": DeduplicationSetState.DEDUPLICATED,
        "findings_count": 1,
    }
    client.retrieve_findings.return_value = []
    fail = mocker.patch.object(workflow, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is True
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
    mocker.patch.object(workflow, "get_rdp_operation", return_value=running_biometric_operation)
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    make_client.return_value.__enter__.return_value.retrieve_deduplication_set.side_effect = error
    fail = mocker.patch.object(workflow, "fail_rdp_operation", return_value=True)

    assert workflow.sync_biometric_deduplication_result(operation_id=running_biometric_operation.id) is True
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
        workflow,
        "_build_dedup_operation_callback_url",
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
    mocker.patch.object(workflow, "_build_dedup_operation_callback_url", return_value="https://example.org/callback")

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
    make_client = mocker.patch.object(workflow, "make_dedup_client")
    client = make_client.return_value.__enter__.return_value
    mocker.patch.object(workflow, "_prepare_biometric_set", return_value=state)
    sync = mocker.patch.object(workflow, "sync_biometric_deduplication_result")

    workflow.run_biometric_deduplication(biometric_operation)

    assert sync.called is sync_called
    assert client.process.called is process_called


def test_run_biometric_deduplication_rejects_invalid_state(
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    mocker.patch.object(workflow, "make_dedup_client")
    mocker.patch.object(
        workflow,
        "_prepare_biometric_set",
        return_value=DeduplicationSetState.APPROVED,
    )

    with pytest.raises(RdpWorkflowError, match="can not process"):
        workflow.run_biometric_deduplication(biometric_operation)


def test_reject_cancelled_rdp_set(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(
        workflow,
        "retrieve_deduplication_set_state",
        return_value=DeduplicationSetState.DEDUPLICATED,
    )
    reject = mocker.patch.object(workflow, "reject_deduplication_set")

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    reject.assert_called_once_with(
        operation_id=biometric_operation.id,
        group_reference_id=rdp.program.unicef_id,
    )


def test_reject_cancelled_rdp_set_rejects_stale_job(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)

    with pytest.raises(RdpWorkflowError, match="no longer current"):
        workflow.reject_cancelled_rdp_set_core(job)


@pytest.mark.parametrize(
    "state",
    [None, DeduplicationSetState.REJECTED],
    ids=["missing", "already_rejected"],
)
def test_reject_cancelled_rdp_set_skips_completed_cleanup(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    state: DeduplicationSetState | None,
) -> None:
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(workflow, "retrieve_deduplication_set_state", return_value=state)
    reject = mocker.patch.object(workflow, "reject_deduplication_set")

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}
    reject.assert_not_called()


def test_reject_cancelled_rdp_set_rejects_non_rejectable_state(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(
        workflow,
        "retrieve_deduplication_set_state",
        return_value=DeduplicationSetState.ENCODING_IN_PROGRESS,
    )

    with pytest.raises(RdpWorkflowError, match="can not reject"):
        workflow.reject_cancelled_rdp_set_core(job)


@pytest.mark.parametrize(
    "error",
    [RemoteError("remote"), RemoteUnavailableError("unavailable")],
    ids=["remote_error", "unavailable"],
)
def test_reject_cancelled_rdp_set_wraps_remote_error(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
    error: Exception,
) -> None:
    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(workflow, "retrieve_deduplication_set_state", side_effect=error)

    with pytest.raises(RdpWorkflowError, match=str(error)):
        workflow.reject_cancelled_rdp_set_core(job)


def test_reject_cancelled_rdp_set_schedules_clean_rdp(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import RdpFactory

    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    clean_rdp = RdpFactory(program=rdp.program)
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
            "clean_rdp_id": clean_rdp.pk,
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(workflow, "retrieve_deduplication_set_state", return_value=None)
    schedule = mocker.patch.object(workflow, "schedule_rdp_operations")

    assert workflow.reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}
    schedule.assert_called_once_with(rdp=clean_rdp)


def test_reject_cancelled_rdp_set_rejects_non_pending_clean_rdp(
    rdp: Rdp,
    biometric_operation: RdpOperation,
    mocker: MockerFixture,
) -> None:
    from testutils.factories import RdpFactory

    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    clean_rdp = RdpFactory(program=rdp.program, status=Rdp.PushStatus.CANCELLED)
    job = mocker.MagicMock(
        config={
            "rdp_id": rdp.pk,
            "deduplication_set_id": str(biometric_operation.id),
            "clean_rdp_id": clean_rdp.pk,
        }
    )
    mocker.patch.object(workflow, "rdp_for_dedup", return_value=rdp)
    mocker.patch.object(workflow, "biometric_operation_for_rdp", return_value=biometric_operation)
    mocker.patch.object(workflow, "retrieve_deduplication_set_state", return_value=None)

    with pytest.raises(RdpWorkflowError, match="clean replacement"):
        workflow.reject_cancelled_rdp_set_core(job)


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


def test_schedule_cancelled_rdp_set_rejection(
    rdp: Rdp,
    user,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    on_commit = mocker.patch.object(workflow.transaction, "on_commit")

    assert (
        workflow.schedule_cancelled_rdp_set_rejection(
            rdp=rdp,
            user_id=user.pk,
            deduplication_set_id="SET",
            clean_rdp_id=123,
        )
        is job
    )

    assert create.call_args.kwargs["config"] == {
        "rdp_id": rdp.pk,
        "deduplication_set_id": "SET",
        "clean_rdp_id": 123,
    }
    on_commit.assert_called_once_with(job.queue, robust=True)


def test_schedule_cancelled_rdp_set_rejection_without_clean_rdp(
    rdp: Rdp,
    user,
    mocker: MockerFixture,
) -> None:
    job = mocker.MagicMock()
    create = mocker.patch.object(workflow.AsyncJob.objects, "create", return_value=job)
    mocker.patch.object(workflow.transaction, "on_commit")

    workflow.schedule_cancelled_rdp_set_rejection(
        rdp=rdp,
        user_id=user.pk,
        deduplication_set_id="SET",
    )

    assert create.call_args.kwargs["config"] == {
        "rdp_id": rdp.pk,
        "deduplication_set_id": "SET",
    }


def test_build_dedup_operation_callback_url(mocker: MockerFixture) -> None:
    operation_id = uuid4()
    mocker.patch.object(workflow, "get_dedup_callback_base_url", return_value="https://example.org")
    dumps = mocker.patch.object(workflow.signing, "dumps", return_value="TOKEN")
    reverse = mocker.patch.object(workflow, "reverse", return_value="/callback/TOKEN/")

    assert workflow._build_dedup_operation_callback_url(operation_id=operation_id) == (
        "https://example.org/callback/TOKEN/"
    )

    dumps.assert_called_once_with(
        {"operation_id": str(operation_id)},
        salt=workflow.DEDUP_CALLBACK_SALT,
    )
    reverse.assert_called_once_with(
        "api:callbacks:dedup-engine-rdp-state-changed",
        kwargs={"signed_token": "TOKEN"},
    )
