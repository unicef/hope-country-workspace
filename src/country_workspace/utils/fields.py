from collections.abc import Callable, Mapping
from typing import Any
from functools import reduce

from django.utils import timezone
from hope_flex_fields.models import DataChecker

from country_workspace.utils.config import FailIfAlienConfig

batch_name_default: Callable[[], str] = lambda: f"Batch {timezone.now()}"
rdi_name_default: Callable[[], str] = lambda: f"RDI to HOPE {timezone.now()}"

Record = Mapping[str, Any]
RecordPreprocessor = Callable[[Record], Record]


def clean_field_name(v: str) -> str:
    """Normalize a field name by removing specific substrings (case-insensitive) and converting it to lowercase.

    Args:
        v (str): The original field name.

    Returns:
        str: The cleaned field name.

    """
    to_remove = ("_h_c", "_h_f", "_i_c", "_i_f")
    return reduce(lambda name, substr: name.replace(substr, ""), to_remove, v.lower())


class ExtraFieldInRecordError(Exception):
    def __init__(self, *fields: str) -> None:
        super().__init__(*fields)
        self.fields = fields

    def __str__(self) -> str:
        return f"Extra fields found: {', '.join(self.fields)}"


def create_json_record_preprocessor(config: FailIfAlienConfig, checker: DataChecker) -> Callable[[Record], Record]:
    if config["fail_if_alien"]:
        field_names = {field.name for _, field in checker.get_fields()}
    else:
        field_names = set()

    def preprocessor(record: Record) -> Record:
        cleaned_record = {clean_field_name(k): v for k, v in record.items()}

        if config["fail_if_alien"] and (extra_fields := cleaned_record.keys() - field_names):
            raise ExtraFieldInRecordError(*extra_fields)

        return cleaned_record

    return preprocessor


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
