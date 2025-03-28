from unittest.mock import MagicMock

import pytest

from country_workspace.utils.fields import (
    clean_field_name,
    TO_REMOVE,
    ExtraFieldInRecordError,
    create_json_record_preprocessor,
)


@pytest.mark.parametrize(
    ("input_value", "expected_output"),
    [(f"field{substr}_foo", "field_foo") for substr in TO_REMOVE]
    + [(f"FIELD{substr.upper()}_foo", "field_foo") for substr in TO_REMOVE]
    + [
        ("field_foo", "field_foo"),
    ],
)
def test_clean_field_name(input_value, expected_output):
    assert clean_field_name(input_value) == expected_output


def test_extra_field_in_record_error_format() -> None:
    assert ", ".join(extra_fields := ("a", "b", "c")) in str(ExtraFieldInRecordError(*extra_fields))


def test_create_json_record_preprocessor_raises_on_extra_fields() -> None:
    config = {
        "fail_if_alien": True,
    }
    checker = MagicMock()
    preprocessor = create_json_record_preprocessor(config, checker)

    with pytest.raises(ExtraFieldInRecordError):
        preprocessor({"foo": "bar"})
