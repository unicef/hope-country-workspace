from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.template import Context, Library

if TYPE_CHECKING:
    from django.forms import BoundField

    from country_workspace.models.base import Validable


register = Library()


@register.simple_tag(takes_context=True)
def field_error(context: Context, field: "BoundField") -> list[ValidationError]:
    obj: "Validable" | None = context.get("original")
    form_errors = field.form.errors.get(field.name, [])
    if obj:
        errs = obj.errors.get(field.name, [])
        return form_errors + errs
    return form_errors
