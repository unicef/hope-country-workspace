import pytest
from unittest.mock import Mock

from country_workspace.validators.beneficiaries import validate_beneficiaries, _collect_validation_errors
from country_workspace.workspaces.admin.forms import ValidateMode
from country_workspace.utils.types import BeneficiaryMapping
from country_workspace.utils.config import ValidateModeConfig
from country_workspace.models.office import Office
from country_workspace.workspaces.exceptions import BeneficiaryValidationError


@pytest.fixture
def mapping_and_office() -> tuple[BeneficiaryMapping, Office]:
    from testutils.factories import CountryHouseholdFactory, ProgramFactory

    program = ProgramFactory()
    mapping: BeneficiaryMapping = {}
    for i in range(1, 3):
        beneficiary = CountryHouseholdFactory(batch__program=program, batch__country_office=program.country_office)
        beneficiary.validate_with_checker = Mock(return_value=True)
        mapping[i] = beneficiary
    return mapping, program.country_office


@pytest.fixture(params=ValidateMode.__members__.values())
def config(request) -> ValidateModeConfig:
    return {
        "validate_mode": request.param,
    }


@pytest.fixture(params=[mode for mode in ValidateMode if mode != ValidateMode.NONE])
def failing_config(request) -> ValidateModeConfig:
    return {
        "validate_mode": request.param,
    }


def test_validate_beneficiaries_success(
    config: ValidateModeConfig, mapping_and_office: tuple[BeneficiaryMapping, Office]
) -> None:
    beneficiary_mapping, office = mapping_and_office

    validate_beneficiaries(beneficiary_mapping, config, office)

    for beneficiary in beneficiary_mapping.values():
        if config["validate_mode"] == ValidateMode.NONE:
            beneficiary.validate_with_checker.assert_not_called()
        else:
            fail_if_alien = config["validate_mode"] == ValidateMode.CHECK_AND_FAIL_IF_ALIEN
            beneficiary.validate_with_checker.assert_called_once_with(fail_if_alien=fail_if_alien)


def test_validate_beneficiaries_validation_error(
    failing_config: ValidateModeConfig, mapping_and_office: tuple[BeneficiaryMapping, Office]
) -> None:
    beneficiary_mapping, office = mapping_and_office
    beneficiary_mapping[1].validate_with_checker.return_value = False

    with pytest.raises(BeneficiaryValidationError):
        validate_beneficiaries(beneficiary_mapping, failing_config, office)


def test_validate_beneficiaries_none_mode(mapping_and_office: tuple[BeneficiaryMapping, Office]) -> None:
    beneficiary_mapping, office = mapping_and_office
    config = {"validate_mode": ValidateMode.NONE}

    validate_beneficiaries(beneficiary_mapping, config, office)

    for beneficiary in beneficiary_mapping.values():
        beneficiary.validate_with_checker.assert_not_called()


def test_collect_validation_errors_success() -> None:
    beneficiary_mapping = {
        1: Mock(validate_with_checker=Mock(return_value=True)),
        2: Mock(validate_with_checker=Mock(return_value=True)),
    }
    fail_if_alien = True

    result = _collect_validation_errors(beneficiary_mapping, fail_if_alien)

    assert result == []
    for beneficiary in beneficiary_mapping.values():
        beneficiary.validate_with_checker.assert_called_once_with(fail_if_alien=fail_if_alien)


def test_collect_validation_errors_with_failures() -> None:
    beneficiary_mapping = {
        1: Mock(validate_with_checker=Mock(return_value=True)),
        2: Mock(validate_with_checker=Mock(return_value=False)),
        3: Mock(validate_with_checker=Mock(return_value=False)),
    }
    fail_if_alien = False

    result = _collect_validation_errors(beneficiary_mapping, fail_if_alien)

    assert result == [2, 3]
    for beneficiary in beneficiary_mapping.values():
        beneficiary.validate_with_checker.assert_called_once_with(fail_if_alien=fail_if_alien)
