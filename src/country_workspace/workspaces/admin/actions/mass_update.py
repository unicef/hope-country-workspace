from typing import TYPE_CHECKING, Any, Callable, Optional

from django import forms
from django.db import transaction
from django.db.models import QuerySet
from django.forms import MultiValueField, widgets
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils.text import slugify
from django.utils.translation import gettext as _

from hope_flex_fields.fields import FlexFormMixin
from strategy_field.utils import fqn

from .base import BaseActionForm

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import BeneficiaryBaseAdmin

    MassUpdateFunc = Callable[[Any, Any], Any]
    FormOperations = dict[str, tuple[str, str]]
    Operation = tuple[type[forms.Field], str, MassUpdateFunc]
    Operations = dict[str, Operation]


class OperationManager:
    def __init__(self) -> None:
        self._dict: Operations = dict()
        self._cache: dict[forms.Form, list[tuple[str, str]]] = {}

    def register(self, target: Any, name: str, func: "MassUpdateFunc") -> None:
        unique = slugify(f"{fqn(target)}_{name}_{func.__name__}")
        self._dict[unique] = (target, name, func)

    def get_function_by_id(self, id: str) -> "MassUpdateFunc":
        return self._dict.get(id)[2]

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
# operations.register(forms.Field, "set null", lambda old_value, new_value: None)
operations.register(forms.CharField, "upper", lambda old_value, new_value: old_value.upper())
operations.register(forms.CharField, "lower", lambda old_value, new_value: old_value.lower())
operations.register(forms.BooleanField, "toggle", lambda old_value, new_value: not old_value)


class MassUpdateWidget(widgets.MultiWidget):
    template_name = "workspace/actions/massupdatewidget.html"
    is_required = False

    def __init__(self, field: FlexFormMixin, attrs: Optional[dict[str, Any]] = None) -> None:
        _widgets = (
            widgets.Select(choices=[("", "-")] + operations.get_choices_for_target(field.flex_field.field.field_type)),
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


def mass_update_impl(records: "QuerySet[Beneficiary]", config: "FormOperations") -> None:
    with transaction.atomic():
        for record in records:
            for field_name, attrs in config.items():
                op, new_value = attrs
                old_value = record.flex_fields[field_name]
                func = operations.get_function_by_id(op)
                record.flex_fields[field_name] = func(old_value, new_value)
            record.save()


def mass_update(
    model_admin: "BeneficiaryBaseAdmin", request: HttpRequest, queryset: "QuerySet[Beneficiary]"
) -> HttpResponse:
    ctx = model_admin.get_common_context(request, title=_("Mass update"))
    ctx["checker"] = checker = model_admin.get_checker(request)
    form = MassUpdateForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_apply" in request.POST:
        if form.is_valid():
            mass_update_impl(queryset.all(), form.get_selected())
            model_admin.message_user(request, "Records updated successfully")
    return render(request, "workspace/actions/mass_update.html", ctx)
