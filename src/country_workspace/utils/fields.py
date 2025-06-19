import binascii
from collections.abc import Callable, Mapping
from functools import reduce
from typing import Any
from base64 import b64decode
from uuid import UUID

from django.utils import timezone

batch_name_default: Callable[[], str] = lambda: f"Batch {timezone.now()}"
rdi_name_default: Callable[[], str] = lambda: f"Push to HOPE {timezone.now()}"

Record = Mapping[str, Any]


TO_REMOVE_VALUES = "_h_c", "_h_f", "_i_c", "_i_f"
TO_UPPERCASE_FIELDS = "relationship", "gender", "residence_status"
TO_MAP_FIELDS = {"gender": "sex"}


def clean_field_name(v: str) -> str:
    """Normalize a field name by removing specific substrings (case-insensitive) and converting it to lowercase.

    Args:
        v (str): The original field name.

    Returns:
        str: The cleaned field name.

    """
    return reduce(lambda name, substr: name.replace(substr, ""), TO_REMOVE_VALUES, v.lower())


def clean_field_names(record: Record) -> Record:
    """Clean all field names in a record by normalizing them.

    Args:
        record (dict): A dictionary with field names as keys and their values.

    Returns:
        dict: A new dictionary with cleaned field names and original values.

    """
    return {clean_field_name(k): uppercase_field_value(k, v) for k, v in record.items()}


def uppercase_field_value(k: str, v: Any) -> str:
    """
    Convert the given field value to uppercase if its name starts with specific prefixes.

    Args:
        k (str): The name of the field.
        v (Any): The value associated with the field.

    Returns:
        str: The uppercase value if applicable or the original value.

    """
    return v.upper() if isinstance(v, str) and any(k.startswith(prefix) for prefix in TO_UPPERCASE_FIELDS) else v


def map_fields(fields: dict[str, str]) -> dict[str, str]:
    """
    Map keys in a dictionary to alternative names based on a predefined mapping.

    Args:
        fields (dict[str, str]): A dictionary containing field names as keys and their values.

    Returns:
        dict[str, str]: A new dictionary with keys mapped according to the predefined mapping.

    """
    return {TO_MAP_FIELDS.get(k, k): v for k, v in fields.items() if v is not None}


def extract_uuid(value: str, prefix: str | None = None) -> UUID:
    """Extract a UUID from the given string.

    - If `value` is already a UUID, returns it unchanged.
    - Otherwise attempts Base64-decoding and stripping an optional `prefix`.

    """
    if not isinstance(value, str):
        raise TypeError("value must be a str")
    if prefix is not None and not isinstance(prefix, str):
        raise TypeError("prefix must be a str or None")

    try:
        return UUID(value)
    except ValueError:
        pass

    try:
        decoded = b64decode(value, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError):
        raise ValueError(f"value is neither a valid UUID nor valid Base64: {value!r}")

    raw = decoded.removeprefix(prefix or "")
    try:
        return UUID(raw)
    except ValueError:
        raise ValueError(f"decoded data is not a valid UUID: {raw!r}")
