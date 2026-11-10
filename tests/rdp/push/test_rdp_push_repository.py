from functools import partial
from uuid import uuid4

import pytest

from country_workspace.models import Program, Rdp
from country_workspace.rdp.push import repository


pytestmark = pytest.mark.django_db


def test_get_or_create_rdp_push_data_job(rdp: Rdp) -> None:
    push_attempt_id = uuid4()
    get_job = partial(repository.get_or_create_rdp_push_data_job, rdp=rdp, action="test.action")

    job, created = get_job(push_attempt_id=push_attempt_id)

    assert created is True
    assert job.config == {"rdp_id": rdp.pk, "push_attempt_id": str(push_attempt_id)}
    assert (job.rdp_id, job.program_id, job.owner_id) == (rdp.pk, rdp.program_id, rdp.pushed_by_id)
    assert job.type == repository.AsyncJob.JobType.TASK
    assert job.action == "test.action"
    assert get_job(push_attempt_id=push_attempt_id) == (job, False)

    other_job, created = get_job(push_attempt_id=uuid4())

    assert created is True
    assert other_job.pk != job.pk


def test_claim_rdp_data_push(push_pending_rdp: Rdp) -> None:
    result = repository.claim_rdp_data_push(
        rdp_id=push_pending_rdp.pk,
        push_attempt_id=push_pending_rdp.push_attempt_id,
    )

    assert result is not None
    assert result.pk == push_pending_rdp.pk
    push_pending_rdp.refresh_from_db()
    assert push_pending_rdp.hope_rdi_id == "N/A"


def test_claim_rdp_data_push_rejects_already_claimed(push_pending_rdp: Rdp) -> None:
    push_pending_rdp.hope_rdi_id = "RID"
    push_pending_rdp.save(update_fields=["hope_rdi_id"])

    assert (
        repository.claim_rdp_data_push(
            rdp_id=push_pending_rdp.pk,
            push_attempt_id=push_pending_rdp.push_attempt_id,
        )
        is None
    )


def test_claim_rdp_data_push_rejects_other_attempt(push_pending_rdp: Rdp) -> None:
    assert repository.claim_rdp_data_push(rdp_id=push_pending_rdp.pk, push_attempt_id=uuid4()) is None


def test_serializer_for_program_without_serializer(program: Program) -> None:
    program.serializer = None
    program.save(update_fields=["serializer"])

    serializer = repository.serializer_for_program(program.hope_id)
    data = [{"value": 1}]

    assert serializer(data) is data


def test_serializer_for_program_with_serializer(program: Program) -> None:
    from testutils.factories import DataSerializerFactory

    serializer = DataSerializerFactory()
    program.serializer = serializer
    program.save(update_fields=["serializer"])

    resolved = repository.serializer_for_program(program.hope_id)

    assert resolved.__self__.pk == serializer.pk
