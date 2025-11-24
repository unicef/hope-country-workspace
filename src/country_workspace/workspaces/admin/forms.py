from typing import TYPE_CHECKING, Any

from django import forms
from django.db.models import TextChoices
from django.utils.translation import gettext_lazy as _

from country_workspace.models import BeneficiaryGroup, Program
from country_workspace.workspaces.admin.cleaners.base import BaseActionForm
from country_workspace.workspaces.validators import ValidatableFileValidator

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker


class BulkUpdateExportForm(BaseActionForm):
    fields = forms.MultipleChoiceField(choices=[], widget=forms.CheckboxSelectMultiple())
    include_errors = forms.BooleanField(
        label=_("Include errors and validity status"),
        required=False,
        initial=False,
    )

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
    validate_after_import = forms.BooleanField(initial=True, required=False)
    fail_if_alien = forms.BooleanField(
        initial=True, required=False, help_text="Alien field will be checked on first record only"
    )
    household_mapping = forms.ModelChoiceField(
        queryset=None,
        required=False,
        help_text=_("Optional mapping to apply to household data"),
        empty_label=_("No mapping"),
    )
    individual_mapping = forms.ModelChoiceField(
        queryset=None,
        required=False,
        help_text=_("Optional mapping to apply to individual/people data"),
        empty_label=_("No mapping"),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        from country_workspace.models import MappingImporter

        # Extract custom kwargs
        program = kwargs.pop("program", None)
        kwargs.pop("office", None)

        super().__init__(*args, **kwargs)

        # Set up mapping fields based on program's data checkers
        if program:
            if program.household_checker:
                self.fields["household_mapping"].queryset = MappingImporter.objects.filter(
                    office=program.country_office, data_checker=program.household_checker
                )
            else:
                self.fields.pop("household_mapping", None)

            if program.individual_checker:
                self.fields["individual_mapping"].queryset = MappingImporter.objects.filter(
                    office=program.country_office, data_checker=program.individual_checker
                )
            else:
                self.fields.pop("individual_mapping", None)
        else:
            # Remove mapping fields if no program context
            self.fields.pop("household_mapping", None)
            self.fields.pop("individual_mapping", None)


class ImportFileForm(BaseImportForm):
    household_id_column = forms.CharField(
        required=True,
        initial="household_id",
        help_text=_(
            "Which column contains the unique identifier of the household record. It is mandatory from Master/Detail"
        ),
    )

    beneficiary_id_column = forms.CharField(
        required=True,
    )

    household_label = forms.CharField(
        required=False,
        initial="household_id",
        help_text=_("Which column should be used as label for the household. It can use interpolation"),
    )

    people_prefix = forms.CharField(
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

    def __init__(
        self,
        *args: Any,
        beneficiary_group: BeneficiaryGroup | None = None,
        program: Program | None = None,
        **kwargs: Any,
    ) -> None:
        if program:
            kwargs["program"] = program

        super().__init__(*args, **kwargs)
        if not beneficiary_group:
            return

        is_md = beneficiary_group.master_detail
        fields_to_exclude = ("people_prefix",) if is_md else ("household_id_column", "household_label")
        field_cfg = {
            "label": "Individual id column" if is_md else "People id column",
            "initial": "individual_id" if is_md else "pp_index_id",
            "help_text": (
                "Which column contains the unique identifier of the individual record."
                "It is mandatory from Master/Detail"
                if is_md
                else "Which column contains the unique identifier of the people record."
            ),
        }

        [self.fields.pop(field_name, None) for field_name in fields_to_exclude]
        [setattr(self.fields["beneficiary_id_column"], attr, v) for attr, v in field_cfg.items()]


class MassDefaultsForm(forms.Form):
    def __init__(self, *args: Any, checker: "DataChecker", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        source_form = checker.get_form()()
        for field in source_form.fields.values():
            field.required = False
        self.fields.update(source_form.fields)
