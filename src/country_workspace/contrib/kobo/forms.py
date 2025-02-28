from django import forms

from country_workspace.contrib.kobo.models import KoboAsset


class ImportKoboForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")
    individual_records_field = forms.CharField(
        required=False,
        initial="individual_questions",
        help_text="Which field contains individual records",
    )
