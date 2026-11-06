from contextlib import nullcontext
from uuid import UUID, uuid4

import pytest
from django.db import IntegrityError, transaction

from country_workspace.models import Rdp
from country_workspace.models.rdp import RdpPushStatus


pytestmark = pytest.mark.django_db


def test_start_push_attempt(rdp: Rdp) -> None:
    previous_attempt_id = rdp.start_push_attempt()
    push_attempt_id = rdp.start_push_attempt()

    rdp.refresh_from_db()

    assert isinstance(push_attempt_id, UUID)
    assert push_attempt_id != previous_attempt_id
    assert rdp.status == Rdp.PushStatus.PUSH_PENDING
    assert rdp.push_attempt_id == push_attempt_id


@pytest.mark.parametrize("status", [Rdp.PushStatus.SUCCESS, Rdp.PushStatus.FAILURE], ids=["success", "failure"])
def test_finish_push_attempt(rdp: Rdp, status: RdpPushStatus) -> None:
    rdp.start_push_attempt()

    rdp.finish_push_attempt(status=status, hope_rdi_id="RID")

    rdp.refresh_from_db()

    assert rdp.status == status
    assert rdp.hope_rdi_id == "RID"
    assert rdp.push_attempt_id is None


def test_finish_push_attempt_rejects_invalid_status(rdp: Rdp) -> None:
    rdp.start_push_attempt()
    previous = (rdp.status, rdp.push_attempt_id, rdp.hope_rdi_id)

    with pytest.raises(ValueError, match="Invalid final push status"):
        rdp.finish_push_attempt(status=Rdp.PushStatus.PENDING, hope_rdi_id="RID")

    assert (rdp.status, rdp.push_attempt_id, rdp.hope_rdi_id) == previous
    rdp.refresh_from_db()
    assert (rdp.status, rdp.push_attempt_id, rdp.hope_rdi_id) == previous


@pytest.mark.parametrize("hope_rdi_id", [None, "RID"], ids=["without_rdi", "with_rdi"])
def test_mark_cancelled(rdp: Rdp, hope_rdi_id: str | None) -> None:
    rdp.start_push_attempt()
    rdp.hope_rdi_id = hope_rdi_id
    rdp.save(update_fields=["hope_rdi_id"])

    rdp.mark_cancelled()

    rdp.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.CANCELLED
    assert rdp.hope_rdi_id == (hope_rdi_id or "N/A")
    assert rdp.push_attempt_id is None


@pytest.mark.parametrize("status", [RdpPushStatus.PUSH_PENDING, RdpPushStatus.PENDING])
def test_rdp_rejects_inconsistent_push_attempt(rdp: Rdp, status: RdpPushStatus) -> None:
    push_attempt_id = None if status == RdpPushStatus.PUSH_PENDING else uuid4()

    with pytest.raises(IntegrityError), transaction.atomic():
        Rdp.objects.filter(pk=rdp.pk).update(status=status, push_attempt_id=push_attempt_id)


@pytest.mark.parametrize(
    ("status", "blocked"),
    [
        (RdpPushStatus.PENDING, True),
        (RdpPushStatus.REVIEW_PENDING, True),
        (RdpPushStatus.PUSH_PENDING, True),
        (RdpPushStatus.FAILURE, True),
        (RdpPushStatus.SUCCESS, False),
        (RdpPushStatus.CANCELLED, False),
    ],
)
def test_rdp_is_unique_per_program_while_unfinished(rdp: Rdp, status: RdpPushStatus, blocked: bool) -> None:
    from testutils.factories import RdpFactory

    Rdp.objects.filter(pk=rdp.pk).update(
        status=status, push_attempt_id=uuid4() if status == RdpPushStatus.PUSH_PENDING else None
    )

    with pytest.raises(IntegrityError) if blocked else nullcontext(), transaction.atomic():
        RdpFactory(program=rdp.program)
