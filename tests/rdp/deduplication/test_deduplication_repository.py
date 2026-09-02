import pytest

from country_workspace.models import Rdp
from country_workspace.rdp.deduplication.repository import rdp_for_dedup, release_rdp_dedup_settings_lock

pytestmark = pytest.mark.django_db


@pytest.fixture
def rdp(user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(pushed_by=user)


@pytest.fixture(params=[True, False], ids=["locked", "unlocked"])
def locked_rdp(request: pytest.FixtureRequest, user) -> Rdp:
    from testutils.factories import CountryRdpFactory

    return CountryRdpFactory(pushed_by=user, is_dedup_settings_locked=request.param)


def test_rdp_for_dedup(rdp: Rdp) -> None:
    result = rdp_for_dedup(pk=rdp.pk)

    assert result == rdp
    assert "program" in result._state.fields_cache


def test_release_rdp_dedup_settings_lock(locked_rdp: Rdp) -> None:
    release_rdp_dedup_settings_lock(rdp_id=locked_rdp.pk)
    locked_rdp.refresh_from_db()

    assert locked_rdp.is_dedup_settings_locked is False
