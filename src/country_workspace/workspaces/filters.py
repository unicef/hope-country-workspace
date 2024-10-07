from django.urls import reverse

from adminfilters.autocomplete import AutoCompleteFilter

from country_workspace.state import state


class ProgramFilter(AutoCompleteFilter):
    fk_name = "name"

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.request = request
        super().__init__(field, request, params, model, model_admin, field_path)

    def get_url(self):
        url = reverse("%s:autocomplete" % self.admin_site.namespace)
        if self.fk_name in self.request.GET:
            oid = self.request.GET[self.fk_name]
            return f"{url}?oid={oid}"
        return url

    def queryset(self, request, queryset):
        if self.lookup_val:
            p = state.tenant.programs.get(pk=self.lookup_val)
            # if request.usser.has_perm()
            queryset = super().queryset(request, queryset)
            state.program = p
        return queryset
