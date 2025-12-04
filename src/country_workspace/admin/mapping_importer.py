from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import MappingImporter


@admin.register(MappingImporter)
class MappingImporterAdmin(BaseModelAdmin):
    readonly_fields = ("created_at", "last_modified", "created_by")
    list_display = ("name", "office", "data_checker", "created_by", "created_at", "last_modified")
    list_filter = (
        ("office", AutoCompleteFilter),
        ("data_checker", AutoCompleteFilter),
        ("created_by", AutoCompleteFilter),
    )
    search_fields = ("name", "description")
    autocomplete_fields = ("office", "data_checker")

    def save_model(self, request: HttpRequest, obj: MappingImporter, form: ModelForm, change: bool) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
