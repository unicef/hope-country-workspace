import phonenumbers

from typing import Any


def is_right_phone_number_format(phone_number: str | Any) -> tuple[bool, str | None]:
    # from phonenumbers.parse method description:
    # This method will throw a NumberParseException if the number is not
    # considered to be a possible number.
    #
    # so if `parse` does not throw, we may assume it's ok
    if not isinstance(phone_number, str):  # pragma: no cover
        phone_number = str(phone_number)

    phone_number = phone_number.strip()
    if phone_number.startswith("00"):
        phone_number = f"+{phone_number[2:]}"

    try:
        phonenumbers.parse(phone_number)
    except phonenumbers.NumberParseException:
        return False, None

    return True, phone_number


def is_valid_phone_number(phone_number: Any) -> bool:  # pragma: no cover
    if not isinstance(phone_number, str):
        phone_number = str(phone_number)

    try:
        parsed_number = phonenumbers.parse(phone_number)
    except phonenumbers.NumberParseException:
        return False
    else:
        return phonenumbers.is_valid_number(parsed_number)
