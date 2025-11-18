from unittest.mock import patch

import pytest

from country_workspace.workspaces.admin.cleaners.name_parser import name_parser_impl

pytestmark = [pytest.mark.django_db]


def test_name_parser_impl(individual_factory):
    """Test that name_parser_impl correctly splits names and updates flex fields."""
    # 1. Setup - Create test data
    full_name_field = "full_name"
    given_name_field = "given_name"
    family_name_field = "family_name"
    middle_name_field = "middle_name"

    individuals = [
        individual_factory(flex_fields={full_name_field: "John Doe"}),
        individual_factory(flex_fields={full_name_field: "Jane Marie Smith"}),
        individual_factory(flex_fields={full_name_field: "No Change"}),
    ]

    config = {
        "source_field": full_name_field,
        "given_name_field": given_name_field,
        "family_name_field": family_name_field,
        "middle_name_field": middle_name_field,
        "country_code": "us",  # Mocked, so value doesn't matter
    }

    # 2. Mock the parser
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

    # No Change
    individuals[2].refresh_from_db()
    assert individuals[2].flex_fields[given_name_field] == "No Change"
    assert middle_name_field not in individuals[2].flex_fields
    assert family_name_field not in individuals[2].flex_fields
