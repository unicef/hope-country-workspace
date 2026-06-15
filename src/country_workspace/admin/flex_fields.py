from typing import Any

from admin_extra_buttons.decorators import button
from django.contrib import admin
from django.http import HttpRequest, HttpResponse

from hope_flex_fields.admin import DataCheckerAdmin, FieldsetAdmin, FlexFieldAdmin
from hope_flex_fields.models import DataChecker, Fieldset, FlexField

from country_workspace.signals import collect_invalidations


class CollectInvalidationsMixin:
    def changeform_view(
        self,
        request: HttpRequest,
        object_id: str | None = None,
        form_url: str = "",
        extra_context: dict[str, Any] | None = None,
    ) -> HttpResponse:
        if request.method == "POST":
            with collect_invalidations():
                return super().changeform_view(request, object_id, form_url, extra_context)
        return super().changeform_view(request, object_id, form_url, extra_context)


admin.site.unregister(DataChecker)
admin.site.unregister(Fieldset)
admin.site.unregister(FlexField)


@admin.register(DataChecker)
class CWDataCheckerAdmin(CollectInvalidationsMixin, DataCheckerAdmin):
    pass


@admin.register(Fieldset)
class CWFieldsetAdmin(CollectInvalidationsMixin, FieldsetAdmin):
    @button(label="Fields")
    def all_fields(self, request: HttpRequest, pk: str) -> HttpResponse:
        impl = FieldsetAdmin.all_fields.func
        if request.method == "POST":
            with collect_invalidations():
                return impl(self, request, pk)
        return impl(self, request, pk)


@admin.register(FlexField)
class CWFlexFieldAdmin(CollectInvalidationsMixin, FlexFieldAdmin):
    pass
