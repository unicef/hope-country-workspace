from django import forms

from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import Program


class ImportAuroraForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch.")
    registration = forms.ModelChoiceField(
        queryset=Registration.objects.none(),
        help_text="What type of registrations are being imported.",
    )
    household_column_prefix = forms.CharField(
        initial="household_", help_text="Household's column group prefix", required=False
    )
    individuals_column_prefix = forms.CharField(
        initial="individuals_",
        help_text="Individuals' column group prefix",
    )
    household_label_column = forms.CharField(
        required=False,
        initial="family_name",
        help_text="Which Individual's column should be used as label for the household.",
    )
    check_before = forms.BooleanField(
        required=False, help_text="Prevent import if errors if data is not valid against data checker."
    )
    fail_if_alien = forms.BooleanField(
        required=False, help_text="Fails if it finds fields which do not exists in data checker."
    )

    def __init__(self, *args: tuple, program: Program | None = None, **kwargs: dict) -> None:
        super().__init__(*args, **kwargs)
        self.program = program
        if program:
            self.fields["registration"].queryset = Registration.objects.filter(project__program=program, active=True)
            if not getattr(program.beneficiary_group, "master_detail", False):
                self.fields = {
                    key: value
                    for key, value in self.fields.items()
                    if key not in ("household_column_prefix", "household_label_column")
                }
