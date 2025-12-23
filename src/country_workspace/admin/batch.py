from admin_extra_buttons.api import button, choice
from admin_extra_buttons.buttons import ChoiceButton, LinkButton
from admin_extra_buttons.decorators import link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.http import HttpRequest, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse

from ..models import Batch
from .base import BaseModelAdmin


@admin.register(Batch)
class BatchAdmin(BaseModelAdmin):
    list_display = ("name", "import_date", "imported_by", "program", "source")
    list_filter = (
        # "country_office",
        # "program",
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
        ("imported_by", AutoCompleteFilter),
        "source",
    )
    readonly_fields = ("country_office", "program", "imported_by")
    search_fields = ("name",)
    ordering = ("-import_date",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    @button(change_list=False, label="All Beneficiaries", visible=False)
    def beneficiaries(self, request: HttpRequest, pk: str) -> None:
        batch = self.get_object(request, pk)
        households = batch.household_set.all()
        individuals = batch.individual_set.all()
        context = {
            "batch": batch,
            "households": households,
            "individuals": individuals,
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
        }
        return render(request, "admin/country_workspace/batch_beneficiaries.html", context)

    @button(change_list=False, label="All Beneficiaries", visible=False)
    def _beneficiaries_choice(self, request: HttpRequest, pk: str) -> HttpResponseRedirect:
        opts = self.model._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_beneficiaries", args=[pk])
        return HttpResponseRedirect(url)

    @button(change_list=False, visible=False)
    def _households_choice(self, request: HttpRequest, pk: str) -> HttpResponseRedirect:
        url = reverse("admin:country_workspace_household_changelist")
        return HttpResponseRedirect(f"{url}?batch__exact={pk}")

    @button(change_list=False, visible=False)
    def _individuals_choice(self, request: HttpRequest, pk: str) -> HttpResponseRedirect:
        url = reverse("admin:country_workspace_individual_changelist")
        return HttpResponseRedirect(f"{url}?batch__exact={pk}")

    @choice(change_list=False, label="Related Records")
    def related_records(self, button: ChoiceButton) -> None:
        button.choices = [
            self._beneficiaries_choice,
            self._households_choice,
            self._individuals_choice,
        ]

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countrybatch_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]
