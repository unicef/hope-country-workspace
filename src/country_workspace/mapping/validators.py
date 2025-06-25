import jmespath
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _


@deconstructible
class JMESPathValidator:
    """Validator for JMESPath expressions."""

    def __init__(self) -> None:
        self.message = _("Invalid JMESPath expression: {error}")
        self.code = "invalid_jmespath"

    def __call__(self, value: str | None) -> None:
        if not value or not value.strip():
            return

        try:
            jmespath.compile(value.strip())
        except jmespath.exceptions.JMESPathError as e:
            raise ValidationError(self.message.format(error=str(e)), code=self.code)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, self.__class__)
