from pathlib import Path

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class ValidatableFileValidator:
    error_messages = {"invalid_file": _("Unsupported file format '%s'")}

    def __call__(self, f: Path) -> None:
        if Path(f.name).suffix != ".xlsx":
            raise ValidationError(self.error_messages["invalid_file"] % Path(f.name).suffix)
