from django.urls import reverse

from adminfilters.autocomplete import AutoCompleteFilter


class ProgramFilter(AutoCompleteFilter):
    fk_name = "name"

    def __init__(self, field, request, params, model, model_admin, field_path):
        self.request = request
        super().__init__(field, request, params, model, model_admin, field_path)

    # def has_output(self):
    #     return "project__organization__exact" in self.request.GET

    def get_url(self):
        url = reverse("%s:autocomplete" % self.admin_site.namespace)
        if self.fk_name in self.request.GET:
            oid = self.request.GET[self.fk_name]
            return f"{url}?oid={oid}"
        return url
