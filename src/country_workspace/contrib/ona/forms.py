import logging
from typing import Any

from constance import config as constance_config
from django import forms
from django.core.cache import cache
from requests import RequestException

from country_workspace.contrib.ona.client import OnaClient
from country_workspace.contrib.ona.exceptions import OnaApiError
from country_workspace.contrib.ona.transformers import DEFAULT_INDIVIDUALS_KEY
from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm

logger = logging.getLogger(__name__)

FORM_CHOICES_CACHE_TTL = 5 * 60


def get_ona_form_choices() -> list[tuple[str, str]]:
    """Return the importable forms the ONA token can access as `(form_id, label)` choices."""
    cache_key = f"ona:form-choices:{constance_config.ONA_API_URL}"
    if (cached := cache.get(cache_key)) is not None:
        return cached

    client = OnaClient(base_url=constance_config.ONA_API_URL, token=constance_config.ONA_API_TOKEN)
    choices = [
        (str(form["formid"]), f"{form.get('title') or form['formid']} ({form['formid']})")
        for form in client.get_forms()
        if form.get("downloadable", True)
    ]
    cache.set(cache_key, choices, FORM_CHOICES_CACHE_TTL)
    return choices


class ImportOnaForm(BaseImportForm):
    form_id = forms.ChoiceField(
        required=True,
        choices=(),
        help_text="Select an ONA / INFORM form.",
    )
    individuals_key = forms.CharField(
        required=False,
        initial=DEFAULT_INDIVIDUALS_KEY,
        help_text="JSON key that contains individual records for master/detail forms.",
    )

    def __init__(
        self,
        *args: Any,
        program: Program | None = None,
        **kwargs: Any,
    ) -> None:
        kwargs["program"] = program
        super().__init__(*args, **kwargs)

        if not constance_config.ONA_API_TOKEN:
            self._add_init_error("Please set ONA_API_TOKEN to use ONA / INFORM import")
            return

        try:
            self.fields["form_id"].choices = get_ona_form_choices()
        except (OnaApiError, RequestException):
            logger.exception("Could not load ONA / INFORM forms")
            self._add_init_error("Could not load ONA / INFORM forms. Please try again later.")
            return

        if not self.fields["form_id"].choices:
            self._add_init_error("No ONA / INFORM forms are available.")

    def _add_init_error(self, message: str) -> None:
        self.cleaned_data = {}
        self.add_error(None, message)
