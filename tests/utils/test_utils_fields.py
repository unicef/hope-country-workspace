import pytest
from pytest_mock import MockFixture

from country_workspace.utils.fields import (
    clean_field_name,
    TO_REMOVE_VALUES,
    clean_field_names,
    map_fields,
)


@pytest.mark.parametrize(
    ("input_value", "expected_output"),
    [(f"field{substr}_foo", "field_foo") for substr in TO_REMOVE_VALUES]
    + [(f"FIELD{substr.upper()}_foo", "field_foo") for substr in TO_REMOVE_VALUES]
    + [
        ("field_foo", "field_foo"),
    ],
)
def test_clean_field_name(input_value, expected_output):
    assert clean_field_name(input_value) == expected_output


def test_clean_field_names(mocker: MockFixture) -> None:
    clean_field_name_mock = mocker.patch("country_workspace.utils.fields.clean_field_name")

    cleaned = clean_field_names({(key := "foo"): "bar"})

    assert cleaned == {clean_field_name_mock.return_value: "bar"}
    clean_field_name_mock.assert_called_once_with(key)


@pytest.mark.parametrize(
    ("input_fields", "expected_output"),
    [
        ({"gender": "male"}, {"sex": "male"}),
        ({"name": "John"}, {"name": "John"}),
        ({}, {}),
        ({"gender": "female", "age": "30"}, {"sex": "female", "age": "30"}),
    ],
)
def test_map_fields(input_fields, expected_output):
    result = map_fields(input_fields)
    assert result == expected_output
