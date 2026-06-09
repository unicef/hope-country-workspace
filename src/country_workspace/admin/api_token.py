from django.contrib import admin
from django.http import HttpRequest
from hope_api_auth.admin import APITokenAdmin as BaseAPITokenAdmin
from hope_api_auth.admin import APITokenForm as BaseAPITokenForm

from country_workspace.models import APIToken


class APITokenForm(BaseAPITokenForm):
    class Meta(BaseAPITokenForm.Meta):
        model = APIToken
        fields = (*BaseAPITokenForm.Meta.fields, "valid_for")


@admin.register(APIToken)
class APITokenAdmin(BaseAPITokenAdmin):
    form = APITokenForm
    filter_horizontal = (
        *getattr(BaseAPITokenAdmin, "filter_horizontal", ()),
        "valid_for",
    )
    search_fields = (*BaseAPITokenAdmin.search_fields, "valid_for__name")

    def get_fields(self, request: HttpRequest, obj: APIToken | None = None) -> tuple[str, ...]:
        fields = super().get_fields(request, obj)
        return (*fields, "valid_for") if "valid_for" not in fields else fields
