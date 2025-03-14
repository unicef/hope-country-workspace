import pytest

from country_workspace.utils.fields import clean_field_name

TO_REMOVE = ("_h_c", "_h_f", "_i_c", "_i_f")


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
