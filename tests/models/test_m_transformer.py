import pytest
from django.core.exceptions import ValidationError

from country_workspace.validators.mapping import ValueTransformationRulesValidator


@pytest.fixture
def transformer():
    from testutils.factories import TransformerFactory

    return TransformerFactory


def test_value_transformation_validator_valid_rules():
    validator = ValueTransformationRulesValidator()
    validator("sex:M=MALE\nsex:F=FEMALE")


@pytest.mark.parametrize(
    ("rules", "expected_error"),
    [
        ("invalid_rule", "Expected ':' character"),
        ("field:", "Expected one '=' character"),
        (":old=new", "Field name cannot be empty"),
        ("field:old=old", "Old value and new value must be different"),
        ("field=name:value", "Expected format: 'fieldname:old_value=new_value'"),
    ],
    ids=["invalid_format", "missing_equals", "empty_fieldname", "same_old_new", "no_equals_in_value_part"],
)
def test_value_transformation_validator_invalid_rules(rules, expected_error):
    validator = ValueTransformationRulesValidator()
    with pytest.raises(ValidationError, match=expected_error):
        validator(rules)


def test_value_transformation_validator_skips_empty_lines():
    """Test that ValueTransformationRulesValidator.__call__ skips empty lines (if line: check)."""
    validator = ValueTransformationRulesValidator()
    # Should not raise - empty lines are skipped
    validator("sex:M=MALE\n\nsex:F=FEMALE")
    validator("   \nsex:M=MALE\n\t\nsex:F=FEMALE")
    validator("\n\n\n")


@pytest.mark.parametrize(
    ("value_transformations", "expected"),
    [
        ("", {}),
        ("sex:M=MALE", {"sex": {"M": "MALE"}}),
        ("sex:M=MALE\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        (
            "status:1=ACTIVE\nstatus:0=INACTIVE\ngender:M=MALE",
            {"status": {"1": "ACTIVE", "0": "INACTIVE"}, "gender": {"M": "MALE"}},
        ),
    ],
    ids=["empty", "single_rule", "multiple_same_field", "multiple_fields"],
)
def test_value_transformations_as_dict(transformer, value_transformations, expected):
    t = transformer(value_transformations=value_transformations)
    assert t.value_transformations_as_dict == expected


@pytest.mark.parametrize(
    ("value_transformations", "expected"),
    [
        # Empty lines should be skipped
        ("sex:M=MALE\n\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\n   \nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\n\t\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
    ],
    ids=[
        "empty_line_newline",
        "empty_line_spaces",
        "empty_line_tab",
    ],
)
def test_value_transformations_as_dict_skips_empty_lines(transformer, value_transformations, expected):
    """Test that value_transformations_as_dict skips empty lines."""
    t = transformer(value_transformations=value_transformations)
    assert t.value_transformations_as_dict == expected


@pytest.mark.parametrize(
    ("value_transformations", "expected_error_line"),
    [
        # Lines without ":" or "=" should raise ValueError
        ("sex:M=MALE\ninvalid_line\nsex:F=FEMALE", 2),
        ("sex:M=MALE\nno_colon_or_equals\nsex:F=FEMALE", 2),
        # Lines with ":" but no "=" in value_part should raise ValueError
        ("sex:M=MALE\nfield:value_without_equals\nsex:F=FEMALE", 2),
        ("sex:M=MALE\nfield:old_value\nsex:F=FEMALE", 2),
        # Lines with "=" but no ":" should raise ValueError
        ("sex:M=MALE\nfield=name:value\nsex:F=FEMALE", 2),
    ],
    ids=[
        "line_without_colon_or_equals",
        "line_without_colon_or_equals_2",
        "line_with_colon_no_equals_in_value",
        "line_with_colon_no_equals_in_value_2",
        "equals_in_field_part_not_value_part",
    ],
)
def test_value_transformations_as_dict_raises_on_invalid_lines(
    transformer,
    value_transformations,
    expected_error_line,
):
    """Test that value_transformations_as_dict raises ValueError for invalid non-empty lines."""
    t = transformer(value_transformations=value_transformations)
    with pytest.raises(ValueError, match=f"Line {expected_error_line}"):
        t.value_transformations_as_dict  # noqa: B018


@pytest.mark.parametrize(
    ("value_transformations", "data", "expected"),
    [
        # No transformations
        ("", {"gender": "M"}, {"gender": "M"}),
        # Only value transformation
        ("gender:M=MALE", {"gender": "M"}, {"gender": "MALE"}),
        # Multiple value transformations
        ("gender:M=MALE\ngender:F=FEMALE", {"gender": "F"}, {"gender": "FEMALE"}),
        # Value transformation on different field
        ("status:1=ACTIVE", {"gender": "M", "status": "1"}, {"gender": "M", "status": "ACTIVE"}),
        # Value that doesn't match transformation
        ("gender:M=MALE", {"gender": "X"}, {"gender": "X"}),
        # Transformation rule exists but field_name not in data
        ("missing_field:old=new", {"other_field": "value"}, {"other_field": "value"}),
    ],
    ids=[
        "no_transformations",
        "only_value_transformation",
        "multiple_value_transformations",
        "transformation_on_different_field",
        "value_no_match",
        "field_not_in_data",
    ],
)
def test_apply(transformer, value_transformations, data, expected):
    t = transformer(value_transformations=value_transformations)
    result = t.apply(data)
    assert result == expected
    assert result is data
