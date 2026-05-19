from collections.abc import Callable, Mapping, Iterable
from functools import reduce
from typing import Any

from django.utils import timezone

batch_name_default: Callable[[], str] = lambda: f"Batch {timezone.now()}"
rdi_name_default: Callable[[], str] = lambda: f"Push to HOPE {timezone.now()}"

Record = Mapping[str, Any]


TO_REMOVE_VALUES = "_h_c", "_h_f", "_i_c", "_i_f"
TO_UPPERCASE_FIELDS = "relationship", "gender", "residence_status", "consent_sharing"


def clean_field_name(v: str) -> str:
    """Normalize a field name by removing specific substrings (case-insensitive) and converting it to lowercase."""
    return reduce(lambda name, substr: name.replace(substr, ""), TO_REMOVE_VALUES, v.lower())


def clean_field_names(record: Record, fields_to_uppercase: Iterable[str] = TO_UPPERCASE_FIELDS) -> Record:
    """Clean all field names in a record by normalizing them."""
    return {clean_field_name(k): uppercase_field_value(k, v, fields_to_uppercase) for k, v in record.items()}


def uppercase_field_value(k: str, v: Any, fields_to_uppercase: Iterable[str] = TO_UPPERCASE_FIELDS) -> str:
    """Convert the given field value to uppercase if its name starts with specific prefixes."""
    return v.upper() if isinstance(v, str) and any(k.startswith(prefix) for prefix in fields_to_uppercase) else v


def to_reference_key(value: Any) -> str | None:
    """Return a stable string key for external references, ignoring empty and boolean values."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value).strip() or None
    if isinstance(value, str):
        return value.strip() or None
    return str(value).strip() or None
