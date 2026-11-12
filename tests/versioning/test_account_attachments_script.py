from importlib import import_module

import pytest
from hope_flex_fields.models import DataChecker, DataCheckerFieldset, Fieldset

from country_workspace.contrib.hope.account_attachments import AccountAttachmentsField
from country_workspace.contrib.hope.constants import (
    ACCOUNT_FIELDSET_NAME,
    INDIVIDUAL_CHECKER_NAME,
    PEOPLE_CHECKER_NAME,
)
from country_workspace.versioning.management.manager import Manager

VERSION_BEFORE_THIS_SCRIPT = 35
REFERENCE = "flexfile:00000000-0000-0000-0000-000000000001"


def account_prefixes(checker_name: str) -> set[str]:
    return set(
        DataCheckerFieldset.objects.filter(
            checker__name=checker_name, fieldset__name=ACCOUNT_FIELDSET_NAME
        ).values_list("prefix", flat=True)
    )


@pytest.mark.django_db
def test_forward_adds_attachments_to_the_account_fieldset() -> None:
    Manager().forward()

    field = Fieldset.objects.get(name=ACCOUNT_FIELDSET_NAME).fields.get(name="attachments")
    assert field.definition.field_type is AccountAttachmentsField
    assert field.attrs["required"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("checker_name", [INDIVIDUAL_CHECKER_NAME, PEOPLE_CHECKER_NAME])
def test_forward_lets_individuals_and_people_carry_account_attachments(checker_name: str) -> None:
    Manager().forward()

    assert {"bank_", "mobile_"} <= account_prefixes(checker_name)
    checker = DataChecker.objects.get(name=checker_name)
    form_field = checker.get_form_class().declared_fields["bank_attachments"]
    assert isinstance(form_field, AccountAttachmentsField)
    assert form_field.clean([{"file": REFERENCE}]) == [{"file": REFERENCE, "title": ""}]


@pytest.mark.django_db
def test_people_checker_gets_the_prefixes_of_the_individual_checker() -> None:
    Manager().forward()

    assert account_prefixes(PEOPLE_CHECKER_NAME) == account_prefixes(INDIVIDUAL_CHECKER_NAME)


@pytest.mark.django_db
def test_forward_is_idempotent() -> None:
    Manager().forward()
    prefixes = account_prefixes(PEOPLE_CHECKER_NAME)

    import_module("country_workspace.versioning.scripts.0036_add_account_attachments").forward()

    assert account_prefixes(PEOPLE_CHECKER_NAME) == prefixes
    assert Fieldset.objects.get(name=ACCOUNT_FIELDSET_NAME).fields.filter(name="attachments").count() == 1


@pytest.mark.django_db
def test_backward_removes_attachments_and_people_accounts() -> None:
    m = Manager()
    m.forward()

    m.backward(VERSION_BEFORE_THIS_SCRIPT)

    assert not Fieldset.objects.get(name=ACCOUNT_FIELDSET_NAME).fields.filter(name="attachments").exists()
    assert account_prefixes(PEOPLE_CHECKER_NAME) == set()
    assert account_prefixes(INDIVIDUAL_CHECKER_NAME)
