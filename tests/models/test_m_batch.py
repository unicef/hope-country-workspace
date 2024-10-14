from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from country_workspace.workspaces.models import CountryBatch


@pytest.fixture()
def program():
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory()


@pytest.fixture()
def batch(program) -> "CountryBatch":
    from testutils.factories import CountryBatchFactory

    return CountryBatchFactory(program=program, country_office=program.country_office)


def test_properties(batch: "CountryBatch"):
    assert batch.country_office == batch.program.country_office
