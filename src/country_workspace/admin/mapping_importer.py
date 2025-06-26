from adminfilters.autocomplete import AutoCompleteFilter, LinkedAutoCompleteFilter
from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import MappingImporter


@admin.register(MappingImporter)
class MappingImporterAdmin(BaseModelAdmin):
    exclude = ("country_office",)
    readonly_fields = ("created_at", "last_modified", "created_by")
    list_display = ("name", "country_office", "program", "created_at", "last_modified", "created_by")
    list_filter = (
        ("country_office", LinkedAutoCompleteFilter.factory(parent=None)),
        ("program", LinkedAutoCompleteFilter.factory(parent="country_office")),
        ("created_by", AutoCompleteFilter),
    )
    search_fields = ("name",)

    def save_model(self, request: HttpRequest, obj: MappingImporter, form: ModelForm, change: bool) -> None:
        if not change:
            obj.created_by = request.user
        obj.country_office = obj.program.country_office
        super().save_model(request, obj, form, change)
