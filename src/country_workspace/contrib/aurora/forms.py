from django import forms


class ImportAuroraForm(forms.Form):

    batch_name = forms.CharField(required=False, help_text="Label for this batch")

    check_before = forms.BooleanField(required=False, help_text="Prevent import if errors")

    household_name_column = forms.CharField(
        required=False,
        initial="family_name",
        help_text="Which Individual's column contains the Household's name",
    )

    fail_if_alien = forms.BooleanField(required=False)
