from typing import TYPE_CHECKING, Any

from django import forms
from country_workspace.workspaces.admin.cleaners.base import BaseActionForm
from country_workspace.workspaces.validators import ValidatableFileValidator
from country_workspace.models import MappingProfile, Program

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class BulkUpdateExportForm(BaseActionForm):
    fields = forms.MultipleChoiceField(choices=[], widget=forms.CheckboxSelectMultiple())

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        self.fields["fields"].choices = [(name, name) for name, fld in checker.get_form()().fields.items()]


class BulkUpdateImportForm(forms.Form):
    description = forms.CharField(
        required=False,
        help_text="Description of the bulk update from file",
    )
    target = forms.ChoiceField(
        choices=(("hh", "Household"), ("ind", "Individual")),
        help_text="Which entity to update",
    )
    file = forms.FileField(
        validators=[ValidatableFileValidator()],
        help_text=".xlsx file with the updates",
    )


class ImportFileForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")

    pk_column_name = forms.CharField(
        required=True,
        initial="household_id",
        help_text="Which column contains the unique identifier of the record.It is mandatory from Master/detail",
    )

    master_column_label = forms.CharField(
        required=False,
        initial="household_id",
        help_text="Which column contains the 'link' to the household record.",
    )

    detail_column_label = forms.CharField(
        required=False,
        initial="household_id",
        help_text="Which column should be used as label for the household. It can use interpolation",
    )

    first_line = forms.IntegerField(required=True, initial=0, help_text="First line to process")

    mapping_profile = forms.ModelChoiceField(
        required=False,
        queryset=MappingProfile.objects.none(),
        help_text="Mapping profile to use for this import.",
    )

    check_before = forms.BooleanField(
        required=False, help_text="Prevent import if errors if data is not valid against data checker."
    )
    fail_if_alien = forms.BooleanField(
        required=False, help_text="Fails if it finds fields which do not exists in data checker."
    )
    file = forms.FileField(validators=[ValidatableFileValidator()])

    def __init__(self, *args: Any, program: Program | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if not program:
            self.fields["mapping_profile"].queryset = MappingProfile.objects.none()
            return

        is_master_detail = program.beneficiary_group and program.beneficiary_group.master_detail
        schema = MappingProfile.ImportSchema.HH_IND if is_master_detail else MappingProfile.ImportSchema.PEOPLE
        self.fields["mapping_profile"].queryset = MappingProfile.objects.filter(
            source_type__in=[MappingProfile.SourceType.XLS, MappingProfile.SourceType.ANY],
            import_schema__in=[schema, MappingProfile.ImportSchema.ANY],
            program=program,
            is_active=True,
        ).select_related("parent")
