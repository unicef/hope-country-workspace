import json
from typing import Any

from constance import config as constance_config
from django import forms

from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple | set):
        return [str(item) for item in value]
    return [str(value)]


def _normalise(value: Any) -> str:
    return str(value).strip().lower()


def _matches_any(allowed_values: list[str], actual_values: set[str]) -> bool:
    return any(_normalise(value) in actual_values for value in allowed_values)


def _program_identifiers(program: Program | None) -> set[str]:
    if not program:
        return set()

    values = {
        getattr(program, "pk", None),
        getattr(program, "id", None),
        getattr(program, "name", None),
        getattr(program, "slug", None),
        getattr(program, "code", None),
    }
    return {_normalise(value) for value in values if value is not None}


def _office_identifiers(program: Program | None) -> set[str]:
    if not program:
        return set()

    country_office = getattr(program, "country_office", None)
    if not country_office:
        return set()

    values = {
        getattr(country_office, "pk", None),
        getattr(country_office, "id", None),
        getattr(country_office, "name", None),
        getattr(country_office, "slug", None),
        getattr(country_office, "code", None),
        getattr(country_office, "kobo_country_code", None),
    }
    return {_normalise(value) for value in values if value is not None}


def get_approved_ona_forms() -> dict[str, dict[str, Any]]:
    raw_config = getattr(constance_config, "ONA_APPROVED_FORMS", "") or "{}"

    try:
        parsed_config = json.loads(raw_config)
    except json.JSONDecodeError as exc:
        raise forms.ValidationError("ONA_APPROVED_FORMS must be valid JSON.") from exc

    if not isinstance(parsed_config, dict):
        raise forms.ValidationError("ONA_APPROVED_FORMS must be a JSON object.")

    return {str(form_id): config for form_id, config in parsed_config.items() if isinstance(config, dict)}


def is_ona_form_allowed(form_id: str, program: Program | None = None) -> bool:
    approved_forms = get_approved_ona_forms()
    form_config = approved_forms.get(str(form_id))

    if not form_config:
        return False

    allowed_programmes = _as_list(form_config.get("programmes"))
    allowed_offices = _as_list(form_config.get("offices"))

    if not allowed_programmes and not allowed_offices:
        return False

    program_match = not allowed_programmes or _matches_any(allowed_programmes, _program_identifiers(program))
    office_match = not allowed_offices or _matches_any(allowed_offices, _office_identifiers(program))

    return program_match and office_match


def get_allowed_ona_form_choices(program: Program | None = None) -> list[tuple[str, str]]:
    choices = []

    for form_id, form_config in get_approved_ona_forms().items():
        if is_ona_form_allowed(form_id, program):
            label = form_config.get("label") or form_id
            choices.append((form_id, f"{label} ({form_id})"))

    return choices


class ImportOnaForm(BaseImportForm):
    form_id = forms.ChoiceField(
        required=True,
        choices=(),
        help_text="Select an approved ONA / INFORM form for this office/programme.",
    )
    individuals_key = forms.CharField(
        required=False,
        initial="individuals",
        help_text="JSON key that contains individual records for master/detail forms.",
    )
    household_field_mapping = forms.JSONField(
        required=False,
        initial=dict,
        help_text='JSON mapping from ONA household fields to CW fields, e.g. {"household/name": "household_name"}.',
    )
    individual_field_mapping = forms.JSONField(
        required=True,
        initial=dict,
        help_text='JSON mapping from ONA individual fields to CW fields, e.g. {"name": "full_name"}.',
    )

    def __init__(
        self,
        *args: Any,
        program: Program | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs["program"] = program
        super().__init__(*args, **kwargs)

        self.program = program
        self.fields["form_id"].choices = get_allowed_ona_form_choices(program)

        if not self.fields["form_id"].choices:
            self.cleaned_data = {}
            self.add_error(None, "No ONA / INFORM forms are approved for this office/programme.")

    def clean_form_id(self) -> str:
        form_id = self.cleaned_data["form_id"]

        if not is_ona_form_allowed(form_id, self.program):
            raise forms.ValidationError("This ONA / INFORM form is not approved for this office/programme.")

        return form_id
