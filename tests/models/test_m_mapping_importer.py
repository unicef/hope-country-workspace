import pytest
from django.core.exceptions import ValidationError

from country_workspace.validators.mapping import FieldMappingRulesValidator, ValueTransformationRulesValidator


@pytest.fixture
def mapping_importer():
    from testutils.factories import MappingImporterFactory

    return MappingImporterFactory


def test_validator_valid_rules():
    validator = FieldMappingRulesValidator()
    validator("gender=sex\nage=birth_year")


@pytest.mark.parametrize(
    ("rules", "expected_error"),
    [
        ("invalid_rule", "Expected one '=' character"),
        ("gender=gender", "Field names must be different"),
        ("=invalid", "old_fieldname=new_fieldname"),
    ],
    ids=["invalid_format", "same_field_names", "missing_old_fieldname"],
)
def test_validator_invalid_rules(rules, expected_error):
    validator = FieldMappingRulesValidator()
    with pytest.raises(ValidationError, match=expected_error):
        validator(rules)


@pytest.mark.parametrize(
    ("rules", "data", "expected"),
    [
        ("", {"gender": "MALE", "age": 25}, {"gender": "MALE", "age": 25}),
        (
            "gender=sex\nage=birth_year",
            {"gender": "MALE", "age": 25, "country": "UA"},
            {"sex": "MALE", "birth_year": 25, "country": "UA"},
        ),
    ],
    ids=["no_rules", "valid_rules"],
)
def test_apply_successful(mapping_importer, rules, data, expected):
    mi = mapping_importer(rules=rules)
    result = mi.apply(data)
    assert result == expected
    assert result is data


@pytest.mark.parametrize(
    ("rules", "expected"),
    [
        ("", {}),
        ("gender=sex", {"gender": "sex"}),
        ("gender=sex\nage=birth_year", {"gender": "sex", "age": "birth_year"}),
        (
            "field1=mapped1\nfield2=mapped2\nfield3=mapped3",
            {"field1": "mapped1", "field2": "mapped2", "field3": "mapped3"},
        ),
    ],
    ids=["empty_rules", "single_rule", "multiple_rules", "three_rules"],
)
def test_rules_as_dict(mapping_importer, rules, expected):
    mi = mapping_importer(rules=rules)
    assert mi.rules_as_dict == expected


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
def test_value_transformations_as_dict(mapping_importer, value_transformations, expected):
    mi = mapping_importer(value_transformations=value_transformations)
    assert mi.value_transformations_as_dict == expected


@pytest.mark.parametrize(
    ("value_transformations", "expected"),
    [
        # Empty lines should be skipped
        ("sex:M=MALE\n\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\n   \nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\n\t\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        # Lines without ":" or "=" should be skipped
        ("sex:M=MALE\ninvalid_line\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\nno_colon_or_equals\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        # Lines with ":" but no "=" in value_part should be skipped
        ("sex:M=MALE\nfield:value_without_equals\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
        ("sex:M=MALE\nfield:old_value\nsex:F=FEMALE", {"sex": {"M": "MALE", "F": "FEMALE"}}),
    ],
    ids=[
        "empty_line_newline",
        "empty_line_spaces",
        "empty_line_tab",
        "line_without_colon_or_equals",
        "line_without_colon_or_equals_2",
        "line_with_colon_no_equals_in_value",
        "line_with_colon_no_equals_in_value_2",
    ],
)
def test_value_transformations_as_dict_skips_invalid_lines(mapping_importer, value_transformations, expected):
    """Test that value_transformations_as_dict skips lines that trigger continue statements."""
    mi = mapping_importer(value_transformations=value_transformations)
    assert mi.value_transformations_as_dict == expected


@pytest.mark.parametrize(
    ("rules", "value_transformations", "data", "expected"),
    [
        # No transformations
        ("", "", {"gender": "M"}, {"gender": "M"}),
        # Only field mapping
        ("gender=sex", "", {"gender": "M"}, {"sex": "M"}),
        # Only value transformation
        ("", "gender:M=MALE", {"gender": "M"}, {"gender": "MALE"}),
        # Field mapping then value transformation
        ("gender=sex", "sex:M=MALE", {"gender": "M"}, {"sex": "MALE"}),
        # Multiple value transformations
        ("gender=sex", "sex:M=MALE\nsex:F=FEMALE", {"gender": "F"}, {"sex": "FEMALE"}),
        # Value transformation on non-mapped field
        ("gender=sex", "status:1=ACTIVE", {"gender": "M", "status": "1"}, {"sex": "M", "status": "ACTIVE"}),
        # Value that doesn't match transformation
        ("gender=sex", "sex:M=MALE", {"gender": "X"}, {"sex": "X"}),
        # Transformation rule exists but field_name not in data (field_name in data is False)
        ("", "missing_field:old=new", {"other_field": "value"}, {"other_field": "value"}),
        ("gender=sex", "missing_field:old=new", {"gender": "M"}, {"sex": "M"}),
    ],
    ids=[
        "no_transformations",
        "only_field_mapping",
        "only_value_transformation",
        "field_mapping_then_value",
        "multiple_value_transformations",
        "transformation_on_different_field",
        "value_no_match",
        "field_not_in_data",
        "field_not_in_data_with_mapping",
    ],
)
def test_apply_with_value_transformations(mapping_importer, rules, value_transformations, data, expected):
    mi = mapping_importer(rules=rules, value_transformations=value_transformations)
    result = mi.apply(data)
    assert result == expected
    assert result is data
