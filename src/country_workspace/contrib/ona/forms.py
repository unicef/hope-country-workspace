from typing import Any

from django import forms

from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm


class ImportOnaForm(BaseImportForm):
    form_id = forms.CharField(
        required=True,
        help_text="ONA / INFORM form ID, for example 9153.",
    )
    token = forms.CharField(
        required=True,
        widget=forms.PasswordInput(render_value=True),
        help_text="ONA API token. It is stored in the async job config only.",
    )
    base_url = forms.URLField(
        required=False,
        initial="https://api.ona.io",
        help_text="ONA API base URL. Default is https://api.ona.io.",
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