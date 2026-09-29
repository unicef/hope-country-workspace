import pytest
from django.core.exceptions import ValidationError

from country_workspace.contrib.hope.latin_names import LatinNameField, normalize_latin_name


@pytest.mark.parametrize(
    "value",
    [
        "John",
        "O'Brien",
        "Anna-Maria",
        "Jean Paul",
        "D'Angelo Smith-Jones",
    ],
)
def test_valid_names(value: str) -> None:
    field = LatinNameField(required=False)
    assert field.clean(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "-Anna",  # cannot start with a separator
        "Anna-",  # cannot end with a separator
        "John123",  # digits not allowed
        "Анна",  # non-ASCII / Cyrillic
        "أحمد",  # non-ASCII / Arabic
        "John#Doe",  # disallowed symbol
        "John--Doe",  # repeated separators
    ],
)
def test_invalid_names(value: str) -> None:
    field = LatinNameField(required=False)
    with pytest.raises(ValidationError, match=r"Only ASCII letters, spaces, hyphens, and apostrophes are allowed."):
        field.clean(value)


def test_empty_value_is_allowed_when_not_required() -> None:
    field = LatinNameField(required=False)
    assert field.clean("") == ""
    assert field.clean(None) == ""


def test_required_field_rejects_empty_value() -> None:
    field = LatinNameField(required=True)
    with pytest.raises(ValidationError):
        field.clean("")


def test_whitespace_is_collapsed_and_stripped() -> None:
    field = LatinNameField(required=False)
    assert field.clean("  John   Paul  ") == "John Paul"


def test_normalize_latin_name() -> None:
    assert normalize_latin_name("  John   Paul  ") == "John Paul"
    assert normalize_latin_name("") == ""
    assert normalize_latin_name(None) is None
