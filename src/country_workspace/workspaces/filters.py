from django.db.models import QuerySet
from django.http import HttpRequest
from django.urls import reverse

from adminfilters.autocomplete import AutoCompleteFilter

from country_workspace.state import state


class ProgramFilter(AutoCompleteFilter):

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            # if request.usser.has_perm()
            queryset = super().queryset(request, queryset)
            state.program = p
        return queryset


class HouseholdFilter(AutoCompleteFilter):
    fk_name = "name"

    def __init__(self, field: str, request: HttpRequest, params, model, model_admin, field_path):
        self.request = request
        super().__init__(field, request, params, model, model_admin, field_path)

    def has_output(self) -> bool:
        return bool(self.selected_program())

    def selected_program(self) -> str:
        return self.request.GET.get("program__exact")

    def get_url(self) -> str:
        url = reverse("%s:autocomplete" % self.admin_site.namespace)
        if oid := self.selected_program():
            return f"{url}?program={oid}"
        return url

    def queryset(self, request: HttpRequest, queryset: QuerySet) -> QuerySet:
        qs = super().queryset(request, queryset)
        if oid := self.selected_program():
            qs = qs.filter(program__exact=oid)
        else:
            qs = qs.none()
        return qs
