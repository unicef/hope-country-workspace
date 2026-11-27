import pytest
from django import forms
from hope_flex_fields.fields import IdentityField
from hope_flex_fields.models import DataChecker
from testutils.factories import DataCheckerFactory

from country_workspace.contrib.hope.phone_numbers import PhoneNumberField
from country_workspace.utils.flex_fields import normalize_field_types
from country_workspace.utils.import_flow.normalization import get_normalizable_field_types


pytestmark = pytest.mark.django_db


PROTECTED_VALUES = {
    "household_id": 42.0,
    "individual_id": 42.0,
    "index_id": 42.0,
    "collector_id": 42,
    "relationship": 42,
    "role": 42,
    "head_of_household_id": 42,
    "primary_collector_id": 42,
    "alternate_collector_id": 42,
    "head_of_household": 42,
    "primary_collector": 42,
    "alternate_collector": 42,
}


@pytest.fixture
def checker() -> DataChecker:
    return DataCheckerFactory(
        fields=[
            *((name, forms.CharField) for name in PROTECTED_VALUES),
            ("uid", IdentityField),
            ("phone_no", PhoneNumberField),
            ("document_id", forms.CharField),
        ],
    )


def test_get_normalizable_field_types(checker: DataChecker) -> None:
    assert get_normalizable_field_types(checker) == {
        "phone_no": PhoneNumberField,
        "document_id": forms.CharField,
    }


def test_get_normalizable_field_types_without_checker() -> None:
    assert get_normalizable_field_types(None) == {}


def test_normalization_preserves_protected_values(checker: DataChecker) -> None:
    data = {
        **PROTECTED_VALUES,
        "uid": 0,
        "phone_no": 9328772,
        "document_id": 123,
    }

    assert normalize_field_types(data, get_normalizable_field_types(checker)) == {
        **PROTECTED_VALUES,
        "uid": 0,
        "phone_no": "9328772",
        "document_id": "123",
    }
