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
    check_before = forms.BooleanField(required=False, help_text="Prevent import if errors")
    pk_column_name = forms.CharField(required=True, initial="household_id")
    first_line = forms.IntegerField(required=True, initial=0, help_text="First line to process")
    fail_if_alien = forms.BooleanField(required=False)
    file = forms.FileField(validators=[ValidatableFileValidator()])
