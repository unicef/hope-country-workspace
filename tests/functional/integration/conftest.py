import pytest

from country_workspace.models import SyncLog
from testutils.factories import OfficeFactory


@pytest.fixture(autouse=True)
def sync_checkers(prepare_checkers) -> None:
    SyncLog.objects.refresh()


@pytest.fixture
def office():
    return OfficeFactory(
        name="Afghanistan",
        slug="afghanistan",
        code="AF",
    )
