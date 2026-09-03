import json
from types import SimpleNamespace

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


def test_get_approved_ona_forms_rejects_invalid_json(monkeypatch) -> None:
    _set_raw_approved_forms(monkeypatch, "{invalid-json")

    with pytest.raises(forms.ValidationError, match="valid JSON"):
        get_approved_ona_forms()


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


def test_import_ona_form_uses_choice_field() -> None:
    assert isinstance(ImportOnaForm.base_fields["form_id"], forms.ChoiceField)
