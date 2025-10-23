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
        assert result == f"+{number[2:]}"


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


def test_invalid_phone_number_format():
    field = PhoneNumberField()

    # Numbers that should fail format validation
    invalid_format_numbers = [
        "123",  # Too short, no country code
        "+",  # Just plus sign
        "+99",  # Too short after plus
        "abc123",  # Contains letters
        "123-abc-456",  # Contains letters
    ]

    for number in invalid_format_numbers:
        with pytest.raises(ValidationError, match="Invalid phone number format."):
            field.clean(number)


def test_invalid_phone_number_validity():
    field = PhoneNumberField()

    # Numbers that pass format but fail validity
    invalid_validity_numbers = [
        "+123456789012345",  # Too long international number
    ]

    for number in invalid_validity_numbers:
        with pytest.raises(ValidationError, match="Invalid phone number."):
            field.clean(number)


def test_edge_cases():
    field = PhoneNumberField()

    # These should fail format validation
    with pytest.raises(ValidationError, match="Invalid phone number format."):
        field.clean("1")

    with pytest.raises(ValidationError, match="Invalid phone number format."):
        field.clean("0000000000")

    with pytest.raises(ValidationError, match="Invalid phone number format."):
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
    assert result == "+12345678901"
