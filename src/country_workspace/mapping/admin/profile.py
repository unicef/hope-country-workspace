from django.contrib import admin
from django import forms
from django.db import models
from django.http import HttpRequest

from country_workspace.mapping.models import MappingProfile
from country_workspace.admin.base import BaseModelAdmin


@admin.register(MappingProfile)
class MappingProfileAdmin(BaseModelAdmin):
    list_display = ("name", "source_type", "import_schema", "is_active", "inheritance")
    list_filter = ("source_type", "import_schema", "program", "is_active")
    search_fields = ("name", "description")
    filter_horizontal = ("program",)
    fields = (
        "name",
        "description",
        "parent",
        "source_type",
        "import_schema",
        "program",
        "is_active",
        "created_by",
        "created_at",
        "updated_at",
    )
    readonly_fields = ("created_by", "created_at", "updated_at")

    @admin.display(description="Inheritance Chain")
    def inheritance(self, obj: MappingProfile) -> str:
        return obj.get_inheritance_chain()

    def get_queryset(self, request: HttpRequest) -> models.QuerySet[MappingProfile]:
        return super().get_queryset(request).select_related("parent", "created_by").prefetch_related("program")

    def save_model(
        self, request: HttpRequest, obj: MappingProfile, form: forms.ModelForm | None = None, change: bool = False
    ) -> None:
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
