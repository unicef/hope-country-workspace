import pytest
from django.core.exceptions import ValidationError

from country_workspace.validators.mapping import FieldMappingRulesValidator


@pytest.fixture
def mapping_importer():
    from testutils.factories.mapping_importer import MappingImporterFactory

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


def test_apply_failure(mapping_importer):
    mi = mapping_importer(rules="invalid_rule")
    with pytest.raises(ValidationError):
        mi.apply({"gender": "MALE"})
