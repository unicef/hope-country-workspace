from unittest.mock import patch

import pytest

from country_workspace.workspaces.admin.cleaners.name_parser import NameParserForm, name_parser_impl
from testutils.factories import CountryFactory, CountryIndividualFactory, DataCheckerFactory, OfficeFactory

pytestmark = [pytest.mark.django_db]


HIDDEN_FORM_FIELDS = {
    "action": "parse_names",
    "select_across": "0",
    "_selected_action": "1",
}


def test_name_parser_impl():
    """Test that name_parser_impl correctly splits names and updates flex fields."""
    # 1. Setup - Create test data
    full_name_field = "full_name"
    given_name_field = "given_name"
    family_name_field = "family_name"
    middle_name_field = "middle_name"

    individuals = [
        CountryIndividualFactory(flex_fields={full_name_field: "John Doe"}),
        CountryIndividualFactory(flex_fields={full_name_field: "Jane Marie Smith"}),
    ]

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "family_name_field": family_name_field,
        "middle_name_field": middle_name_field,
        "country_code": "us",  # Mocked, so value doesn't matter
    }

    def mock_parser(name: str) -> list[str]:
        if name == "John Doe":
            return ["given_name", "family_name"]
        if name == "Jane Marie Smith":
            return ["given_name", "middle_name", "family_name"]
        return ["given_name"]

    # 3. Run the implementation
    with patch("country_workspace.workspaces.admin.cleaners.name_parser.get_parser") as mock_get_parser:
        mock_get_parser.return_value = mock_parser

        name_parser_impl(
            records=type(individuals[0]).objects.all(),
            config=config,
            save=True,
        )

    # 4. Assertions
    # John Doe
    individuals[0].refresh_from_db()
    assert individuals[0].flex_fields[given_name_field] == "John"
    assert individuals[0].flex_fields[family_name_field] == "Doe"
    assert middle_name_field not in individuals[0].flex_fields

    # Jane Marie Smith
    individuals[1].refresh_from_db()
    assert individuals[1].flex_fields[given_name_field] == "Jane"
    assert individuals[1].flex_fields[middle_name_field] == "Marie"
    assert individuals[1].flex_fields[family_name_field] == "Smith"


def test_name_parser_form_prevents_source_as_destination():
    """Test that the form validation prevents using source field as a destination field."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    checker = DataCheckerFactory(fields=["full_name", "given_name", "family_name"])

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "given_name_field": "flex_fields__full_name",  # Same as source - should fail
        "family_name_field": "flex_fields__family_name",
        "country_code": "us",
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "source field cannot be the same as a destination field" in str(form.errors)


def test_name_parser_form_prevents_duplicate_destinations():
    """Test that the form validation prevents using the same field for multiple destinations."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    checker = DataCheckerFactory(fields=["full_name", "name_part"])

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "given_name_field": "flex_fields__name_part",
        "family_name_field": "flex_fields__name_part",  # Same as given_name_field - should fail
        "country_code": "us",
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "Each destination field must be unique" in str(form.errors)


def test_name_parser_form_requires_at_least_one_destination():
    """Test that the form validation requires at least one destination field."""
    country = CountryFactory(iso_code2="US", name="United States")
    office = OfficeFactory()
    office.countries.add(country)

    checker = DataCheckerFactory(fields=["full_name"])

    form_data = {
        **HIDDEN_FORM_FIELDS,
        "source_field": "flex_fields__full_name",
        "country_code": "us",
        # No destination fields specified
    }

    form = NameParserForm(
        data=form_data,
        checker=checker,
        tenant=office,
    )

    assert not form.is_valid()
    assert "At least one destination field must be selected" in str(form.errors)
