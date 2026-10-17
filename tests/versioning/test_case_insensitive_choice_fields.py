from importlib import import_module

import pytest
from django import forms
from hope_flex_fields.models import DataChecker, FieldDefinition

from country_workspace.contrib.hope.constants import INDIVIDUAL_CHECKER_NAME
from country_workspace.contrib.hope.required_choice_field import ChoiceFieldWithEmptyDisplay
from country_workspace.utils.flex_fields import (
    CaseInsensitiveChoiceField,
    CaseInsensitiveChoiceFieldWithEmptyDisplay,
)
from country_workspace.versioning.management.manager import Manager

script = import_module("country_workspace.versioning.scripts.0034_case_insensitive_choice_fields")

VERSION_BEFORE_THIS_SCRIPT = 33


def _field_types(names: list[str]) -> dict[str, type]:
    return {fd.name: fd.field_type for fd in FieldDefinition.objects.filter(name__in=names)}


@pytest.mark.django_db
def test_forward_switches_field_types() -> None:
    Manager().forward()

    assert _field_types(script.CHOICE_FIELDS) == dict.fromkeys(script.CHOICE_FIELDS, CaseInsensitiveChoiceField)
    assert _field_types(script.CHOICE_FIELDS_WITH_EMPTY_DISPLAY) == dict.fromkeys(
        script.CHOICE_FIELDS_WITH_EMPTY_DISPLAY, CaseInsensitiveChoiceFieldWithEmptyDisplay
    )


@pytest.mark.django_db
def test_forward_checker_returns_choice_keys() -> None:
    Manager().forward()

    checker = DataChecker.objects.get(name=INDIVIDUAL_CHECKER_NAME)
    checker.validate([{"seeing_disability": "some_difficulty", "disability": "DISABLED"}])

    assert checker.form.cleaned_data["seeing_disability"] == "SOME_DIFFICULTY"
    assert checker.form.cleaned_data["disability"] == "disabled"


@pytest.mark.django_db
def test_backward_restores_field_types() -> None:
    m = Manager()
    m.forward()

    m.backward(VERSION_BEFORE_THIS_SCRIPT)

    assert _field_types(script.CHOICE_FIELDS) == dict.fromkeys(script.CHOICE_FIELDS, forms.ChoiceField)
    assert _field_types(script.CHOICE_FIELDS_WITH_EMPTY_DISPLAY) == dict.fromkeys(
        script.CHOICE_FIELDS_WITH_EMPTY_DISPLAY, ChoiceFieldWithEmptyDisplay
    )
