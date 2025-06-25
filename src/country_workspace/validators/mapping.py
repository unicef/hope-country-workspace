from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class JSONFieldStringListValidator:
    """Validator for JSONField containing list of strings."""

    def __init__(self) -> None:
        self.message = _("Must be a list of non-empty strings")
        self.code = "invalid_string_list"

    def __call__(self, value: list[str] | None) -> None:
        if value is None:
            return

        if not isinstance(value, list):
            raise ValidationError(self.message, code=self.code)

        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValidationError(self.message, code=self.code)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__)
