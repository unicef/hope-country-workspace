from typing import TYPE_CHECKING, Any, Callable

from django import forms
from django.db import transaction
from django.db.models import QuerySet
from django.forms import MultiValueField, widgets
from django.shortcuts import render
from django.utils.text import slugify
from django.utils.translation import gettext as _

from hope_flex_fields.fields import FlexFormMixin
from strategy_field.utils import fqn

from .base import BaseActionForm

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import CountryHouseholdIndividualBaseAdmin

    MassUpdateFunc = Callable[[Any, Any], Any]
    FormOperations = dict[str, tuple[str, str]]
    Operation = tuple[Any, str, MassUpdateFunc]
    Operations = dict[str, Operation]


class OperationManager:
    def __init__(self):
        self._dict: dict[str, "Operation"] = dict()
        self._cache = {}

    def register(self, target: Any, name: str, func: "MassUpdateFunc"):
        unique = slugify(f"{fqn(target)}_{name}_{func.__name__}")
        self._dict[unique] = (target, name, func)

    def get_function_by_id(self, id) -> "MassUpdateFunc":
        return self._dict.get(id)[2]

    def get_choices_for_target(self, target):
        ret = []
        if target not in self._cache:
            for id, attrs in self._dict.items():
                if issubclass(target, attrs[0]):
                    ret.append([id, attrs[1]])
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

    def __init__(self, field: FlexFormMixin, attrs=None):
        _widgets = (
            widgets.Select(choices=[("", "-")] + operations.get_choices_for_target(field.flex_field.field.field_type)),
            field.widget,
        )
        super().__init__(_widgets, attrs)

    def decompress(self, value):
        if value:
            return [value, "", ""]
        return [None, None, None]


class MassUpdateField(MultiValueField):
    widget = MassUpdateWidget

    def __init__(self, *, field, **kwargs):
        field.required = False
        fields = (forms.CharField(required=False), field)
        self.widget = MassUpdateWidget(field)
        super().__init__(fields, require_all_fields=False, required=False, **kwargs)

    def compress(self, data_list):
        return data_list


class MassUpdateForm(BaseActionForm):

    def __init__(self, *args, **kwargs):
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        for name, fld in checker.get_form()().fields.items():
            self.fields[f"flex_fields__{name}"] = MassUpdateField(label=fld.label, field=fld)

    def get_selected(self) -> "FormOperations":
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


def mass_update(model_admin: "CountryHouseholdIndividualBaseAdmin", request, queryset):
    ctx = model_admin.get_common_context(request, title=_("Mass update"))
    ctx["checker"] = checker = model_admin.get_checker(request)
    form = MassUpdateForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_apply" in request.POST:
        if form.is_valid():
            mass_update_impl(queryset.all(), form.get_selected())
    return render(request, "workspace/actions/mass_update.html", ctx)
