import pytest
from django.core.exceptions import ValidationError

from country_workspace.validators.mapping import ValueTransformationRulesValidator


@pytest.fixture
def transformer():
    from tests.extras.testutils.factories import TransformerFactory

    return TransformerFactory


def test_value_transformation_validator_valid_js():
    validator = ValueTransformationRulesValidator()
    # Valid JS function
    validator("function transform(record) { return record; }")
    # Valid JS function expression assigned to const
    validator("const transform = function(record) { return record; }")


def test_value_transformation_validator_invalid_js():
    validator = ValueTransformationRulesValidator()

    # Not a function
    with pytest.raises(ValidationError, match="Invalid JavaScript code"):
        validator("var x = 1;")

    # Syntax error
    with pytest.raises(ValidationError, match="Invalid JavaScript code"):
        validator("function transform(record) { return record")


def test_value_transformation_validator_empty():
    validator = ValueTransformationRulesValidator()
    validator("")
    validator("   ")


@pytest.mark.parametrize(
    ("value_transformations", "data", "expected"),
    [
        # No transformations
        ("", {"gender": "M"}, {"gender": "M"}),
        # Simple transformation
        ("function t(d) { d['gender'] = 'MALE'; return d; }", {"gender": "M"}, {"gender": "MALE"}),
        # Transformation using logic
        (
            "function t(d) { if(d['gender']=='M') d['gender']='MALE'; else if(d['gender']=='F') d['gender']='FEMALE'; return d; }",  # noqa: E501
            {"gender": "F"},
            {"gender": "FEMALE"},
        ),
        # Transformation adding field
        (
            "function t(d) { d['new_field'] = 'new_value'; return d; }",
            {"existing": "value"},
            {"existing": "value", "new_field": "new_value"},
        ),
        # Transformation removing field (by not returning it? No, it modifies dict)
        # Javascript `delete` operator
        (
            "function t(d) { delete d['remove_me']; return d; }",
            {"keep_me": "val", "remove_me": "val"},
            {"keep_me": "val"},
        ),
    ],
    ids=[
        "no_transformations",
        "simple_transformation",
        "conditional_transformation",
        "add_field",
        "remove_field",
    ],
)
def test_apply(transformer, value_transformations, data, expected):
    t = transformer(value_transformations=value_transformations)
    result = t.apply(data)
    assert result == expected


def test_apply_handles_js_error(transformer, caplog):
    t = transformer(value_transformations="function t(d) { throw 'Error!'; }")
    data = {"foo": "bar"}

    with caplog.at_level("ERROR"):
        result = t.apply(data)

    assert result == data
    assert "Error applying value transformations" in caplog.text


def test_apply_handles_non_dict_return(transformer):
    """If JS returns a non-dict value, the raw result is returned."""
    t = transformer(value_transformations="function t(d) { return 'not a dict'; }")
    data = {"foo": "bar"}

    result = t.apply(data)
    assert result == "not a dict"


def test_apply_handles_null_return(transformer):
    """If JS returns null, the raw None is returned."""
    t = transformer(value_transformations="function t(d) { return null; }")
    data = {"foo": "bar"}

    result = t.apply(data)
    assert result is None
