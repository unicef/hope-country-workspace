from uuid import UUID

import pytest

from country_workspace.models import Rdp


pytestmark = pytest.mark.django_db


def test_start_push_attempt(rdp: Rdp) -> None:
    push_attempt_id = rdp.start_push_attempt()

    rdp.refresh_from_db()

    assert isinstance(push_attempt_id, UUID)
    assert rdp.status == Rdp.PushStatus.PUSH_PENDING
    assert rdp.push_attempt_id == push_attempt_id


@pytest.mark.parametrize("status", [Rdp.PushStatus.SUCCESS, Rdp.PushStatus.FAILURE], ids=["success", "failure"])
def test_finish_push_attempt(rdp: Rdp, status: str) -> None:
    rdp.start_push_attempt()

    rdp.finish_push_attempt(status=status, hope_rdi_id="RID")

    rdp.refresh_from_db()

    assert rdp.status == status
    assert rdp.hope_rdi_id == "RID"
    assert rdp.push_attempt_id is None


def test_finish_push_attempt_rejects_invalid_status(rdp: Rdp) -> None:
    with pytest.raises(ValueError, match="Invalid final push status"):
        rdp.finish_push_attempt(status=Rdp.PushStatus.PENDING, hope_rdi_id="RID")


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
