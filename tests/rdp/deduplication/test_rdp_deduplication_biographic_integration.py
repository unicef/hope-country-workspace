"""Biographic deduplication against a faked DedupEngine HTTP API, from run to approval."""

import json
from collections.abc import Iterator

import pytest
import responses
from constance.test import override_config

from country_workspace.models import Individual, Rdp, RdpOperation, RdpOperationFinding
from country_workspace.rdp import RdpWorkflowError
from country_workspace.rdp.deduplication.biographic.actions import approve_biographic_dataset_after_successful_push
from country_workspace.rdp.deduplication.biographic.workflow import run_biographic_deduplication
from country_workspace.rdp.deduplication.workflow import (
    check_cancellation_rejections,
    check_clean_rdp_deduplication,
    reject_cancelled_rdp_set_core,
    schedule_deduplication_approval,
    sync_deduplication_result,
)
from country_workspace.rdp.push.thresholds import evaluate_review_thresholds

pytestmark = pytest.mark.django_db

HDE = "https://de"


@pytest.fixture(autouse=True)
def configuration() -> Iterator[None]:
    with override_config(DEDUP_API_URL=HDE, DEDUP_API_TOKEN="token", APP_BASE_URL="https://cw.example.org"):
        yield


@pytest.fixture
def hde() -> Iterator[responses.RequestsMock]:
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def operation(people_rdp: tuple[Rdp, list[Individual]]) -> RdpOperation:
    from testutils.factories import BiographicRdpOperationFactory

    rdp, _ = people_rdp
    return BiographicRdpOperationFactory(
        rdp=rdp,
        status=RdpOperation.Status.RUNNING,
        config={"threshold_type": "count", "threshold_value": "0"},
    )


@pytest.fixture
def datasets(operation: RdpOperation) -> str:
    program = operation.rdp.program
    return f"{HDE}/api/biographic/{program.country_office.slug}/{program.code}/datasets/"


def _finding(individual: Individual, matched: Individual, scope: str = "batch") -> dict:
    return {
        "reference_pk": str(individual.pk),
        "matched_reference_pk": str(matched.pk),
        "scope": scope,
        "score": 0.95,
        "proximity_to_score": 0.1,
        "matched_full_name": matched.name,
        "matched_birth_date": None,
    }


def _deduplicated(
    hde: responses.RequestsMock,
    datasets: str,
    findings: list[dict],
    dataset_id: int = 7,
) -> None:
    hde.get(f"{datasets}{dataset_id}/", json={"dataset_id": dataset_id, "status": "deduplicated"})
    hde.get(f"{datasets}{dataset_id}/findings/", json={"count": len(findings), "next": None, "results": findings})


def test_biographic_deduplication_from_run_to_approval(
    hde: responses.RequestsMock,
    datasets: str,
    operation: RdpOperation,
    people_rdp: tuple[Rdp, list[Individual]],
) -> None:
    rdp, individuals = people_rdp
    hde.post(datasets, json={"dataset_id": 7, "status": "pending"}, status=201)
    hde.post(f"{datasets}7/records/", json={"received": 3, "records_count": 3})
    hde.post(f"{datasets}7/process/", json={"dataset_id": 7, "status": "indexing"})

    run_biographic_deduplication(operation)

    operation.refresh_from_db()
    assert operation.external_id == "7"
    created = json.loads(hde.calls[0].request.body)
    assert created["notify"] is True
    assert created["notification_url"].startswith("https://cw.example.org/")
    uploaded = json.loads(hde.calls[1].request.body)["records"]
    assert {record["reference_pk"] for record in uploaded} == {str(individual.pk) for individual in individuals}
    assert hde.calls[2].request.url == f"{datasets}7/process/"

    # DedupEngine calls back once scoring is done: the callback syncs the operation.
    _deduplicated(
        hde,
        datasets,
        [
            _finding(individuals[0], individuals[1]),
            _finding(individuals[1], individuals[0]),
            _finding(individuals[0], individuals[2], scope="population"),
        ],
    )
    assert sync_deduplication_result(operation_id=operation.id) is True

    operation.refresh_from_db()
    assert operation.status == RdpOperation.Status.SUCCESS
    assert RdpOperationFinding.objects.filter(operation=operation).count() == 3

    # Matches are reported from both sides, so the threshold counts individuals, not findings.
    thresholds, review_required = evaluate_review_thresholds(rdp=rdp)
    assert thresholds[RdpOperation.Type.BIOGRAPHIC_DEDUPLICATION.value]["findings_count"] == 2
    assert review_required is True

    # Reviewing, cleaning and cancelling leave the dataset to the shared deduplication layer.
    check, checked = check_clean_rdp_deduplication(rdp)
    assert check.allowed
    assert list(checked) == [operation]

    # Pushed to HOPE: the dataset becomes the population later RDPs are checked against.
    hde.post(f"{datasets}7/approve/", json={"dataset_id": 7, "status": "approved"})
    approve_biographic_dataset_after_successful_push(operation)
    operation.refresh_from_db()
    assert operation.log[-1]["result"] == {"success": True}


def test_biographic_deduplication_cancellation_rejects_the_dataset(
    hde: responses.RequestsMock,
    datasets: str,
    operation: RdpOperation,
    people_rdp: tuple[Rdp, list[Individual]],
    mocker,
) -> None:
    rdp, individuals = people_rdp
    RdpOperation.objects.filter(pk=operation.pk).update(external_id="7", status=RdpOperation.Status.SUCCESS)
    _deduplicated(hde, datasets, [_finding(individuals[0], individuals[1])])

    check, operation_ids = check_cancellation_rejections(rdp)

    assert check.allowed
    assert operation_ids == (operation.id,)

    rdp.status = Rdp.PushStatus.CANCELLED
    rdp.save(update_fields=["status"])
    hde.post(f"{datasets}7/reject/", json={"dataset_id": 7, "status": "rejected"})
    job = mocker.MagicMock(config={"rdp_id": rdp.pk, "operation_ids": [str(operation.id)]})

    assert reject_cancelled_rdp_set_core(job) == {"rdp_id": rdp.pk}

    assert hde.calls[-1].request.url == f"{datasets}7/reject/"
    operation.refresh_from_db()
    assert operation.log[-1]["result"] == {"success": True}


def test_biographic_deduplication_cancellation_is_blocked_while_dedupengine_works(
    hde: responses.RequestsMock,
    datasets: str,
    operation: RdpOperation,
) -> None:
    RdpOperation.objects.filter(pk=operation.pk).update(external_id="7")
    hde.get(f"{datasets}7/", json={"dataset_id": 7, "status": "deduplicating"})

    check, operation_ids = check_cancellation_rejections(operation.rdp)

    assert not check.allowed
    assert "can not cancel" in check.reason
    assert operation_ids == ()


def test_biographic_deduplication_clean_requires_deduplicated_dataset(
    hde: responses.RequestsMock,
    datasets: str,
    operation: RdpOperation,
) -> None:
    RdpOperation.objects.filter(pk=operation.pk).update(external_id="7", status=RdpOperation.Status.SUCCESS)
    hde.get(f"{datasets}7/", json={"dataset_id": 7, "status": "approved"})

    check, checked = check_clean_rdp_deduplication(operation.rdp)

    assert not check.allowed
    assert checked == ()


def test_biographic_deduplication_run_fails_without_named_individuals(
    hde: responses.RequestsMock,
    rdp: Rdp,
) -> None:
    from testutils.factories import BiographicRdpOperationFactory

    operation = BiographicRdpOperationFactory(rdp=rdp, status=RdpOperation.Status.RUNNING)

    with pytest.raises(RdpWorkflowError, match="no named individuals"):
        run_biographic_deduplication(operation)

    assert not hde.calls


def test_schedule_deduplication_approval_reaches_dedupengine(
    hde: responses.RequestsMock,
    datasets: str,
    operation: RdpOperation,
    mocker,
) -> None:
    RdpOperation.objects.filter(pk=operation.pk).update(external_id="7", status=RdpOperation.Status.SUCCESS)
    hde.post(f"{datasets}7/approve/", json={"dataset_id": 7, "status": "approved"})
    on_commit = mocker.patch("country_workspace.rdp.deduplication.workflow.transaction.on_commit")

    schedule_deduplication_approval(operation.rdp)
    on_commit.call_args.args[0]()

    assert hde.calls[-1].request.url == f"{datasets}7/approve/"
