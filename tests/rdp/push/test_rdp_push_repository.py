from uuid import uuid4

import pytest
from pytest_mock import MockerFixture

from country_workspace.models import Rdp
from country_workspace.rdp.push import repository


pytestmark = pytest.mark.django_db


def test_get_or_create_rdp_push_data_job(
    rdp: Rdp,
    mocker: MockerFixture,
) -> None:
    push_attempt_id = uuid4()
    job = mocker.MagicMock()
    get_or_create = mocker.patch.object(repository.AsyncJob.objects, "get_or_create", return_value=(job, True))

    assert repository.get_or_create_rdp_push_data_job(
        rdp=rdp,
        push_attempt_id=push_attempt_id,
        action="test.action",
    ) == (job, True)

    get_or_create.assert_called_once_with(
        rdp=rdp,
        action="test.action",
        config={"rdp_id": rdp.pk, "push_attempt_id": str(push_attempt_id)},
        defaults={
            "description": f"Push RDP {rdp.pk} data to HOPE",
            "type": repository.AsyncJob.JobType.TASK,
            "owner_id": rdp.pushed_by_id,
            "program_id": rdp.program_id,
        },
    )


def test_claim_rdp_data_push(push_pending_rdp: Rdp) -> None:
    result = repository.claim_rdp_data_push(
        rdp_id=push_pending_rdp.pk,
        push_attempt_id=push_pending_rdp.push_attempt_id,
    )

    assert result is not None
    assert result.hope_rdi_id == "N/A"


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


def test_serializer_for_program_without_serializer(program) -> None:
    program.serializer = None
    program.save(update_fields=["serializer"])

    serializer = repository.serializer_for_program(program.hope_id)
    data = [{"value": 1}]

    assert serializer(data) is data


def test_serializer_for_program_with_serializer(program) -> None:
    from testutils.factories import DataSerializerFactory

    serializer = DataSerializerFactory()
    program.serializer = serializer
    program.save(update_fields=["serializer"])

    resolved = repository.serializer_for_program(program.hope_id)

    assert resolved.__self__.pk == serializer.pk
