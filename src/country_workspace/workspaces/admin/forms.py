from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from country_workspace.workspaces.admin.cleaners.base import BaseActionForm
from country_workspace.workspaces.validators import ValidatableFileValidator
from country_workspace.models import BeneficiaryGroup

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

    def __init__(self, *args: Any, beneficiary_group: BeneficiaryGroup | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if beneficiary_group and beneficiary_group.master_detail is False:
            self.fields["target"].initial = "ind"
            self.fields["target"].help_text = "Only Individual updates are allowed for this program."
            self.fields["target"].widget.attrs.update(
                {
                    "readonly": True,
                    "style": "background-color:var(--darkened-bg); color:var(--body-quiet-color); pointer-events:none;",
                }
            )


class ValidateMode(TextChoices):
    NONE = "none", _("Skip validation — import data as is.")
    CHECK_BEFORE = "check_before", _("Prevent import if data is not valid against data checker.")
    CHECK_AND_FAIL_IF_ALIEN = (
        "check_and_fail_if_alien",
        _("Prevent import if data is invalid AND fail if an alien field is found."),
    )


class BaseImportForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")
    validate_mode = forms.TypedChoiceField(
        choices=ValidateMode.choices,
        coerce=ValidateMode,
        empty_value=ValidateMode.CHECK_AND_FAIL_IF_ALIEN,
        initial=ValidateMode.CHECK_AND_FAIL_IF_ALIEN,
        required=True,
        help_text=_("How to validate data before import"),
    )


class ImportFileForm(BaseImportForm):
    pk_column_name = forms.CharField(
        required=True,
        initial="household_id",
        help_text=_("Which column contains the unique identifier of the record. It is mandatory from Master/detail"),
    )

    master_column_label = forms.CharField(
        required=False,
        initial="household_id",
        help_text=_("Which column contains the 'link' to the household record."),
    )

    detail_column_label = forms.CharField(
        required=False,
        initial="household_id",
        help_text=_("Which column should be used as label for the household. It can use interpolation"),
    )

    people_column_prefix = forms.CharField(
        required=False,
        initial="pp_",
        help_text=_("People' column group prefix"),
    )

    first_line = forms.IntegerField(
        required=True,
        initial=2,
        min_value=2,
        help_text="First data row to process (row 1 is headers, data starts from row 2)",
    )

    file = forms.FileField(validators=[ValidatableFileValidator()])

    def __init__(self, *args: Any, beneficiary_group: BeneficiaryGroup | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if beneficiary_group:
            exclude_fields = (
                ("people_column_prefix",)
                if beneficiary_group.master_detail
                else ("pk_column_name", "master_column_label", "detail_column_label")
            )
            for field_name in exclude_fields:
                self.fields.pop(field_name, None)
