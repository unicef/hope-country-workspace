import re
from typing import TYPE_CHECKING, Any

from django import forms
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import render
from django.utils.translation import gettext as _

from .base import BaseActionForm

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import CountryHouseholdIndividualBaseAdmin

    RegexRule = tuple[str, str]
    RegexRules = list(RegexRule)


class RegexFormField(forms.CharField):
    def clean(self, value: Any) -> Any:
        super().clean(value)
        try:
            re.compile(value)
            return value
        except Exception:
            raise forms.ValidationError("Invalid regex")


class RegexUpdateForm(BaseActionForm):
    field = forms.ChoiceField(choices=[])
    regex = RegexFormField()
    subst = forms.CharField()

    def __init__(self, *args, **kwargs):
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        field_names = checker.get_form()().fields.keys()
        self.fields["field"].choices = zip(field_names, field_names)


def regex_update_impl(records: "QuerySet[Beneficiary]", config: dict[str, Any]) -> None:
    if isinstance(config["regex"], str):
        config["regex"] = re.compile(config["regex"])

    field_name = config["field"]

    with transaction.atomic():
        for record in records:
            old_value = record.flex_fields.get(field_name, "")
            new_value = config["regex"].sub(config["subst"], old_value, 1)

            record.flex_fields[field_name] = new_value
            record.save()


def regex_update(model_admin: "CountryHouseholdIndividualBaseAdmin", request, queryset):
    ctx = model_admin.get_common_context(request, title=_("Regex update"))
    ctx["checker"] = checker = model_admin.get_checker(request)
    if "_preview" in request.POST:
        form = RegexUpdateForm(request.POST, checker=checker)
        if form.is_valid():
            regex_update_impl(queryset.all(), form.cleaned_data)
            model_admin.message_user(request, "Records updated successfully")
    else:
        form = RegexUpdateForm(request.POST, checker=checker)

    ctx["form"] = form
    return render(request, "workspace/actions/regex.html", ctx)
