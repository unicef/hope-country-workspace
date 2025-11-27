import pytest
from country_workspace.workspaces.models import CountryHousehold, CountryIndividual, CountryProgram

type Beneficiary = CountryHousehold | CountryIndividual


@pytest.fixture(params=[True, False], ids=["master_detail_true", "master_detail_false"])
def master_detail(request: pytest.FixtureRequest) -> bool:
    return request.param


@pytest.fixture
def program(master_detail: bool) -> CountryProgram:
    from testutils.factories import CountryProgramFactory

    return CountryProgramFactory(beneficiary_group__master_detail=master_detail)


@pytest.fixture
def beneficiary(program: CountryProgram, master_detail: bool) -> Beneficiary:
    from testutils.factories import CountryHouseholdFactory, CountryIndividualFactory

    if master_detail:
        return CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)
    return CountryIndividualFactory(
        batch__program=program,
        batch__country_office=program.country_office,
        household=None,
    )
