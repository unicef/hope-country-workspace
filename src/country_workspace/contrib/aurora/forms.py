from typing import Any

from django import forms

from country_workspace.contrib.aurora.models import Registration
from country_workspace.models import Program
from country_workspace.mapping.models import MappingProfile


class ImportAuroraForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch.")
    registration = forms.ModelChoiceField(
        queryset=Registration.objects.none(),
        help_text="What type of registrations are being imported.",
    )
    household_column_prefix = forms.CharField(
        initial="household-info_", help_text="Household's column group prefix", required=False
    )
    individuals_column_prefix = forms.CharField(
        initial="individual-details_",
        help_text="Individuals' column group prefix",
    )
    household_label_column = forms.CharField(
        required=False,
        initial="family_name",
        help_text="Which Individual's column should be used as label for the household.",
    )
    mapping_profile = forms.ModelChoiceField(
        required=False,
        queryset=MappingProfile.objects.none(),
        help_text="Mapping profile to use for this import. It will be used to map fields from the file to the model.",
    )
    check_before = forms.BooleanField(
        required=False, help_text="Prevent import if errors if data is not valid against data checker."
    )
    fail_if_alien = forms.BooleanField(
        required=False, help_text="Fails if it finds fields which do not exists in data checker."
    )

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not program:
            self.fields["registration"].queryset = Registration.objects.none()
            self.fields["mapping_profile"].queryset = MappingProfile.objects.none()
            return

        is_master_detail = program.beneficiary_group and program.beneficiary_group.master_detail
        schema = MappingProfile.ImportSchema.HH_IND if is_master_detail else MappingProfile.ImportSchema.PEOPLE
        if not is_master_detail:
            self.fields = {
                key: value
                for key, value in self.fields.items()
                if key not in ("household_column_prefix", "household_label_column")
            }

        self.fields["registration"].queryset = Registration.objects.filter(project__program=program, active=True)
        self.fields["mapping_profile"].queryset = MappingProfile.objects.filter(
            source_type__in=[MappingProfile.SourceType.AURORA, MappingProfile.SourceType.ANY],
            import_schema__in=[schema, MappingProfile.ImportSchema.ANY],
            program=program,
            is_active=True,
        ).select_related("parent")
