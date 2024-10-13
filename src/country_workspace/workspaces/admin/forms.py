from pathlib import Path

from django import forms
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext as _


@deconstructible
class ValidatableFileValidator(object):
    error_messages = {"invalid_file": _("Unsupported file format '%s'")}

    def __call__(self, f):
        if Path(f.name).suffix not in [".xlsx"]:
            raise ValidationError(self.error_messages["invalid_file"] % Path(f.name).suffix)


class ImportFileForm(forms.Form):
    batch_name = forms.CharField(required=False, help_text="Label for this batch")

    check_before = forms.BooleanField(required=False, help_text="Prevent import if errors")
    pk_column_name = forms.CharField(
        required=True,
        initial="household_id",
        help_text="Which column contains the unique identifier of the record." "It is mandatory from Master/detail",
    )

    description_column_name = forms.CharField(required=False, initial="")

    first_line = forms.IntegerField(required=True, initial=0, help_text="First line to process")
    fail_if_alien = forms.BooleanField(required=False)
    file = forms.FileField(validators=[ValidatableFileValidator()])
