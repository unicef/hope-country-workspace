import pytest

from country_workspace.models import SyncLog
from testutils.factories import OfficeFactory


HOPE_PROGRAM_ID = "a4cad4c6-b512-42a5-9be5-cce9760a46d8"


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


@pytest.fixture
def program_id():
    return HOPE_PROGRAM_ID
