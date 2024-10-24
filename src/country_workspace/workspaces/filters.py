from typing import TYPE_CHECKING, Any

from django.http import HttpRequest
from django.urls import reverse

from adminfilters.autocomplete import LinkedAutoCompleteFilter

from country_workspace.state import state

if TYPE_CHECKING:
    from django.contrib.admin import ModelAdmin
    from django.db.models import Model, QuerySet

    from country_workspace.types import Beneficiary


class CWLinkedAutoCompleteFilter(LinkedAutoCompleteFilter):
    parent_lookup_kwarg: str

    def __init__(
        self,
        field: Any,
        request: "HttpRequest",
        params: dict[str, Any],
        model: "Model",
        model_admin: "ModelAdmin",
        field_path: str,
    ):
        self.dependants = []
        if self.parent and not self.parent_lookup_kwarg:
            self.parent_lookup_kwarg = f"{self.parent}__exact"
        super().__init__(field, request, params, model, model_admin, field_path)
        for pos, entry in enumerate(model_admin.list_filter):
            if isinstance(entry, (list, tuple)):
                if (
                    len(entry) == 2
                    and entry[0] != self.field_path
                    and entry[1].__name__ == type(self).__name__
                    and entry[1].parent == self.field_path
                ):
                    kwarg = f"{entry[0]}__exact"
                    if entry[1].parent:
                        if kwarg not in self.dependants:
                            self.dependants.extend(entry[1].dependants)
                            self.dependants.append(kwarg)

    def get_url(self) -> str:
        url = reverse("%s:autocomplete" % self.admin_site.name)
        if self.parent_lookup_kwarg in self.request.GET:
            flt = self.parent_lookup_kwarg.split("__")[-2]
            oid = self.request.GET[self.parent_lookup_kwarg]
            return f"{url}?{flt}={oid}"
        return url

    # @classmethod
    # def factory(cls, **kwargs):
    #     kwargs.setdefault(**{
    #         "filter_title": None,
    #         "lookup_name": "exact",
    #     })
    #     # kwargs["filter_title"] = title
    #     # kwargs["lookup_name"] = lookup_name
    #     return type("LinkedAutoCompleteFilter", (cls,), kwargs)


class ProgramFilter(CWLinkedAutoCompleteFilter):

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> "QuerySet[Beneficiary]":
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            # if request.usser.has_perm()
            queryset = super().queryset(request, queryset).filter(batch__program=p)
        return queryset


class BatchFilter(CWLinkedAutoCompleteFilter):
    def has_output(self) -> bool:
        return bool("batch__program__exact" in self.request.GET)

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> "QuerySet[Beneficiary]":
        if self.lookup_val:
            queryset = super().queryset(request, queryset).filter(batch=self.lookup_val)
        return queryset


class HouseholdFilter(CWLinkedAutoCompleteFilter):
    fk_name = "name"

    def has_output(self) -> bool:
        return bool(self.selected_program())

    def selected_program(self) -> str:
        return self.request.GET.get("batch__program__exact")

    def get_url(self) -> str:
        url = reverse("%s:autocomplete" % self.admin_site.namespace)
        if oid := self.selected_program():
            return f"{url}?batch__program={oid}"
        return url

    def queryset(self, request: HttpRequest, queryset: "QuerySet[Beneficiary]") -> "QuerySet[Beneficiary]":
        qs = super().queryset(request, queryset)
        if oid := self.selected_program():
            qs = qs.filter(batch__program__exact=oid)
        else:
            qs = qs.none()
        return qs
