from typing import Any

from django import forms

from country_workspace.contrib.kobo.sync import make_client
from country_workspace.models import Program
from country_workspace.workspaces.admin.forms import BaseImportForm


def get_kobo_project_choices(kobo_country_code: str) -> list[tuple[str, str]]:
    """Return the Kobo projects of the country as `(uid, name)` choices."""
    return [(asset.uid, asset.name) for asset in make_client(kobo_country_code).assets]


class ImportKoboForm(BaseImportForm):
    project_id = forms.ChoiceField(required=True, choices=(), help_text="Select a project")
    individual_records_field = forms.CharField(
        required=False,
        initial="individual_questions",
        help_text="Which field contains individual records",
    )

    def __init__(
        self,
        *args: Any,
        kobo_country_code: str | None = None,
        program: Program | None = None,
        load_choices: bool = True,
        **kwargs: Any,
    ) -> None:
        kwargs["program"] = program

        super().__init__(*args, **kwargs)
        if kobo_country_code:
            if load_choices:
                self.fields["project_id"].choices = get_kobo_project_choices(kobo_country_code)
            else:
                self.defer_choices("project_id", "kobo")
        else:
            self.cleaned_data = {}
            self.add_error(None, "Please set country iso code for office to use Kobo import")
