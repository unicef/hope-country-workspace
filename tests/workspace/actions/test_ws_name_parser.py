from unittest.mock import MagicMock, patch

import pytest

from country_workspace.workspaces.admin.cleaners.name_parser import name_parser_impl
from testutils.factories import CountryIndividualFactory

pytestmark = [pytest.mark.django_db]


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
        CountryIndividualFactory(flex_fields={full_name_field: "No Change"}),
    ]

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "family_name_field": family_name_field,
        "middle_name_field": middle_name_field,
        "country_code": "us",  # Mocked, so value doesn't matter
    }

    # 2. Mock the parser - returns tuple of (name_dict, format)
    def mock_parser(name: str):
        mock = MagicMock()
        if name == "John Doe":
            mock.as_dict.return_value = {"given_name": "John", "family_name": "Doe"}
            mock.format.return_value = ["given_name", "family_name"]
        elif name == "Jane Marie Smith":
            mock.as_dict.return_value = {"given_name": "Jane", "middle_name": "Marie", "family_name": "Smith"}
            mock.format.return_value = ["given_name", "middle_name", "family_name"]
        else:
            mock.as_dict.return_value = {"given_name": "No Change"}
            mock.format.return_value = ["given_name"]
        return mock

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

    # No Change
    individuals[2].refresh_from_db()
    assert individuals[2].flex_fields[given_name_field] == "No Change"
    assert middle_name_field not in individuals[2].flex_fields
    assert family_name_field not in individuals[2].flex_fields
