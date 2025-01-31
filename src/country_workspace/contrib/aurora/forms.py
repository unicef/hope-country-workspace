from django import forms

from country_workspace.models import Program
from country_workspace.models import Registration


class ImportAuroraForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch.")

    registration = forms.ModelChoiceField(
        queryset=Registration.objects.none(),
        help_text="What type of registrations are being imported.",
    )

    check_before = forms.BooleanField(required=False, help_text="Prevent import if errors.")

    household_name_column = forms.CharField(
        required=False,
        initial="family_name",
        help_text="Which Individual's column contains the Household's name.",
    )

    fail_if_alien = forms.BooleanField(required=False, help_text="Fail if found fields dose not exists in validator.")

    def __init__(self, *args: tuple, program: Program | None = None, **kwargs: dict) -> None:
        super().__init__(*args, **kwargs)
        if program:
            self.fields["registration"].queryset = Registration.objects.filter(program=program)
