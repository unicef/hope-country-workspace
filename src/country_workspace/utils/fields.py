from collections.abc import Callable, Mapping
from functools import reduce
from typing import Any

from django.utils import timezone

batch_name_default: Callable[[], str] = lambda: f"Batch {timezone.now()}"
rdi_name_default: Callable[[], str] = lambda: f"RDI to HOPE {timezone.now()}"

Record = Mapping[str, Any]


TO_REMOVE = "_h_c", "_h_f", "_i_c", "_i_f"
TO_UPPERCASE = "relationship", "gender", "disability", "residence_status"


def clean_field_name(v: str) -> str:
    """Normalize a field name by removing specific substrings (case-insensitive) and converting it to lowercase.

    Args:
        v (str): The original field name.

    Returns:
        str: The cleaned field name.

    """
    return reduce(lambda name, substr: name.replace(substr, ""), TO_REMOVE, v.lower())


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
    return v.upper() if isinstance(v, str) and any(k.startswith(prefix) for prefix in TO_UPPERCASE) else v
