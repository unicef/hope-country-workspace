import pytest
from django.core.exceptions import ValidationError

from country_workspace.validators.mapping import FieldMappingRulesValidator


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
        ("gender=sex\n\nage=birth_year", {"gender": "sex", "age": "birth_year"}),
        (
            "field1=mapped1\nfield2=mapped2\nfield3=mapped3",
            {"field1": "mapped1", "field2": "mapped2", "field3": "mapped3"},
        ),
    ],
    ids=["empty_rules", "single_rule", "multiple_rules", "blank_line", "three_rules"],
)
def test_rules_as_dict(mapping_importer, rules, expected):
    mi = mapping_importer(rules=rules)
    assert mi.rules_as_dict == expected


@pytest.mark.parametrize(
    ("rules", "value_transformations", "data", "expected"),
    [
        # No transformations
        ("", "", {"gender": "M"}, {"gender": "M"}),
        # Only field mapping
        ("gender=sex", "", {"gender": "M"}, {"sex": "M"}),
        # Field mapping then value transformation (using separate Transformer)
        ("gender=sex", "sex:M=MALE", {"gender": "M"}, {"sex": "M"}),
        # Multiple value transformations (using separate Transformer)
        ("gender=sex", "sex:M=MALE\nsex:F=FEMALE", {"gender": "F"}, {"sex": "F"}),
        # Value transformation on non-mapped field (using separate Transformer)
        ("gender=sex", "status:1=ACTIVE", {"gender": "M", "status": "1"}, {"sex": "M", "status": "ACTIVE"}),
        # Value that doesn't match transformation (using separate Transformer)
        ("gender=sex", "sex:M=MALE", {"gender": "X"}, {"sex": "X"}),
        # Transformation rule exists but field_name not in data (using separate Transformer)
        ("gender=sex", "missing_field:old=new", {"gender": "M"}, {"sex": "M"}),
    ],
    ids=[
        "no_transformations",
        "only_field_mapping",
        "field_mapping_then_value",
        "multiple_value_transformations",
        "transformation_on_different_field",
        "value_no_match",
        "field_not_in_data_with_mapping",
    ],
)
def test_apply_with_transformer(mapping_importer, rules, value_transformations, data, expected):
    """Test that MappingImporter can work with Transformer for value transformations.

    Flow: INPUT -> MAPPER (field mapping) -> TRANSFORMER (value transformation)
    """
    from testutils.factories import TransformerFactory

    mi = mapping_importer(rules=rules)
    # Step 1: Apply mapping first (field-level)
    result = mi.apply(data)

    # Step 2: Apply transformer if value_transformations are provided (record-level)
    if value_transformations:
        transformer = TransformerFactory(value_transformations=value_transformations)
        result = transformer.apply(result)

    assert result == expected
    assert result is data
