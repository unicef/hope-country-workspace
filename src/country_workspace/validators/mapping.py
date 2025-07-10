from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class FieldMappingRulesValidator:
    """Validate each non-empty line against: 'old_fieldname=new_fieldname'."""

    def __call__(self, value: str) -> None:
        errors = []
        for idx, line in enumerate((raw_line.strip() for raw_line in value.splitlines()), start=1):
            if line:
                error = self._validate_line(line, idx)
                if error:
                    errors.append(error)
        if errors:
            raise ValidationError(errors)

    def _validate_line(self, line: str, num: int) -> ValidationError | None:
        if line.count("=") != 1:
            return self._error(num, _("Invalid format. Expected one '=' character."))

        old_field, new_field = (field.strip() for field in line.split("="))
        if not old_field or not new_field:
            return self._error(num, _("Invalid format. Expected format: 'old_fieldname=new_fieldname'"))
        if old_field == new_field:
            return self._error(num, _("Field names must be different"))

        return None

    def _error(self, num: int, message: str) -> ValidationError:
        return ValidationError(_("Line %(num)d: %(message)s") % {"num": num, "message": message}, code="invalid_rule")
