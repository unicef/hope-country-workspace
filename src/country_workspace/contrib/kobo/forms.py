from typing import Any

from country_workspace.contrib.kobo.sync import make_client
from django import forms


class ImportKoboForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")
    project_id = forms.ChoiceField(required=True, choices=(), help_text="Select a project")
    individual_records_field = forms.CharField(
        required=False,
        initial="individual_questions",
        help_text="Which field contains individual records",
    )

    def __init__(self, *args: Any, kobo_country_code: str | None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if kobo_country_code:
            client = make_client(kobo_country_code)
            self.fields["project_id"].choices = [(asset.uid, asset.name) for asset in client.assets]
        else:
            self.cleaned_data = {}  # type: ignore
            self.add_error(None, "Please set country iso code for office to use Kobo import")
