import pytest
from pytest_mock import MockFixture

from country_workspace.utils.fields import (
    TO_REMOVE,
    clean_field_name,
    clean_field_names,
)


@pytest.mark.parametrize(
    ("input_value", "expected_output"),
    [(f"field{substr}_foo", "field_foo") for substr in TO_REMOVE]
    + [(f"FIELD{substr.upper()}_foo", "field_foo") for substr in TO_REMOVE]
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
