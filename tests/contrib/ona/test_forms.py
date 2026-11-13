from types import SimpleNamespace

import pytest
import responses
from django import forms
from django.core.cache.backends.locmem import LocMemCache
from requests import ConnectionError as RequestsConnectionError

from country_workspace.contrib.ona import forms as ona_forms
from country_workspace.contrib.ona.forms import ImportOnaForm, get_ona_form_choices

ONA_API_URL = "https://data.inform.unicef.org"
FORMS_URL = f"{ONA_API_URL}/api/v1/forms"


@pytest.fixture(autouse=True)
def ona_settings(monkeypatch) -> SimpleNamespace:
    settings = SimpleNamespace(ONA_API_URL=ONA_API_URL, ONA_API_TOKEN="t")
    monkeypatch.setattr(ona_forms, "constance_config", settings)
    cache = LocMemCache("ona-form-choices-tests", {})
    cache.clear()
    monkeypatch.setattr(ona_forms, "cache", cache)
    return settings


def test_import_ona_form_uses_choice_field() -> None:
    assert isinstance(ImportOnaForm.base_fields["form_id"], forms.ChoiceField)


def test_import_ona_form_defaults_individuals_key_to_individual_questions() -> None:
    assert ImportOnaForm.base_fields["individuals_key"].initial == "individual_questions"


@responses.activate
def test_get_ona_form_choices_lists_downloadable_forms() -> None:
    responses.get(
        FORMS_URL,
        json=[
            {"formid": 13591, "title": "Registration_template_October_2026", "downloadable": True},
            {"formid": 13592, "title": "Closed form", "downloadable": False},
            {"formid": 14000, "title": "", "downloadable": True},
        ],
    )

    assert get_ona_form_choices() == [
        ("13591", "Registration_template_October_2026 (13591)"),
        ("14000", "14000 (14000)"),
    ]
    assert responses.calls[0].request.headers["Authorization"] == "Token t"


@responses.activate
def test_get_ona_form_choices_are_cached() -> None:
    responses.get(FORMS_URL, json=[{"formid": 1, "title": "Form", "downloadable": True}])

    assert get_ona_form_choices() == get_ona_form_choices() == [("1", "Form (1)")]
    assert len(responses.calls) == 1


@responses.activate
def test_import_ona_form_lists_available_forms() -> None:
    responses.get(FORMS_URL, json=[{"formid": 13591, "title": "Registration", "downloadable": True}])

    form = ImportOnaForm(program=None)

    assert list(form.fields["form_id"].choices) == [("13591", "Registration (13591)")]
    assert not form.non_field_errors()


def test_import_ona_form_requires_api_token(ona_settings: SimpleNamespace) -> None:
    ona_settings.ONA_API_TOKEN = ""

    form = ImportOnaForm(program=None)

    assert form.non_field_errors() == ["Please set ONA_API_TOKEN to use ONA / INFORM import"]


@responses.activate
def test_import_ona_form_reports_when_no_forms_are_available() -> None:
    responses.get(FORMS_URL, json=[])

    form = ImportOnaForm(program=None)

    assert form.non_field_errors() == ["No ONA / INFORM forms are available."]


@pytest.mark.parametrize(
    "response",
    [{"status": 401}, {"status": 500}, {"body": RequestsConnectionError("down")}],
    ids=["unauthorized", "server-error", "connection-error"],
)
@responses.activate
def test_import_ona_form_reports_unavailable_api(response: dict) -> None:
    responses.get(FORMS_URL, **response)

    form = ImportOnaForm(program=None)

    assert form.non_field_errors() == ["Could not load ONA / INFORM forms. Please try again later."]


@responses.activate
def test_import_ona_form_rejects_unlisted_form() -> None:
    responses.get(FORMS_URL, json=[{"formid": 13591, "title": "Registration", "downloadable": True}])

    form = ImportOnaForm({"ona-form_id": "99999"}, prefix="ona", program=None)

    assert not form.is_valid()
    assert "form_id" in form.errors
