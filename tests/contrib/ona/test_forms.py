import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from django import forms

from country_workspace.contrib.ona import forms as ona_forms
from country_workspace.contrib.ona.forms import (
    ImportOnaForm,
    get_allowed_ona_form_choices,
    get_approved_ona_forms,
    is_ona_form_allowed,
)


@pytest.fixture
def program():
    country_office = SimpleNamespace(
        pk=1,
        id=1,
        name="Yemen CO",
        code="YE",
        kobo_country_code="YE",
    )
    return SimpleNamespace(
        pk=10,
        id=10,
        name="IDP",
        code="IDP",
        slug="idp",
        country_office=country_office,
    )


def _set_approved_forms(monkeypatch, value: dict) -> None:
    monkeypatch.setattr(
        ona_forms,
        "constance_config",
        SimpleNamespace(ONA_APPROVED_FORMS=json.dumps(value)),
    )


def _set_raw_approved_forms(monkeypatch, value: str) -> None:
    monkeypatch.setattr(
        ona_forms,
        "constance_config",
        SimpleNamespace(ONA_APPROVED_FORMS=value),
    )


def test_get_approved_ona_forms_reads_json_mapping(monkeypatch) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )

    assert get_approved_ona_forms() == {
        "9153": {
            "label": "Yemen INFORM Registration",
            "programmes": ["IDP"],
            "offices": ["Yemen CO"],
        }
    }


def test_get_approved_ona_forms_returns_empty_mapping_for_invalid_json(monkeypatch) -> None:
    _set_raw_approved_forms(monkeypatch, "{invalid-json")

    assert get_approved_ona_forms() == {}


def test_get_approved_ona_forms_returns_empty_mapping_for_non_object(monkeypatch) -> None:
    _set_raw_approved_forms(monkeypatch, '["9153"]')

    assert get_approved_ona_forms() == {}


def test_ona_form_is_allowed_when_programme_and_office_match(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )

    assert is_ona_form_allowed("9153", program)


def test_ona_form_is_blocked_when_programme_does_not_match(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["WASH"],
                "offices": ["Yemen CO"],
            }
        },
    )

    assert not is_ona_form_allowed("9153", program)


def test_ona_form_is_blocked_when_office_does_not_match(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["IDP"],
                "offices": ["Jordan CO"],
            }
        },
    )

    assert not is_ona_form_allowed("9153", program)


def test_ona_form_without_programme_or_office_mapping_fails_closed(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
            }
        },
    )

    assert not is_ona_form_allowed("9153", program)


def test_ona_form_matches_scalar_and_non_list_identifiers(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "programmes": "IDP",
                "offices": ("Yemen CO",),
            },
            "9154": {
                "programmes": 10,
                "offices": "YE",
            },
        },
    )

    assert is_ona_form_allowed("9153", program)
    assert is_ona_form_allowed("9154", program)


def test_ona_form_is_allowed_when_only_programme_or_only_office_matches(monkeypatch, program) -> None:
    _set_approved_forms(monkeypatch, {"9153": {"programmes": ["IDP"]}})
    assert is_ona_form_allowed("9153", program)

    _set_approved_forms(monkeypatch, {"9153": {"offices": ["YE"]}})
    assert is_ona_form_allowed("9153", program)


def test_ona_form_is_blocked_without_program_office_or_config(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )

    assert not is_ona_form_allowed("missing", program)
    assert not is_ona_form_allowed("9153", None)

    program_without_office = SimpleNamespace(
        pk=10,
        id=10,
        name="IDP",
        code="IDP",
        slug="idp",
        country_office=None,
    )
    assert not is_ona_form_allowed("9153", program_without_office)


def test_get_approved_ona_forms_treats_blank_config_as_empty(monkeypatch) -> None:
    _set_raw_approved_forms(monkeypatch, "")

    assert get_approved_ona_forms() == {}


def test_allowed_ona_form_choices_only_include_forms_allowed_for_program(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            },
            "9200": {
                "label": "Other Programme Registration",
                "programmes": ["WASH"],
                "offices": ["Yemen CO"],
            },
        },
    )

    assert get_allowed_ona_form_choices(program) == [
        ("9153", "Yemen INFORM Registration (9153)"),
    ]


def test_allowed_choices_skip_invalid_entries_and_fall_back_to_form_id(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "bad": "nope",
            "9153": {
                "programmes": ["IDP"],
                "offices": ["YE"],
            },
        },
    )

    assert get_allowed_ona_form_choices(program) == [("9153", "9153 (9153)")]


def test_import_ona_form_uses_choice_field() -> None:
    assert isinstance(ImportOnaForm.base_fields["form_id"], forms.ChoiceField)


def test_import_ona_form_errors_when_no_forms_are_approved(monkeypatch) -> None:
    _set_raw_approved_forms(monkeypatch, "{}")

    form = ImportOnaForm(program=None)

    assert form.non_field_errors() == ["No ONA / INFORM forms are approved for this office/programme."]


def test_import_ona_form_lists_allowed_choices(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "label": "Yemen INFORM Registration",
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )
    program.household_checker = None
    program.individual_checker = None
    program.beneficiary_group = None
    monkeypatch.setattr(
        "country_workspace.models.Transformer.objects.filter",
        lambda *args, **kwargs: MagicMock(),
    )

    form = ImportOnaForm(program=program)

    assert list(form.fields["form_id"].choices) == [("9153", "Yemen INFORM Registration (9153)")]
    assert not form.non_field_errors()


def test_clean_form_id_returns_approved_form(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )
    form = ImportOnaForm(program=None)
    form.program = program
    form.cleaned_data = {"form_id": "9153"}

    assert form.clean_form_id() == "9153"


def test_clean_form_id_rejects_unapproved_form(monkeypatch, program) -> None:
    _set_approved_forms(
        monkeypatch,
        {
            "9153": {
                "programmes": ["IDP"],
                "offices": ["Yemen CO"],
            }
        },
    )
    form = ImportOnaForm(program=None)
    form.program = program
    form.cleaned_data = {"form_id": "0000"}

    with pytest.raises(forms.ValidationError, match="not approved"):
        form.clean_form_id()
