import pytest
from pytest_mock import MockerFixture

from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import Individual, Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication import processing
from country_workspace.rdp.deduplication.biographic import workflow

pytestmark = pytest.mark.django_db

DATASET_ID = "00000000-0000-0000-0000-000000000042"


def _finding(individual_pk: int, matched_pk: int | str, scope: str = "batch", score: float = 0.95) -> dict:
    return {
        "reference_pk": str(individual_pk),
        "matched_reference_pk": str(matched_pk),
        "scope": scope,
        "score": score,
        "proximity_to_score": 0.1,
        "matched_full_name": "Other Person",
        "matched_birth_date": "2000-01-01",
    }


@pytest.fixture
def client(mocker: MockerFixture):
    context = mocker.patch.object(workflow, "make_operation_client")
    return context.return_value.__enter__.return_value


@pytest.fixture
def people_operation(people_rdp: tuple[Rdp, list[Individual]]) -> RdpOperation:
    from testutils.factories import BiographicRdpOperationFactory

    rdp, _ = people_rdp
    return BiographicRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.RUNNING)


@pytest.mark.parametrize("finding", [{"scope": "galaxy"}, {}])
def test_finding_scope_rejects_invalid(finding: dict) -> None:
    with pytest.raises(RemoteError, match="scope"):
        workflow._finding_scope(finding)  # type: ignore[arg-type]


def test_build_biographic_findings(
    people_operation: RdpOperation,
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    from testutils.factories import IndividualFactory

    rdp, individuals = people_rdp
    local_other = IndividualFactory(household=None, batch__program=rdp.program)
    foreign = IndividualFactory(household=None)

    built = workflow._build_biographic_findings(
        people_operation,
        [
            _finding(individuals[0].pk, individuals[1].pk, "batch"),
            _finding(individuals[0].pk, local_other.pk, "population"),
            _finding(individuals[2].pk, foreign.pk, "population"),
        ],
    )

    assert [f.individual_id for f in built] == [individuals[0].pk, individuals[0].pk, individuals[2].pk]
    assert [f.related_individual_id for f in built] == [individuals[1].pk, local_other.pk, None]
    assert {f.finding_type for f in built} == {"DUPLICATE"}
    assert built[1].details["scope"] == "population"
    assert built[0].details == {
        "scope": "batch",
        "related_reference_pk": individuals[1].pk,
        "score": 0.95,
        "proximity_to_score": 0.1,
        "matched_full_name": "Other Person",
        "matched_birth_date": "2000-01-01",
    }


def test_build_biographic_findings_rejects_foreign_individual(
    people_operation: RdpOperation,
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    from testutils.factories import IndividualFactory

    rdp, individuals = people_rdp
    outsider = IndividualFactory(household=None, batch__program=rdp.program)

    with pytest.raises(RemoteError, match="not part of the current RDP"):
        workflow._build_biographic_findings(people_operation, [_finding(outsider.pk, individuals[0].pk)])


def test_sync_ignores_other_operation_types(biometric_operation: RdpOperation, client) -> None:
    assert workflow.sync_biographic_result(biometric_operation) is False

    client.retrieve_dataset.assert_not_called()


def test_sync_ignores_operation_that_is_not_running(biographic_operation: RdpOperation, client) -> None:
    biographic_operation.status = RdpOperation.Status.SUCCESS

    assert workflow.sync_biographic_result(biographic_operation) is False
    client.retrieve_dataset.assert_not_called()


def test_sync_failed_state(running_biographic_operation: RdpOperation, client) -> None:
    client.retrieve_dataset.return_value = {"dataset_id": DATASET_ID, "status": "failed", "error": "boom"}

    assert workflow.sync_biographic_result(running_biographic_operation) is True

    running_biographic_operation.refresh_from_db()
    assert running_biographic_operation.status == RdpOperation.Status.FAILURE
    assert running_biographic_operation.error == {
        "message": "DedupEngine processing failed.",
        "state": "failed",
        "detail": "boom",
    }


@pytest.mark.parametrize("status", ["indexing", "deduplicating", "approved"])
def test_sync_waits_until_deduplicated(running_biographic_operation: RdpOperation, client, status: str) -> None:
    client.retrieve_dataset.return_value = {"dataset_id": DATASET_ID, "status": status}

    assert workflow.sync_biographic_result(running_biographic_operation) is False

    client.retrieve_findings.assert_not_called()
    running_biographic_operation.refresh_from_db()
    assert running_biographic_operation.status == RdpOperation.Status.RUNNING


def test_sync_deduplicated_creates_findings(
    people_operation: RdpOperation,
    people_rdp: tuple[Rdp, list[Individual]],
    client,
) -> None:
    _, individuals = people_rdp
    client.retrieve_dataset.return_value = {"dataset_id": DATASET_ID, "status": "deduplicated"}
    client.retrieve_findings.return_value = [_finding(individuals[0].pk, individuals[1].pk)]

    assert workflow.sync_biographic_result(people_operation) is True

    people_operation.refresh_from_db()
    assert people_operation.status == RdpOperation.Status.SUCCESS
    [finding] = RdpOperationFinding.objects.filter(operation=people_operation)
    assert finding.individual_id == individuals[0].pk
    assert finding.related_individual_id == individuals[1].pk


@pytest.mark.parametrize("error", [RemoteError("remote"), RemoteUnavailableError("down")])
def test_sync_remote_error_fails_operation(
    running_biographic_operation: RdpOperation, client, error: Exception
) -> None:
    client.retrieve_dataset.side_effect = error

    assert workflow.sync_biographic_result(running_biographic_operation) is True

    running_biographic_operation.refresh_from_db()
    assert running_biographic_operation.status == RdpOperation.Status.FAILURE
    assert running_biographic_operation.error == {"message": str(error)}


def test_sync_invalid_findings_fail_operation(people_operation: RdpOperation, client) -> None:
    client.retrieve_dataset.return_value = {"dataset_id": DATASET_ID, "status": "deduplicated"}
    client.retrieve_findings.return_value = [_finding(0, 0)]

    assert workflow.sync_biographic_result(people_operation) is True

    people_operation.refresh_from_db()
    assert people_operation.status == RdpOperation.Status.FAILURE


@pytest.fixture
def run(mocker: MockerFixture):
    mocker.patch.object(processing, "build_dedup_operation_callback_url", return_value="https://cw/callback/")
    return workflow.run_biographic_deduplication


def test_run_creates_dataset_uploads_and_processes(
    people_operation: RdpOperation,
    client,
    run,
    mocker: MockerFixture,
) -> None:
    client.retrieve_dataset_or_none.return_value = None
    client.create_dataset.return_value = {"dataset_id": str(people_operation.id), "status": "pending"}
    client.create_records.return_value = {"received": 3, "records_count": 3}

    run(people_operation)

    client.create_dataset.assert_called_once_with(notification_url="https://cw/callback/")
    assert sum(len(call.args[0]) for call in client.create_records.call_args_list) == 3
    client.process.assert_called_once_with()


def test_run_resumes_pending_dataset_without_creating_a_new_one(people_operation: RdpOperation, client, run) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": "pending"}

    run(people_operation)

    client.create_dataset.assert_not_called()
    client.create_records.assert_called()
    client.process.assert_called_once_with()


def test_run_recreates_dataset_that_no_longer_exists(people_operation: RdpOperation, client, run) -> None:
    client.retrieve_dataset_or_none.return_value = None
    client.create_dataset.return_value = {"dataset_id": str(people_operation.id), "status": "pending"}

    run(people_operation)

    client.create_dataset.assert_called_once_with(notification_url="https://cw/callback/")
    client.process.assert_called_once_with()


def test_run_retries_failed_dataset_without_uploading_again(people_operation: RdpOperation, client, run) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": "failed"}

    run(people_operation)

    client.create_records.assert_not_called()
    client.process.assert_called_once_with()


@pytest.mark.parametrize("status", ["indexing", "indexed", "deduplicating"])
def test_run_waits_for_running_dataset(people_operation: RdpOperation, client, run, status: str) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": status}

    run(people_operation)

    client.process.assert_not_called()
    client.create_records.assert_not_called()


def test_run_syncs_already_deduplicated_dataset(
    people_operation: RdpOperation,
    client,
    run,
    mocker: MockerFixture,
) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": "deduplicated"}
    sync = mocker.patch.object(workflow, "sync_biographic_result")

    run(people_operation)

    sync.assert_called_once_with(people_operation)
    client.process.assert_not_called()


@pytest.mark.parametrize("status", ["approved", "rejected", "canceled"])
def test_run_rejects_dataset_that_can_not_be_processed(
    people_operation: RdpOperation,
    client,
    run,
    status: str,
) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": status}

    with pytest.raises(RdpWorkflowError, match="can not process"):
        run(people_operation)


def test_run_requires_named_individuals(rdp: Rdp, client, run) -> None:
    from testutils.factories import BiographicRdpOperationFactory

    operation = BiographicRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.RUNNING)
    client.retrieve_dataset_or_none.return_value = None

    with pytest.raises(RdpWorkflowError, match="no named individuals"):
        run(operation)

    client.create_dataset.assert_not_called()


def test_run_requires_uploadable_records(
    people_operation: RdpOperation,
    client,
    run,
    mocker: MockerFixture,
) -> None:
    client.retrieve_dataset_or_none.return_value = {"dataset_id": DATASET_ID, "status": "pending"}
    mocker.patch.object(workflow.BiographicDedupProcessor, "upload_records", return_value=0)

    with pytest.raises(RdpWorkflowError, match="no named individuals"):
        run(people_operation)

    client.process.assert_not_called()
