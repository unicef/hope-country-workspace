import pytest
from pytest_mock import MockerFixture
from unittest.mock import Mock

from country_workspace.workspaces.admin.cleaners.validate import validate_program
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


@pytest.mark.parametrize(
    ("return_value", "expected"),
    [(True, {"valid": 1, "invalid": 0}), (False, {"valid": 0, "invalid": 1})],
    ids=["valid", "invalid"],
)
def test_validate_program_success(
    mocker: MockerFixture, beneficiary: Beneficiary, master_detail: bool, return_value: bool, expected: dict[str, int]
) -> None:
    model_path = "country_workspace.models.Household" if master_detail else "country_workspace.models.Individual"
    mocker.patch(f"{model_path}.validate_with_checker", return_value=return_value)
    assert validate_program(Mock(program=beneficiary.program)) == expected


def test_validate_program_exception(mocker: MockerFixture, beneficiary: Beneficiary, master_detail: bool) -> None:
    model_path = "country_workspace.models.Household" if master_detail else "country_workspace.models.Individual"
    mocker.patch(f"{model_path}.validate_with_checker", side_effect=Exception("Test error"))
    with pytest.raises(Exception, match="Test error"):
        validate_program(Mock(program=beneficiary.program))


def test_validate_program_empty_queryset(program: CountryProgram) -> None:
    assert validate_program(Mock(program=program)) == {"valid": 0, "invalid": 0}
