from adminfilters.autocomplete import AutoCompleteFilter
from django.contrib import admin
from django.forms import ModelForm
from django.http import HttpRequest

from country_workspace.admin.base import BaseModelAdmin
from country_workspace.models import Transformer


@admin.register(Transformer)
class TransformerAdmin(BaseModelAdmin):
    readonly_fields = ("created_at", "last_modified", "created_by")
    list_display = ("name", "office", "created_by", "created_at", "last_modified")
    list_filter = (
        ("office", AutoCompleteFilter),
        ("created_by", AutoCompleteFilter),
    )
    search_fields = ("name", "description")
    autocomplete_fields = ("office",)
    fields = (
        "name",
        "description",
        "office",
        "value_transformations",
        "created_by",
        "created_at",
        "last_modified",
    )

    def save_model(self, request: HttpRequest, obj: Transformer, form: ModelForm, change: bool) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
