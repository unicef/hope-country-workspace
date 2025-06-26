from hope_flex_fields.models import DataChecker
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class FieldMappingRulesValidator:
    """Validate each non-empty line against: 'sheet_name:field_name=datachecker name:field_name'."""

    def __call__(self, value: str) -> None:
        errors = []
        for idx, line in enumerate((_line.strip() for _line in value.splitlines()), start=1):
            if line:
                error = self._validate_line(line, idx)
                if error:
                    errors.append(error)
        if errors:
            raise ValidationError(errors)

    def _validate_line(self, line: str, num: int) -> ValidationError | None:
        if line.count("=") != 1:
            return self._error(num, _("Invalid format. Expected one '=' character."))
        left, right = line.split("=", 1)
        return self._validate_format_parts(left, right, num) or self._validate_datachecker_parts(right, num)

    def _validate_format_parts(self, left: str, right: str, num: int) -> ValidationError | None:
        if " " in left or left.count(":") != 1 or ":" not in right:
            expected = "sheet_name:field_name=datachecker name:field_name"
            return self._error(num, _("Invalid format. Expected format: '%(expected)s'") % {"expected": expected})
        return None

    def _validate_datachecker_parts(self, right: str, num: int) -> ValidationError | None:
        datachecker_name, field_name = right.rsplit(":", 1)
        try:
            datachecker = DataChecker.objects.get(name=datachecker_name)
        except DataChecker.DoesNotExist:
            return self._error(num, _("DataChecker '%(name)s' not found") % {"name": datachecker_name})
        if not datachecker.get_field(field_name):
            return self._error(
                num,
                _("Field '%(field)s' not found in '%(datachecker)s'")
                % {"field": field_name, "datachecker": datachecker_name},
            )
        return None

    def _error(self, num: int, message: str) -> ValidationError:
        return ValidationError(_("Line %(num)d: %(message)s.") % {"num": num, "message": message}, code="invalid_rule")
