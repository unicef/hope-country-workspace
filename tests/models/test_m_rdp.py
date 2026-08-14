from uuid import UUID

import pytest

from country_workspace.models import Rdp


pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(pushed_by=user)


def test_start_push_attempt(rdp: Rdp) -> None:
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["is_dedup_settings_locked"])

    push_attempt_id = rdp.start_push_attempt()

    rdp.refresh_from_db()

    assert isinstance(push_attempt_id, UUID)
    assert rdp.status == Rdp.PushStatus.PUSH_PENDING
    assert rdp.push_attempt_id == push_attempt_id
    assert rdp.is_dedup_settings_locked is False


def test_mark_deduplication_pending(rdp: Rdp) -> None:
    rdp.mark_deduplication_pending()

    rdp.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.DEDUP_PENDING
    assert rdp.is_dedup_settings_locked is True


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
def test_mark_deduplication_failed(rdp: Rdp, hope_rdi_id: str | None) -> None:
    rdp.hope_rdi_id = hope_rdi_id
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["hope_rdi_id", "is_dedup_settings_locked"])

    rdp.mark_deduplication_failed()

    rdp.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.FAILURE
    assert rdp.hope_rdi_id == (hope_rdi_id or "N/A")
    assert rdp.is_dedup_settings_locked is False


@pytest.mark.parametrize("hope_rdi_id", [None, "RID"], ids=["without_rdi", "with_rdi"])
def test_mark_cancelled(rdp: Rdp, hope_rdi_id: str | None) -> None:
    rdp.start_push_attempt()
    rdp.hope_rdi_id = hope_rdi_id
    rdp.is_dedup_settings_locked = True
    rdp.save(update_fields=["hope_rdi_id", "is_dedup_settings_locked"])

    rdp.mark_cancelled()

    rdp.refresh_from_db()

    assert rdp.status == Rdp.PushStatus.CANCELLED
    assert rdp.hope_rdi_id == (hope_rdi_id or "N/A")
    assert rdp.is_dedup_settings_locked is False
    assert rdp.push_attempt_id is None
