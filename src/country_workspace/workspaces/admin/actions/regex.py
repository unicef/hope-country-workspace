from typing import TYPE_CHECKING

from django import forms
from django.db import transaction
from django.db.models import QuerySet
from django.shortcuts import render
from django.utils.translation import gettext as _

if TYPE_CHECKING:
    from hope_flex_fields.models import DataChecker

    from country_workspace.types import Beneficiary
    from country_workspace.workspaces.admin.hh_ind import CountryHouseholdIndividualBaseAdmin

    RegexRule = tuple[str, str]
    RegexRules = list(RegexRule)


class RegexUpdateForm(forms.Form):
    action = forms.CharField(widget=forms.HiddenInput)
    select_across = forms.BooleanField(widget=forms.HiddenInput)
    _selected_action = forms.CharField(widget=forms.HiddenInput)
    field = forms.ChoiceField(choices=[])

    def __init__(self, *args, **kwargs):
        checker: "DataChecker" = kwargs.pop("checker")
        super().__init__(*args, **kwargs)
        field_names = checker.get_form()().fields.keys()
        self.fields["field"].choices = zip(field_names, field_names)


def regex_update_impl(records: "QuerySet[Beneficiary]", config: "RegexRules") -> None:
    with transaction.atomic():
        for record in records:
            pass
    # for field_name, attrs in config.items():
    #     op, new_value = attrs
    #     old_value = record.flex_fields[field_name]
    #     func = operations.get_function_by_id(op)
    #     record.flex_fields[field_name] = func(old_value, new_value)
    # record.save()


def regex_update(model_admin: "CountryHouseholdIndividualBaseAdmin", request, queryset):
    ctx = model_admin.get_common_context(request, title=_("Mass update"))
    ctx["checker"] = checker = model_admin.get_checker(request)
    form = RegexUpdateForm(request.POST, checker=checker)
    ctx["form"] = form
    if "_apply" in request.POST:
        if form.is_valid():
            regex_update_impl(queryset.all(), form.get_selected())
    return render(request, "actions/mass_update.html", ctx)
