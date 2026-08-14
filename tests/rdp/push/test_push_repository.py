from uuid import uuid4

import pytest
from django.db import transaction

from country_workspace.models import AsyncJob, Program, Rdp
from country_workspace.rdp.push.repository import (
    claim_rdp_data_push,
    get_or_create_rdp_push_data_job,
    lock_rdp_push_attempt,
    rdp_for_push,
    serializer_for_program,
)


pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(
        pushed_by=user,
        status=Rdp.PushStatus.PENDING,
        hope_rdi_id=None,
    )


@pytest.fixture(params=[True, False], ids=["with_serializer", "without_serializer"])
def program(request: pytest.FixtureRequest) -> Program:
    from testutils.factories import ProgramFactory

    return ProgramFactory() if request.param else ProgramFactory(serializer=None)


def test_lock_rdp_push_attempt(rdp: Rdp) -> None:
    push_attempt_id = rdp.start_push_attempt()

    with transaction.atomic():
        locked = lock_rdp_push_attempt(rdp_id=rdp.pk, push_attempt_id=push_attempt_id)

    assert locked is not None
    assert locked.pk == rdp.pk


def test_lock_rdp_push_attempt_rejects_wrong_attempt(rdp: Rdp) -> None:
    rdp.start_push_attempt()

    with transaction.atomic():
        locked = lock_rdp_push_attempt(rdp_id=rdp.pk, push_attempt_id=uuid4())

    assert locked is None


def test_claim_rdp_data_push(rdp: Rdp) -> None:
    push_attempt_id = rdp.start_push_attempt()

    claimed = claim_rdp_data_push(rdp_id=rdp.pk, push_attempt_id=push_attempt_id)

    assert claimed is not None

    rdp.refresh_from_db()
    assert rdp.hope_rdi_id == "N/A"


def test_claim_rdp_data_push_only_once(rdp: Rdp) -> None:
    push_attempt_id = rdp.start_push_attempt()

    assert claim_rdp_data_push(rdp_id=rdp.pk, push_attempt_id=push_attempt_id) is not None
    assert claim_rdp_data_push(rdp_id=rdp.pk, push_attempt_id=push_attempt_id) is None


def test_claim_rdp_data_push_rejects_wrong_attempt(rdp: Rdp) -> None:
    rdp.start_push_attempt()

    assert claim_rdp_data_push(rdp_id=rdp.pk, push_attempt_id=uuid4()) is None


def test_get_or_create_rdp_push_data_job(rdp: Rdp) -> None:
    push_attempt_id = rdp.start_push_attempt()

    first, first_created = get_or_create_rdp_push_data_job(
        rdp=rdp,
        push_attempt_id=push_attempt_id,
        action="test.action",
    )
    second, second_created = get_or_create_rdp_push_data_job(
        rdp=rdp,
        push_attempt_id=push_attempt_id,
        action="test.action",
    )

    assert first_created is True
    assert second_created is False
    assert first.pk == second.pk
    assert first.rdp_id == rdp.pk
    assert first.action == "test.action"
    assert first.config == {
        "rdp_id": rdp.pk,
        "push_attempt_id": str(push_attempt_id),
    }
    assert first.type == AsyncJob.JobType.TASK
    assert first.owner_id == rdp.pushed_by_id
    assert first.program_id == rdp.program_id


def test_rdp_for_push(rdp: Rdp) -> None:
    assert rdp_for_push(pk=rdp.pk) == rdp


def test_serializer_for_program(program: Program) -> None:
    serializer = serializer_for_program(program.hope_id)
    data = [{"foo": "bar"}]

    assert serializer(data) == data
