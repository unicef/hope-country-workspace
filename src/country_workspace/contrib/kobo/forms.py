from django import forms


class ImportKoboForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")
    country_code = forms.CharField(
        required=False,
        help_text="Country ISO code",
        min_length=3,
        max_length=3,
    )
    individual_records_field = forms.CharField(
        required=False,
        initial="individual_questions",
        help_text="Which field contains individual records",
    )
