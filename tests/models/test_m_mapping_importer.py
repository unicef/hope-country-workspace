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


def test_apply_logs_exception(mapping_importer, caplog, mocker):
    mi = mapping_importer(rules="gender=sex")
    mocker.patch.object(type(mi), "rules_as_dict", new_callable=mocker.PropertyMock, side_effect=RuntimeError("boom"))
    data = {"gender": "M"}

    with caplog.at_level("ERROR"):
        result = mi.apply(data)

    assert "Error applying mapping rules" in caplog.text
    assert result == data
