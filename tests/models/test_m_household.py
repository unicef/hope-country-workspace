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


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("not-eligible, missing-documents", ["not-eligible, missing-documents"]),
        ("other security economical family", ["other security economical family"]),
        (("reason-a", "reason-b"), ["reason-a", "reason-b"]),
        (None, []),
    ],
)
def test_validate_with_checker_normalizes_multiselect_values_before_validation(household, raw_value, expected):
    checker = Mock()
    checker.validate.return_value = {}
    checker.form = Mock(
        cleaned_data={"reasons_oos": expected},
        fields={
            "reasons_oos": Mock(widget=Mock(allow_multiple_selected=True)),
        },
    )
    household.flex_fields = {"reasons_oos": raw_value}

    with mock.patch.object(type(household), "checker", mock.PropertyMock(return_value=checker)):
        household.validate_with_checker()

    checker.validate.assert_called_once_with(
        [{"reasons_oos": expected}],
        fail_if_alien=False,
    )


def test_normalize_multiselect_values_skips_fields_not_present_in_payload():
    checker = Mock()
    checker.form = Mock(
        fields={
            "reasons_oos": Mock(widget=Mock(allow_multiple_selected=True)),
            "missing_in_payload": Mock(widget=Mock(allow_multiple_selected=True)),
        }
    )
    flex_fields = {"reasons_oos": "single-value"}

    with mock.patch.object(
        Validable, "_coerce_multiselect_value", wraps=Validable._coerce_multiselect_value
    ) as coerced:
        normalized = Validable._normalize_multiselect_values(checker, flex_fields)

    assert normalized == {"reasons_oos": ["single-value"]}
    coerced.assert_called_once_with(checker.form.fields["reasons_oos"], "single-value")


def test_coerce_multiselect_value_passthrough_for_non_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=False))

    value = "raw-value"
    result = Validable._coerce_multiselect_value(field, value)

    assert result == value


def test_coerce_multiselect_value_none_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._coerce_multiselect_value(field, None)

    assert result == []


def test_coerce_multiselect_value_list_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    value = ["a", "b"]
    result = Validable._coerce_multiselect_value(field, value)

    assert result == value


def test_coerce_multiselect_value_tuple_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._coerce_multiselect_value(field, ("a", "b"))

    assert result == ["a", "b"]


def test_coerce_multiselect_value_set_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._coerce_multiselect_value(field, {"a", "b"})

    assert set(result) == {"a", "b"}


def test_coerce_multiselect_value_scalar_for_multiselect():
    field = Mock(widget=Mock(allow_multiple_selected=True))

    result = Validable._coerce_multiselect_value(field, "single")

    assert result == ["single"]
