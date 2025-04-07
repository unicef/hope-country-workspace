from typing import TYPE_CHECKING, Any

from django import forms
from django.db import transaction
from django.forms import MultiValueField, widgets
from django.utils.text import slugify
from hope_flex_fields.fields import FlexFormMixin
from strategy_field.utils import fqn

from .base import BaseActionForm

if TYPE_CHECKING:
    from collections.abc import Callable

    from django.db.models import QuerySet
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary

    MassUpdateFunc = Callable[[Any, Any], Any]
    FormOperations = dict[str, tuple[str, str]]
    Operation = tuple[type[forms.Field], str, MassUpdateFunc]
    Operations = dict[str, Operation]


class OperationManager:
    def __init__(self) -> None:
        self._dict: Operations = {}
        self._cache: dict[forms.Form, list[tuple[str, str]]] = {}

    def register(self, target: Any, name: str, func: "MassUpdateFunc") -> None:
        unique = slugify(f"{fqn(target)}_{name}_{func.__name__}")
        self._dict[unique] = (target, name, func)

    def get_function_by_id(self, id_: str) -> "MassUpdateFunc":
        return self._dict.get(id_)[2]

    def get_choices_for_target(self, target: type[forms.Field]) -> list[tuple[str, str]]:
        ret: list[tuple[str, str]] = []
        if target not in self._cache:
            for _id, attrs in self._dict.items():
                if issubclass(target, attrs[0]):
                    ret.append((_id, attrs[1]))
            self._cache[target] = ret
        return self._cache[target]


operations = OperationManager()
operations.register(forms.Field, "set", lambda old_value, new_value: new_value)
operations.register(forms.Field, "set null", lambda old_value, new_value: None)
operations.register(forms.CharField, "upper", lambda old_value, new_value: old_value.upper())
operations.register(forms.CharField, "lower", lambda old_value, new_value: old_value.lower())
operations.register(forms.BooleanField, "toggle", lambda old_value, new_value: not old_value)


class MassUpdateWidget(widgets.MultiWidget):
    template_name = "workspace/actions/massupdatewidget.html"
    is_required = False

    def __init__(self, field: FlexFormMixin, attrs: dict[str, Any] | None = None) -> None:
        _widgets = (
            widgets.Select(
                choices=[("", "-")] + operations.get_choices_for_target(field.flex_field.definition.field_type),
            ),
            field.widget,
        )
        super().__init__(_widgets, attrs)

    def decompress(self, value: str) -> tuple[str | None, str | None, str | None]:
        if value:
            return value, "", ""
        return None, None, None


class MassUpdateField(MultiValueField):
    widget = MassUpdateWidget

    def __init__(self, *, field: FlexFormMixin, **kwargs: Any) -> None:
        field.required = False
        fields = (forms.CharField(required=False), field)
        self.widget = MassUpdateWidget(field)
        super().__init__(fields, require_all_fields=False, required=False, **kwargs)

    def compress(self, data_list: list[Any]) -> Any:
        return data_list


class MassUpdateForm(BaseActionForm):
    _create_missing_fields = forms.BooleanField(required=False)

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        for name, fld in checker.get_form()().fields.items():
            self.fields[f"flex_fields__{name}"] = MassUpdateField(label=fld.label, field=fld)

    def get_selected(self) -> "dict[str, Any]":
        ret = {}
        for k, v in self.cleaned_data.items():
            if k.startswith("flex_fields__") and v and v[0] != "":
                ret[k.replace("flex_fields__", "")] = v[0:]
        return ret


def mass_update_impl(
    queryset: "QuerySet[Beneficiary]",
    config: "FormOperations",
    create_missing_fields: bool = False,
) -> None:
    with transaction.atomic():
        for record in queryset.all():
            for field_name, attrs in config.items():
                op, new_value = attrs
                if field_name in record.flex_fields:
                    old_value = record.flex_fields[field_name]
                    func = operations.get_function_by_id(op)
                    record.flex_fields[field_name] = func(old_value, new_value)
                elif create_missing_fields:
                    record.flex_fields[field_name] = func("", new_value)
            record.save()
