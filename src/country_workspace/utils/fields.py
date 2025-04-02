from collections.abc import Callable, Mapping
from functools import reduce
from typing import Any

from django.utils import timezone

batch_name_default: Callable[[], str] = lambda: f"Batch {timezone.now()}"
rdi_name_default: Callable[[], str] = lambda: f"RDI to HOPE {timezone.now()}"

Record = Mapping[str, Any]


TO_REMOVE = "_h_c", "_h_f", "_i_c", "_i_f"


def clean_field_name(v: str) -> str:
    """Normalize a field name by removing specific substrings (case-insensitive) and converting it to lowercase.

    Args:
        v (str): The original field name.

    Returns:
        str: The cleaned field name.

    """
    return reduce(lambda name, substr: name.replace(substr, ""), TO_REMOVE, v.lower())


def clean_field_names(record: Record) -> Record:
    return {clean_field_name(k): v for k, v in record.items()}


def uppercase_field_value(k: str, v: Any) -> str:
    """
    Convert the given field value to uppercase if applicable.

    Args:
        k (str): The name of the field.
        v (Any): The value associated with the field.

    Returns:
        str: The uppercase value if applicable or the original value.

    """
    to_uppercase = ("relationship", "gender", "disability", "residence_status")
    return v.upper() if isinstance(v, str) and k in to_uppercase else v
