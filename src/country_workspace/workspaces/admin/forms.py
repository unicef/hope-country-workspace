from typing import TYPE_CHECKING, Any

from django import forms

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm
from country_workspace.workspaces.validators import ValidatableFileValidator

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

    check_before = forms.BooleanField(required=False, help_text="Prevent import if errors")
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
        initial="full_name_i_c",
        help_text="Which column should be used as label for the household. It can use interpolation",
    )

    first_line = forms.IntegerField(required=True, initial=0, help_text="First line to process")
    fail_if_alien = forms.BooleanField(required=False)
    file = forms.FileField(validators=[ValidatableFileValidator()])
