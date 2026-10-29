from uuid import uuid4

import pytest
from django.core import signing
from pytest_mock import MockerFixture

from country_workspace.contrib.biographic_dedup import BiographicSetState
from country_workspace.exceptions import RemoteError, RemoteUnavailableError
from country_workspace.models import RdpOperation, RdpOperationFinding
from country_workspace.rdp.biographic import workflow
from country_workspace.rdp.deduplication.constants import DEDUP_CALLBACK_SALT
from country_workspace.rdp.exceptions import RdpWorkflowError

pytestmark = pytest.mark.django_db


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
def make_client(mocker: MockerFixture):
    cm = mocker.patch.object(workflow, "make_biographic_client")
    return cm.return_value.__enter__.return_value


def test_build_callback_url(mocker: MockerFixture) -> None:
    mocker.patch.object(workflow, "get_dedup_callback_base_url", return_value="https://cw")
    operation_id = uuid4()

    url = workflow._build_callback_url(operation_id=operation_id)

    assert url.startswith("https://cw/")
    token = url.rstrip("/").rsplit("/", 1)[-1]
    assert signing.loads(token, salt=DEDUP_CALLBACK_SALT) == {"operation_id": str(operation_id)}


@pytest.mark.parametrize("value", [None, "abc", object()])
def test_individual_id_rejects_invalid(value: object) -> None:
    with pytest.raises(RemoteError):
        workflow._individual_id(value, "reference_pk")


def test_finding_scope_rejects_invalid() -> None:
    with pytest.raises(RemoteError):
        workflow._finding_scope({"scope": "galaxy"})  # type: ignore[typeddict-item]


def test_build_biographic_findings(biographic_operation, people_rdp) -> None:
    from testutils.factories import IndividualFactory

    rdp, individuals = people_rdp
    biographic_operation.rdp = rdp
    local_other = IndividualFactory(household=None, batch__program=rdp.program)
    foreign = IndividualFactory(household=None)

    built = workflow._build_biographic_findings(
        biographic_operation,
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
    assert built[0].details["score"] == 0.95


def test_build_biographic_findings_rejects_foreign_individual(biographic_operation, people_rdp) -> None:
    from testutils.factories import IndividualFactory

    rdp, individuals = people_rdp
    biographic_operation.rdp = rdp
    outsider = IndividualFactory(household=None, batch__program=rdp.program)

    with pytest.raises(RemoteError, match="not part of the current RDP"):
        workflow._build_biographic_findings(biographic_operation, [_finding(outsider.pk, individuals[0].pk)])


def test_sync_unknown_operation() -> None:
    assert workflow.sync_biographic_deduplication_result(operation_id=uuid4()) is False


@pytest.mark.parametrize("scenario", ["biometric", "not_running", "no_external_id"])
def test_sync_ignores_non_matching_operations(biographic_operation, mocker: MockerFixture, scenario: str) -> None:
    if scenario == "biometric":
        biographic_operation.operation_type = RdpOperation.Type.BIOMETRIC_DEDUPLICATION
    elif scenario == "not_running":
        biographic_operation.status = RdpOperation.Status.SUCCESS
    else:
        biographic_operation.external_id = ""
    biographic_operation.save()
    make_client = mocker.patch.object(workflow, "make_biographic_client")

    assert workflow.sync_biographic_deduplication_result(operation_id=biographic_operation.id) is False
    make_client.assert_not_called()


def test_sync_failed_state(biographic_operation, make_client) -> None:
    make_client.retrieve_dataset.return_value = {"dataset_id": 7, "status": "failed", "error": "boom"}

    assert workflow.sync_biographic_deduplication_result(operation_id=biographic_operation.id) is True

    biographic_operation.refresh_from_db()
    assert biographic_operation.status == RdpOperation.Status.FAILURE
    assert biographic_operation.error["detail"] == "boom"


def test_sync_still_running(biographic_operation, make_client) -> None:
    make_client.retrieve_dataset.return_value = {"dataset_id": 7, "status": "deduplicating"}

    assert workflow.sync_biographic_deduplication_result(operation_id=biographic_operation.id) is False

    make_client.retrieve_findings.assert_not_called()
    biographic_operation.refresh_from_db()
    assert biographic_operation.status == RdpOperation.Status.RUNNING


def test_sync_deduplicated_creates_findings(biographic_operation, make_client, people_rdp) -> None:
    rdp, individuals = people_rdp
    RdpOperation.objects.filter(pk=biographic_operation.pk).update(rdp=rdp)
    make_client.retrieve_dataset.return_value = {"dataset_id": 7, "status": "deduplicated"}
    make_client.retrieve_findings.return_value = [_finding(individuals[0].pk, individuals[1].pk)]

    assert workflow.sync_biographic_deduplication_result(operation_id=biographic_operation.id) is True

    biographic_operation.refresh_from_db()
    assert biographic_operation.status == RdpOperation.Status.SUCCESS
    [finding] = RdpOperationFinding.objects.filter(operation=biographic_operation)
    assert finding.individual_id == individuals[0].pk
    assert finding.related_individual_id == individuals[1].pk


@pytest.mark.parametrize("error", [RemoteError("remote"), RemoteUnavailableError("down")])
def test_sync_remote_error_fails_operation(biographic_operation, make_client, error: Exception) -> None:
    make_client.retrieve_dataset.side_effect = error

    assert workflow.sync_biographic_deduplication_result(operation_id=biographic_operation.id) is True

    biographic_operation.refresh_from_db()
    assert biographic_operation.status == RdpOperation.Status.FAILURE
    assert str(error) in biographic_operation.error["message"]


def test_get_or_create_set_state_reuses_existing(biographic_operation, mocker: MockerFixture) -> None:
    client = mocker.MagicMock()
    client.retrieve_dataset_or_none.return_value = {"dataset_id": 7, "status": "pending"}

    state = workflow._get_or_create_set_state(client=client, operation=biographic_operation)

    assert state == BiographicSetState.PENDING
    client.create_dataset.assert_not_called()


def test_get_or_create_set_state_creates_missing(biographic_operation, people_rdp, mocker: MockerFixture) -> None:
    rdp, _ = people_rdp
    biographic_operation.rdp = rdp
    biographic_operation.external_id = ""
    mocker.patch.object(workflow, "_build_callback_url", return_value="https://cw/cb/")
    client = mocker.MagicMock()
    client.create_dataset.return_value = {"dataset_id": 21, "status": "pending"}

    state = workflow._get_or_create_set_state(client=client, operation=biographic_operation)

    assert state == BiographicSetState.PENDING
    client.create_dataset.assert_called_once_with(notification_url="https://cw/cb/")
    biographic_operation.refresh_from_db()
    assert biographic_operation.external_id == "21"


def test_get_or_create_set_state_recreates_unknown_set(biographic_operation, people_rdp, mocker: MockerFixture) -> None:
    rdp, _ = people_rdp
    biographic_operation.rdp = rdp
    mocker.patch.object(workflow, "_build_callback_url", return_value="https://cw/cb/")
    client = mocker.MagicMock()
    client.retrieve_dataset_or_none.return_value = None
    client.create_dataset.return_value = {"dataset_id": 22, "status": "pending"}

    workflow._get_or_create_set_state(client=client, operation=biographic_operation)

    biographic_operation.refresh_from_db()
    assert biographic_operation.external_id == "22"


def test_get_or_create_set_state_requires_named_individuals(biographic_operation, mocker: MockerFixture) -> None:
    biographic_operation.external_id = ""
    client = mocker.MagicMock()

    with pytest.raises(RdpWorkflowError, match="named individuals"):
        workflow._get_or_create_set_state(client=client, operation=biographic_operation)

    client.create_dataset.assert_not_called()


@pytest.mark.parametrize(("state", "uploads"), [(BiographicSetState.PENDING, True), (BiographicSetState.FAILED, False)])
def test_prepare_set_uploads_only_pending(biographic_operation, mocker: MockerFixture, state, uploads: bool) -> None:
    mocker.patch.object(workflow, "_get_or_create_set_state", return_value=state)
    processor = mocker.patch.object(workflow, "BiographicDedupProcessor")
    processor.return_value.upload_records.return_value = 3

    assert workflow._prepare_set(client=mocker.MagicMock(), operation=biographic_operation) == state
    assert processor.return_value.upload_records.called is uploads


def test_prepare_set_requires_uploaded_records(biographic_operation, mocker: MockerFixture) -> None:
    mocker.patch.object(workflow, "_get_or_create_set_state", return_value=BiographicSetState.PENDING)
    mocker.patch.object(workflow, "BiographicDedupProcessor").return_value.upload_records.return_value = 0

    with pytest.raises(RdpWorkflowError):
        workflow._prepare_set(client=mocker.MagicMock(), operation=biographic_operation)


@pytest.mark.parametrize(
    ("state", "processes", "syncs"),
    [
        (BiographicSetState.PENDING, True, False),
        (BiographicSetState.FAILED, True, False),
        (BiographicSetState.INDEXING, False, False),
        (BiographicSetState.DEDUPLICATING, False, False),
        (BiographicSetState.DEDUPLICATED, False, True),
    ],
)
def test_run_biographic_deduplication(
    biographic_operation,
    make_client,
    mocker: MockerFixture,
    state: BiographicSetState,
    processes: bool,
    syncs: bool,
) -> None:
    mocker.patch.object(workflow, "_prepare_set", return_value=state)
    sync = mocker.patch.object(workflow, "sync_biographic_deduplication_result")

    workflow.run_biographic_deduplication(biographic_operation)

    assert make_client.process.called is processes
    assert sync.called is syncs


@pytest.mark.parametrize(
    "state", [BiographicSetState.APPROVED, BiographicSetState.REJECTED, BiographicSetState.CANCELED]
)
def test_run_biographic_deduplication_rejects_final_states(
    biographic_operation, make_client, mocker: MockerFixture, state: BiographicSetState
) -> None:
    mocker.patch.object(workflow, "_prepare_set", return_value=state)

    with pytest.raises(RdpWorkflowError):
        workflow.run_biographic_deduplication(biographic_operation)

    make_client.process.assert_not_called()
