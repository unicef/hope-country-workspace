import pytest
from hope_flex_fields.models import DataChecker, DataCheckerFieldset, Fieldset

from country_workspace.contrib.hope.constants import (
    INDIVIDUAL_BASE_FIELDSET_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.contrib.hope.latin_names import LATIN_NAME_FIELDS
from country_workspace.versioning.management.manager import Manager

# 0032 is the last script before this one whose `backward()` is known-broken (references a
# removed class), unrelated to this change. Discharging only down to it isolates this script's
# own forward/backward without hitting that pre-existing issue.
VERSION_BEFORE_THIS_SCRIPT = 32

EXPECTED_ATTRS = {
    "given_name_latin": {"label": "Given Name Latin", "required": False, "max_length": 150},
    "middle_name_latin": {"label": "Middle Name Latin", "required": False, "max_length": 150},
    "family_name_latin": {"label": "Family Name Latin", "required": False, "max_length": 150},
    "full_name_latin": {"label": "Full Name Latin", "required": False, "max_length": 500, "min_length": 2},
}


@pytest.mark.django_db
def test_forward_adds_optional_latin_fields_to_base_fieldset() -> None:
    Manager().forward()

    base_fs = Fieldset.objects.get(name=INDIVIDUAL_BASE_FIELDSET_NAME)
    field_names = set(base_fs.fields.values_list("name", flat=True))
    assert set(LATIN_NAME_FIELDS) <= field_names

    for field_name, expected_attrs in EXPECTED_ATTRS.items():
        flex_field = base_fs.fields.get(name=field_name)
        assert flex_field.attrs == expected_attrs


@pytest.mark.django_db
def test_forward_makes_fields_available_on_both_checkers() -> None:
    Manager().forward()

    base_fs = Fieldset.objects.get(name=INDIVIDUAL_BASE_FIELDSET_NAME)
    for checker_name in (INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME):
        checker = DataChecker.objects.get(name=checker_name)
        assert DataCheckerFieldset.objects.filter(checker=checker, fieldset=base_fs).exists()

        form_class = checker.get_form_class()
        assert set(LATIN_NAME_FIELDS) <= set(form_class.declared_fields.keys())


@pytest.mark.django_db
def test_forward_fields_are_optional_and_ascii_validated() -> None:
    Manager().forward()

    base_fs = Fieldset.objects.get(name=INDIVIDUAL_BASE_FIELDSET_NAME)
    full_name_latin_field = base_fs.fields.get(name="full_name_latin").get_field()

    assert full_name_latin_field.required is False
    assert full_name_latin_field.clean("") == ""
    assert full_name_latin_field.clean("O'Brien") == "O'Brien"

    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        full_name_latin_field.clean("Анна")


@pytest.mark.django_db
def test_backward_removes_latin_fields() -> None:
    m = Manager()
    m.forward()

    m.backward(VERSION_BEFORE_THIS_SCRIPT)

    base_fs = Fieldset.objects.get(name=INDIVIDUAL_BASE_FIELDSET_NAME)
    remaining = set(base_fs.fields.filter(name__in=LATIN_NAME_FIELDS).values_list("name", flat=True))
    assert remaining == set()
