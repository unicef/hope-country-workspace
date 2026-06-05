from typing import TYPE_CHECKING
from unittest import mock
from unittest.mock import Mock

import pytest

from country_workspace.models.base import Validable

if TYPE_CHECKING:
    from country_workspace.models import Household
    from country_workspace.workspaces.models import CountryHousehold, CountryIndividual


@pytest.fixture
def household() -> "CountryHousehold":
    from testutils.factories import CountryHouseholdFactory

    return CountryHouseholdFactory()


@pytest.fixture
def individual(household) -> "CountryIndividual":
    from testutils.factories import CountryIndividualFactory

    return CountryIndividualFactory(household=household)


def test_properties(household: "CountryHousehold"):
    assert household.program == household.batch.program
    assert household.country_office == household.batch.country_office


def test_validate_with_checker(individual: "CountryHousehold"):
    household: Household = individual.household
    assert household.validate_with_checker()
    assert household.errors == {}
    with mock.patch.object(household.program.beneficiary_validator, "validate", Mock(return_value=["Error"])):
        assert not household.validate_with_checker()
        assert household.errors == {"dct": ["Error"]}


def test_validate_with_checker_preserves_multiselect_invalid_values_as_list(household):
    checker = Mock()
    checker.validate.return_value = {household.pk: {"reasons_oos": ["Invalid value"]}}
    checker.form = Mock(
        cleaned_data={},
        fields={
            "reasons_oos": Mock(widget=Mock(allow_multiple_selected=True)),
        },
    )
    household.flex_fields = {"reasons_oos": "invalid-choice"}

    with mock.patch.object(type(household), "checker", mock.PropertyMock(return_value=checker)):
        household.validate_with_checker()

    household.refresh_from_db()
    assert household.flex_fields["reasons_oos"] == ["invalid-choice"]


def test_normalize_invalid_value_for_field_passthrough_for_non_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=False))

    value = "raw-value"
    result = Validable._normalize_invalid_value_for_field(field, value)

    assert result == value


def test_normalize_invalid_value_for_field_none_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._normalize_invalid_value_for_field(field, None)

    assert result == []


def test_normalize_invalid_value_for_field_list_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    value = ["a", "b"]
    result = Validable._normalize_invalid_value_for_field(field, value)

    assert result == value


def test_normalize_invalid_value_for_field_tuple_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._normalize_invalid_value_for_field(field, ("a", "b"))

    assert result == ["a", "b"]


def test_normalize_invalid_value_for_field_set_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._normalize_invalid_value_for_field(field, {"a", "b"})

    assert set(result) == {"a", "b"}


def test_normalize_invalid_value_for_field_scalar_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._normalize_invalid_value_for_field(field, "single")

    assert result == ["single"]
