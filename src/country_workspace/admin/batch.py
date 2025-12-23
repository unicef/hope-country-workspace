from admin_extra_buttons.buttons import ChoiceButton, LinkButton
from admin_extra_buttons.decorators import button, link
from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.http import HttpRequest
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

    @button(change_list=False, label="Related Records", button_class=ChoiceButton)
    def related_records(self, btn: ChoiceButton) -> None:
        obj = btn.context["original"]
        opts = self.model._meta
        beneficiaries_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_beneficiaries", args=[obj.pk])
        base_hh = reverse("admin:country_workspace_household_changelist")
        base_ind = reverse("admin:country_workspace_individual_changelist")

        btn.choices = [
            {"label": "All Beneficiaries", "url": beneficiaries_url},
            {"label": "Members (HH)", "url": f"{base_hh}?batch__exact={obj.pk}"},
            {"label": "Members (Ind)", "url": f"{base_ind}?batch__exact={obj.pk}"},
        ]

    @link(change_list=True, change_form=False)
    def view_in_workspace(self, btn: "LinkButton") -> None:
        if "request" in btn.context:
            req = btn.context["request"]
            base = reverse("workspace:workspaces_countrybatch_changelist")
            btn.href = f"{base}?%s" % req.META["QUERY_STRING"]
