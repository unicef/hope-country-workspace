import pytest
from django.core.exceptions import ValidationError

from country_workspace.contrib.hope.phone_numbers import PhoneNumberField


def test_valid_international_format_with_plus():
    field = PhoneNumberField()

    valid_numbers = [
        "+12345678901",  # US number (10 digits)
        "+442071234567",  # UK number
        "+33123456789",  # French number
        "+61412345678",  # Australian number
        "+123456789012345",  # Long international number
    ]

    for number in valid_numbers:
        result = field.clean(number)
        assert result == number


def test_valid_international_format_with_00_prefix():
    field = PhoneNumberField()

    valid_numbers = [
        "0012345678901",  # US number with 00
        "00442071234567",  # UK number with 00
        "0033123456789",  # French number with 00
    ]

    for number in valid_numbers:
        result = field.clean(number)
        assert result == number


def test_empty_value():
    field = PhoneNumberField(required=False)

    result = field.clean("")
    assert result == ""

    result = field.clean(None)
    assert result == ""


def test_whitespace_handling():
    field = PhoneNumberField()

    result = field.clean("  +12345678901  ")
    assert result == "+12345678901"

    result = field.clean("+1 234 567 8901")
    assert result == "+1 234 567 8901"


def test_invalid_phone_numbers():
    field = PhoneNumberField()

    invalid_numbers = [
        "123",
        "+",
        "+99",
    ]

    for number in invalid_numbers:
        with pytest.raises(ValidationError, match="Invalid phone number"):
            field.clean(number)


def test_edge_cases():
    field = PhoneNumberField()

    with pytest.raises(ValidationError, match="Invalid phone number"):
        field.clean("1")

    with pytest.raises(ValidationError, match="Invalid phone number"):
        field.clean("0000000000")

    with pytest.raises(ValidationError, match="Invalid phone number"):
        field.clean("123abc456")


def test_required_field_validation():
    field = PhoneNumberField(required=True)

    with pytest.raises(ValidationError):
        field.clean("")

    with pytest.raises(ValidationError):
        field.clean(None)


def test_field_inheritance():
    field = PhoneNumberField(max_length=20)

    long_number = "123456789012345678901234567890"
    with pytest.raises(ValidationError):
        field.clean(long_number)

    valid_number = "+12345678901"
    result = field.clean(valid_number)
    assert result == valid_number


def test_00_prefix_conversion_logic():
    field = PhoneNumberField()

    result = field.clean("0012345678901")
    assert result == "0012345678901"

    result = field.clean("00 123 456 7890")
    assert result == "00 123 456 7890"
