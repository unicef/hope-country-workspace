from django import forms

from country_workspace.contrib.kobo.models import KoboAsset


class ImportKoboAssetsForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")


class ImportKoboDataForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")
    individual_records_field = forms.CharField(
        required=False,
        initial="individual_questions",
        help_text="Which field contains individual records",
    )
    assets = forms.ModelMultipleChoiceField(
        widget=forms.CheckboxSelectMultiple,
        queryset=KoboAsset.objects.all(),
        help_text="Which assets should be imported",
    )
